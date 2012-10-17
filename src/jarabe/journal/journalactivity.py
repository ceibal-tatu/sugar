# Copyright (C) 2006, Red Hat, Inc.
# Copyright (C) 2007, One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import logging
from gettext import gettext as _
import uuid

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkX11
import dbus
import statvfs
import os

from sugar3.graphics.window import Window
from sugar3.graphics.icon import Icon
from sugar3.graphics.alert import Alert, ErrorAlert, ConfirmationAlert

from sugar3.bundle.bundle import ZipExtractException, RegistrationException
from sugar3 import env
from sugar3.activity import activityfactory
from gi.repository import SugarExt


from jarabe.model import bundleregistry
from jarabe.journal.journaltoolbox import MainToolbox, DetailToolbox
from jarabe.journal.journaltoolbox import EditToolbox
from jarabe.journal.listview import ListView
from jarabe.journal.listmodel import ListModel
from jarabe.journal.detailview import DetailView
from jarabe.journal.volumestoolbar import VolumesToolbar
from jarabe.journal import misc
from jarabe.journal.journalentrybundle import JournalEntryBundle
from jarabe.journal.objectchooser import ObjectChooser
from jarabe.journal.modalalert import ModalAlert
from jarabe.journal import model
from jarabe.journal.journalwindow import JournalWindow
from jarabe.journal.journalwindow import show_normal_cursor


J_DBUS_SERVICE = 'org.laptop.Journal'
J_DBUS_INTERFACE = 'org.laptop.Journal'
J_DBUS_PATH = '/org/laptop/Journal'

_SPACE_TRESHOLD = 52428800
_BUNDLE_ID = 'org.laptop.JournalActivity'

_journal = None
_mount_point = None


class JournalActivityDBusService(dbus.service.Object):
    def __init__(self, parent):
        self._parent = parent
        session_bus = dbus.SessionBus()
        bus_name = dbus.service.BusName(J_DBUS_SERVICE,
            bus=session_bus, replace_existing=False, allow_replacement=False)
        logging.debug('bus_name: %r', bus_name)
        dbus.service.Object.__init__(self, bus_name, J_DBUS_PATH)

    @dbus.service.method(J_DBUS_INTERFACE,
        in_signature='s', out_signature='')
    def ShowObject(self, object_id):
        """Pop-up journal and show object with object_id"""

        logging.debug('Trying to show object %s', object_id)

        if self._parent.show_object(object_id):
            self._parent.reveal()

    def _chooser_response_cb(self, chooser, response_id, chooser_id):
        logging.debug('JournalActivityDBusService._chooser_response_cb')
        if response_id == Gtk.ResponseType.ACCEPT:
            object_id = chooser.get_selected_object_id()
            self.ObjectChooserResponse(chooser_id, object_id)
        else:
            self.ObjectChooserCancelled(chooser_id)
        chooser.destroy()
        del chooser

    @dbus.service.method(J_DBUS_INTERFACE, in_signature='is',
                         out_signature='s')
    def ChooseObject(self, parent_xid, what_filter=''):
        chooser_id = uuid.uuid4().hex
        if parent_xid > 0:
            display = Gdk.Display.get_default()
            parent = GdkX11.X11Window.foreign_new_for_display( \
                display, parent_xid)
        else:
            parent = None
        chooser = ObjectChooser(parent, what_filter)
        chooser.connect('response', self._chooser_response_cb, chooser_id)
        chooser.show()

        return chooser_id

    @dbus.service.signal(J_DBUS_INTERFACE, signature='ss')
    def ObjectChooserResponse(self, chooser_id, object_id):
        pass

    @dbus.service.signal(J_DBUS_INTERFACE, signature='s')
    def ObjectChooserCancelled(self, chooser_id):
        pass


class JournalActivity(JournalWindow):
    def __init__(self):
        logging.debug('STARTUP: Loading the journal')
        JournalWindow.__init__(self)

        self.set_title(_('Journal'))

        self._main_view = None
        self._secondary_view = None
        self._list_view = None
        self._detail_view = None
        self._main_toolbox = None
        self._edit_toolbox = None
        self._detail_toolbox = None
        self._volumes_toolbar = None
        self._editing_mode = False
        self._alert = Alert()

        self._error_alert = Alert()
        icon = Icon(icon_name='dialog-ok')
        self._error_alert.add_button(Gtk.ResponseType.OK, _('Ok'), icon)
        icon.show()

        self._confirmation_alert = Alert()
        icon = Icon(icon_name='dialog-cancel')
        self._confirmation_alert.add_button(Gtk.ResponseType.CANCEL, _('Stop'), icon)
        icon.show()
        icon = Icon(icon_name='dialog-ok')
        self._confirmation_alert.add_button(Gtk.ResponseType.OK, _('Continue'), icon)
        icon.show()

        self._current_alert = None
        self.setup_handlers_for_alert_actions()

        self._info_alert = None
        self._selected_entries = []
        self._bundle_installation_allowed = True

        set_mount_point('/')

        self._setup_main_view()
        self._setup_secondary_view()

        self.add_events(Gdk.EventMask.ALL_EVENTS_MASK |
                        Gdk.EventMask.VISIBILITY_NOTIFY_MASK)
        self._realized_sid = self.connect('realize', self.__realize_cb)
        self.connect('visibility-notify-event',
                     self.__visibility_notify_event_cb)
        self.connect('window-state-event', self.__window_state_event_cb)
        self.connect('key-press-event', self._key_press_event_cb)
        self.connect('focus-in-event', self._focus_in_event_cb)

        model.created.connect(self.__model_created_cb)
        model.updated.connect(self.__model_updated_cb)
        model.deleted.connect(self.__model_deleted_cb)

        self._dbus_service = JournalActivityDBusService(self)

        self.iconify()

        self._critical_space_alert = None
        self._check_available_space()

    def __volume_error_cb(self, gobject, message, severity):
        self.update_title_and_message(self._error_alert, severity,
                                      message)
        self._callback = None
        self._data = None
        self.update_alert(self._error_alert)

    def _show_alert(self, message, severity):
        self.__volume_error_cb(None, message, severity)

    def _volume_error_cb(self, gobject, message, severity):
        self.update_error_alert(severity, message, None, None)

    def __alert_response_cb(self, alert, response_id):
        self.remove_alert(alert)

    def __realize_cb(self, window):
        xid = window.get_window().get_xid()
        SugarExt.wm_set_bundle_id(xid, _BUNDLE_ID)
        activity_id = activityfactory.create_activity_id()
        SugarExt.wm_set_activity_id(xid, str(activity_id))
        self.disconnect(self._realized_sid)
        self._realized_sid = None

    def can_close(self):
        return False

    def _setup_main_view(self):
        self._main_toolbox = MainToolbox()
        self._main_view = Gtk.VBox()
        self._main_view.set_can_focus(True)

        self._list_view = ListView()
        self._list_view.connect('detail-clicked', self.__detail_clicked_cb)
        self._list_view.connect('clear-clicked', self.__clear_clicked_cb)
        self._list_view.connect('volume-error', self.__volume_error_cb)
        self._list_view.connect('title-edit-started',
                                self.__title_edit_started_cb)
        self._list_view.connect('title-edit-finished',
                                self.__title_edit_finished_cb)
        self._main_view.pack_start(self._list_view, True, True, 0)
        self._list_view.show()

        self._volumes_toolbar = VolumesToolbar()
        self._volumes_toolbar.connect('volume-changed',
                                      self.__volume_changed_cb)
        self._volumes_toolbar.connect('volume-error', self.__volume_error_cb)
        self._main_view.pack_start(self._volumes_toolbar, False, True, 0)

        self._main_toolbox.connect('query-changed', self._query_changed_cb)
        self._main_toolbox.search_entry.connect('icon-press',
                                                self.__search_icon_pressed_cb)
        self._main_toolbox.set_mount_point('/')
        #search_toolbar.set_mount_point('/')
        set_mount_point('/')

    def _setup_secondary_view(self):
        self._secondary_view = Gtk.VBox()

        self._detail_toolbox = DetailToolbox()
        self._detail_toolbox.set_mount_point('/')
        self._detail_toolbox.connect('volume-error',
                                     self.__volume_error_cb)

        self._detail_view = DetailView()
        self._detail_view.connect('go-back-clicked', self.__go_back_clicked_cb)
        self._secondary_view.pack_end(self._detail_view, True, True, 0)
        self._detail_view.show()

    def _key_press_event_cb(self, widget, event):
        if not self._main_toolbox.search_entry.has_focus():
            self._main_toolbox.search_entry.grab_focus()

        keyname = Gdk.keyval_name(event.keyval)
        if keyname == 'Escape':
            self.show_main_view()

    def __detail_clicked_cb(self, list_view, object_id):
        self._show_secondary_view(object_id)

    def __clear_clicked_cb(self, list_view):
        self._main_toolbox.clear_query()

    def __go_back_clicked_cb(self, detail_view):
        self.show_main_view()

    def _query_changed_cb(self, toolbar, query):
        self._list_view.update_with_query(query)
        self.show_main_view()

    def __search_icon_pressed_cb(self, entry, icon_pos, event):
        self._main_view.grab_focus()

    def __title_edit_started_cb(self, list_view):
        self.disconnect_by_func(self._key_press_event_cb)

    def __title_edit_finished_cb(self, list_view):
        self.connect('key-press-event', self._key_press_event_cb)

    def show_main_view(self):
        if self._editing_mode:
            self._toolbox = EditToolbox()

            # TRANS: Do not translate the "%d"
            self._toolbox.set_total_number_of_entries(self.get_total_number_of_entries())
        else:
            self._toolbox = self._main_toolbox

        self.set_toolbar_box(self._toolbox)
        self._toolbox.show()

        if self.canvas != self._main_view:
            self.set_canvas(self._main_view)
            self._main_view.show()

    def _show_secondary_view(self, object_id):
        metadata = model.get(object_id)
        try:
            self._detail_toolbox.set_metadata(metadata)
        except Exception:
            logging.exception('Exception while displaying entry:')

        self.set_toolbar_box(self._detail_toolbox)
        self._detail_toolbox.show()

        try:
            self._detail_view.props.metadata = metadata
        except Exception:
            logging.exception('Exception while displaying entry:')

        self.set_canvas(self._secondary_view)
        self._secondary_view.show()

    def show_object(self, object_id):
        metadata = model.get(object_id)
        if metadata is None:
            return False
        else:
            self._show_secondary_view(object_id)
            return True

    def __volume_changed_cb(self, volume_toolbar, mount_point):
        logging.debug('Selected volume: %r.', mount_point)
        self._main_toolbox.set_mount_point(mount_point)
        set_mount_point(mount_point)

        # Also, need to update the mount-point for Detail-View.
        self._detail_toolbox.set_mount_point(mount_point)

    def __model_created_cb(self, sender, **kwargs):
        self._check_for_bundle(kwargs['object_id'])
        self._main_toolbox.refresh_filters()
        self._check_available_space()

    def __model_updated_cb(self, sender, **kwargs):
        self._check_for_bundle(kwargs['object_id'])

        if self.canvas == self._secondary_view and \
                kwargs['object_id'] == self._detail_view.props.metadata['uid']:
            self._detail_view.refresh()

        self._check_available_space()

    def __model_deleted_cb(self, sender, **kwargs):
        if self.canvas == self._secondary_view and \
                kwargs['object_id'] == self._detail_view.props.metadata['uid']:
            self.show_main_view()

    def _focus_in_event_cb(self, window, event):
        self._list_view.update_dates()

    def _check_for_bundle(self, object_id):
        if not self._bundle_installation_allowed:
            return

        registry = bundleregistry.get_registry()

        metadata = model.get(object_id)
        if metadata.get('progress', '').isdigit():
            if int(metadata['progress']) < 100:
                return

        bundle = misc.get_bundle(metadata)
        if bundle is None:
            return

        if registry.is_installed(bundle):
            logging.debug('_check_for_bundle bundle already installed')
            return

        if metadata['mime_type'] == JournalEntryBundle.MIME_TYPE:
            # JournalEntryBundle code takes over the datastore entry and
            # transforms it into the journal entry from the bundle -- we have
            # nothing more to do.
            try:
                registry.install(bundle, metadata['uid'])
            except (ZipExtractException, RegistrationException):
                logging.exception('Could not install bundle %s',
                        bundle.get_path())
            return

        try:
            registry.install(bundle)
        except (ZipExtractException, RegistrationException):
            logging.exception('Could not install bundle %s', bundle.get_path())
            return

        metadata['bundle_id'] = bundle.get_bundle_id()
        model.write(metadata)

    def set_bundle_installation_allowed(self, allowed):
        self._bundle_installation_allowed = allowed

    def __window_state_event_cb(self, window, event):
        logging.debug('window_state_event_cb %r', self)
        if event.changed_mask & Gdk.WindowState.ICONIFIED:
            state = event.new_window_state
            visible = not state & Gdk.WindowState.ICONIFIED
            self._list_view.set_is_visible(visible)

    def __visibility_notify_event_cb(self, window, event):
        logging.debug('visibility_notify_event_cb %r', self)
        visible = event.get_state() != Gdk.VisibilityState.FULLY_OBSCURED
        self._list_view.set_is_visible(visible)

    def _check_available_space(self):
        """Check available space on device

            If the available space is below 50MB an alert will be
            shown which encourages to delete old journal entries.
        """

        if self._critical_space_alert:
            return
        stat = os.statvfs(env.get_profile_path())
        free_space = stat[statvfs.F_BSIZE] * stat[statvfs.F_BAVAIL]
        if free_space < _SPACE_TRESHOLD:
            self._critical_space_alert = ModalAlert()
            self._critical_space_alert.connect('destroy',
                                               self.__alert_closed_cb)
            self._critical_space_alert.show()

    def __alert_closed_cb(self, data):
        self.show_main_view()
        self.reveal()
        self._critical_space_alert = None

    def set_active_volume(self, mount):
        self._volumes_toolbar.set_active_volume(mount)

    def show_journal(self):
        """Become visible and show main view"""
        self.reveal()
        self.show_main_view()

    def switch_to_editing_mode(self, switch):
        # (re)-switch, only if not already.
        if (switch) and (not self._editing_mode):
            self._editing_mode = True
            self.get_list_view().disable_drag_and_copy()
            self.show_main_view()
        elif (not switch) and (self._editing_mode):
            self._editing_mode = False
            self.get_list_view().enable_drag_and_copy()
            self.show_main_view()

    def get_list_view(self):
        return self._list_view

    def setup_handlers_for_alert_actions(self):
        self._error_alert.connect('response',
                                   self.__check_for_alert_action)
        self._confirmation_alert.connect('response',
                                   self.__check_for_alert_action)

    def __check_for_alert_action(self, alert, response_id):
        self.hide_alert()
        if self._callback is not None:
            GObject.idle_add(self._callback, self._data,
                             response_id)

    def update_title_and_message(self, alert, title, message):
        alert.props.title = title
        alert.props.msg = message

    def update_alert(self, alert):
        if self._current_alert is None:
            self.add_alert(alert)
        elif self._current_alert != alert:
            self.remove_alert(self._current_alert)
            self.add_alert(alert)

        self.remove_alert(self._current_alert)
        self.add_alert(alert)
        self._current_alert = alert
        self._current_alert.show()
        show_normal_cursor()

    def hide_alert(self):
        if self._current_alert is not None:
            self._current_alert.hide()

    def update_info_alert(self, title, message):
        self.get_toolbar_box().display_running_status_in_multi_select(title, message)

    def update_error_alert(self, title, message, callback, data):
        self.update_title_and_message(self._error_alert, title,
                                       message)
        self._callback = callback
        self._data = data
        self.update_alert(self._error_alert)

    def update_confirmation_alert(self, title, message, callback,
                                  data):
        self.update_title_and_message(self._confirmation_alert, title,
                                       message)
        self._callback = callback
        self._data = data
        self.update_alert(self._confirmation_alert)

    def update_progress(self, fraction):
        self.get_toolbar_box().update_progress(fraction)

    def get_metadata_list(self, selected_state):
        metadata_list = []

        list_view_model = self.get_list_view().get_model()
        for index in range(0, len(list_view_model)):
            metadata = list_view_model.get_metadata(index)
            metadata_selected = \
                    list_view_model.get_selected_value(metadata['uid'])

            if ( (selected_state and metadata_selected) or \
                    ((not selected_state) and (not metadata_selected)) ):
                metadata_list.append(metadata)

        return metadata_list

    def get_total_number_of_entries(self):
        list_view_model = self.get_list_view().get_model()
        return len(list_view_model)

    def is_editing_mode_present(self):
        return self._editing_mode

    def get_volumes_toolbar(self):
        return self._volumes_toolbar

    def get_toolbar_box(self):
        return self._toolbox

    def get_detail_toolbox(self):
        return self._detail_toolbox


def get_journal():
    global _journal
    if _journal is None:
        _journal = JournalActivity()
        _journal.show()
    return _journal


def start():
    get_journal()


def set_mount_point(mount_point):
    global _mount_point
    _mount_point = mount_point

def get_mount_point():
    return _mount_point
