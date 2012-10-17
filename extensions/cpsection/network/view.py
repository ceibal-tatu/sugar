# Copyright (C) 2008, OLPC
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
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GObject
from gi.repository import GConf
from gettext import gettext as _

from sugar3.graphics import style

from jarabe.controlpanel.sectionview import SectionView
from jarabe.controlpanel.inlinealert import InlineAlert


CLASS = 'Network'
ICON = 'module-network'
TITLE = _('Network')

_APPLY_TIMEOUT = 3000
EXPLICIT_REBOOT_MESSAGE = _('Please restart your computer for changes to take effect.')

gconf_client = GConf.Client.get_default()


class Network(SectionView):
    def __init__(self, model, alerts):
        SectionView.__init__(self)

        self._model = model
        self.restart_alerts = alerts
        self._jabber_sid = 0
        self._jabber_valid = True
        self._radio_valid = True
        self._jabber_change_handler = None
        self._radio_change_handler = None
        self._network_configuration_reset_handler = None

        self.set_border_width(style.DEFAULT_SPACING * 2)
        self.set_spacing(style.DEFAULT_SPACING)
        group = Gtk.SizeGroup(Gtk.SizeGroupMode.HORIZONTAL)

        self._radio_alert_box = Gtk.HBox(spacing=style.DEFAULT_SPACING)
        self._jabber_alert_box = Gtk.HBox(spacing=style.DEFAULT_SPACING)
        self._nm_connection_editor_alert_box = Gtk.HBox(spacing=style.DEFAULT_SPACING)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(scrolled)
        scrolled.show()

        workspace = Gtk.VBox()
        scrolled.add_with_viewport(workspace)
        workspace.show()

        separator_wireless = Gtk.HSeparator()
        workspace.pack_start(separator_wireless, False, True, 0)
        separator_wireless.show()

        label_wireless = Gtk.Label(label=_('Wireless'))
        label_wireless.set_alignment(0, 0)
        workspace.pack_start(label_wireless, False, True, 0)
        label_wireless.show()
        box_wireless = Gtk.VBox()
        box_wireless.set_border_width(style.DEFAULT_SPACING * 2)
        box_wireless.set_spacing(style.DEFAULT_SPACING)

        radio_info = Gtk.Label(label=_('Turn off the wireless radio to save battery'
                                 ' life'))
        radio_info.set_alignment(0, 0)
        radio_info.set_line_wrap(True)
        radio_info.show()
        box_wireless.pack_start(radio_info, False, True, 0)

        box_radio = Gtk.HBox(spacing=style.DEFAULT_SPACING)
        self._button = Gtk.CheckButton()
        self._button.set_alignment(0, 0)
        box_radio.pack_start(self._button, False, True, 0)
        self._button.show()

        label_radio = Gtk.Label(label=_('Radio'))
        label_radio.set_alignment(0, 0.5)
        box_radio.pack_start(label_radio, False, True, 0)
        label_radio.show()

        box_wireless.pack_start(box_radio, False, True, 0)
        box_radio.show()

        self._radio_alert = InlineAlert()
        self._radio_alert_box.pack_start(self._radio_alert, False, True, 0)
        box_radio.pack_end(self._radio_alert_box, False, True, 0)
        self._radio_alert_box.show()
        if 'radio' in self.restart_alerts:
            self._radio_alert.props.msg = self.restart_msg
            self._radio_alert.show()

        history_info = Gtk.Label(label=_('Discard network history if you have'
                                   ' trouble connecting to the network'))
        history_info.set_alignment(0, 0)
        history_info.set_line_wrap(True)
        history_info.show()
        box_wireless.pack_start(history_info, False, True, 0)

        box_clear_history = Gtk.HBox(spacing=style.DEFAULT_SPACING)
        self._clear_history_button = Gtk.Button()
        self._clear_history_button.set_label(_('Discard network history'))
        box_clear_history.pack_start(self._clear_history_button, False, True, 0)
        if not self._model.have_networks():
            self._clear_history_button.set_sensitive(False)
        self._clear_history_button.show()
        box_wireless.pack_start(box_clear_history, False, True, 0)
        box_clear_history.show()

        workspace.pack_start(box_wireless, False, True, 0)
        box_wireless.show()

        separator_mesh = Gtk.HSeparator()
        workspace.pack_start(separator_mesh, False, False, 0)
        separator_mesh.show()

        label_mesh = Gtk.Label(label=_('Collaboration'))
        label_mesh.set_alignment(0, 0)
        workspace.pack_start(label_mesh, False, True, 0)
        label_mesh.show()
        box_mesh = Gtk.VBox()
        box_mesh.set_border_width(style.DEFAULT_SPACING * 2)
        box_mesh.set_spacing(style.DEFAULT_SPACING)

        server_info = Gtk.Label(_("The server is the equivalent of what"
                                  " room you are in; people on the same server"
                                  " will be able to see each other, even when"
                                  " they aren't on the same network."))
        server_info.set_alignment(0, 0)
        server_info.set_line_wrap(True)
        box_mesh.pack_start(server_info, False, True, 0)
        server_info.show()

        box_server = Gtk.HBox(spacing=style.DEFAULT_SPACING)
        label_server = Gtk.Label(label=_('Server:'))
        label_server.set_alignment(1, 0.5)
        label_server.modify_fg(Gtk.StateType.NORMAL,
                               style.COLOR_SELECTION_GREY.get_gdk_color())
        box_server.pack_start(label_server, False, True, 0)
        group.add_widget(label_server)
        label_server.show()
        self._entry = Gtk.Entry()
        self._entry.set_alignment(0)
        self._entry.modify_bg(Gtk.StateType.INSENSITIVE,
                        style.COLOR_WHITE.get_gdk_color())
        self._entry.modify_base(Gtk.StateType.INSENSITIVE,
                          style.COLOR_WHITE.get_gdk_color())
        self._entry.set_size_request(int(Gdk.Screen.width() / 3), -1)
        box_server.pack_start(self._entry, False, True, 0)
        self._entry.show()
        box_mesh.pack_start(box_server, False, True, 0)
        box_server.show()

        self._jabber_alert = InlineAlert()
        label_jabber_error = Gtk.Label()
        group.add_widget(label_jabber_error)
        self._jabber_alert_box.pack_start(label_jabber_error, False, True, 0)
        label_jabber_error.show()
        self._jabber_alert_box.pack_start(self._jabber_alert, False, True, 0)
        box_mesh.pack_end(self._jabber_alert_box, False, True, 0)
        self._jabber_alert_box.show()
        if 'jabber' in self.restart_alerts:
            self._jabber_alert.props.msg = self.restart_msg
            self._jabber_alert.show()

        workspace.pack_start(box_mesh, False, True, 0)
        box_mesh.show()

        if gconf_client.get_bool('/desktop/sugar/extensions/network/show_nm_connection_editor') is True:
            box_nm_connection_editor = self.add_nm_connection_editor_launcher(workspace)

        self.setup()

    def add_nm_connection_editor_launcher(self, workspace):
        separator_nm_connection_editor = Gtk.HSeparator()
        workspace.pack_start(separator_nm_connection_editor, False, True, 0)
        separator_nm_connection_editor.show()

        label_nm_connection_editor = Gtk.Label(_('Advanced Network Settings'))
        label_nm_connection_editor.set_alignment(0, 0)
        workspace.pack_start(label_nm_connection_editor, False, True, 0)
        label_nm_connection_editor.show()

        box_nm_connection_editor = Gtk.VBox()
        box_nm_connection_editor.set_border_width(style.DEFAULT_SPACING * 2)
        box_nm_connection_editor.set_spacing(style.DEFAULT_SPACING)

        info = Gtk.Label(_("For more specific network settings, use "
                              "the NetworkManager Connection Editor."))

        info.set_alignment(0, 0)
        info.set_line_wrap(True)
        box_nm_connection_editor.pack_start(info, False, True, 0)

        self._nm_connection_editor_alert = InlineAlert()
        self._nm_connection_editor_alert.props.msg = EXPLICIT_REBOOT_MESSAGE
        self._nm_connection_editor_alert_box.pack_start(self._nm_connection_editor_alert,
                False, True, 0)
        box_nm_connection_editor.pack_end(self._nm_connection_editor_alert_box,
                False, True, 0)
        self._nm_connection_editor_alert_box.show()
        self._nm_connection_editor_alert.show()

        launch_button = Gtk.Button()
        launch_button.set_alignment(0, 0)
        launch_button.set_label(_('Launch'))
        launch_button.connect('clicked', self.__launch_button_clicked_cb)
        box_launch_button = Gtk.HBox()
        box_launch_button.set_homogeneous(False)
        box_launch_button.pack_start(launch_button, False, True, 0)
        box_launch_button.show_all()

        box_nm_connection_editor.pack_start(box_launch_button, False, True, 0)
        workspace.pack_start(box_nm_connection_editor, False, True, 0)
        box_nm_connection_editor.show_all()

    def setup(self):
        self._entry.set_text(self._model.get_jabber())
        try:
            radio_state = self._model.get_radio()
        except self._model.ReadError, detail:
            self._radio_alert.props.msg = detail
            self._radio_alert.show()
        else:
            self._button.set_active(radio_state)

        self._jabber_valid = True
        self._radio_valid = True
        self.needs_restart = False
        self._radio_change_handler = self._button.connect( \
                'toggled', self.__radio_toggled_cb)
        self._jabber_change_handler = self._entry.connect( \
                'changed', self.__jabber_changed_cb)
        self._network_configuration_reset_handler =  \
                self._clear_history_button.connect( \
                        'clicked', self.__network_configuration_reset_cb)

    def undo(self):
        self._button.disconnect(self._radio_change_handler)
        self._entry.disconnect(self._jabber_change_handler)
        self._model.undo()
        self._jabber_alert.hide()
        self._radio_alert.hide()

    def _validate(self):
        if self._jabber_valid and self._radio_valid:
            self.props.is_valid = True
        else:
            self.props.is_valid = False

    def __radio_toggled_cb(self, widget, data=None):
        radio_state = widget.get_active()
        try:
            self._model.set_radio(radio_state)
        except self._model.ReadError, detail:
            self._radio_alert.props.msg = detail
            self._radio_valid = False
        else:
            self._radio_valid = True
            if self._model.have_networks():
                self._clear_history_button.set_sensitive(True)

        self._validate()
        return False

    def __jabber_changed_cb(self, widget, data=None):
        if self._jabber_sid:
            GObject.source_remove(self._jabber_sid)
        self._jabber_sid = GObject.timeout_add(_APPLY_TIMEOUT,
                                               self.__jabber_timeout_cb,
                                               widget)

    def __jabber_timeout_cb(self, widget):
        self._jabber_sid = 0
        if widget.get_text() == self._model.get_jabber:
            return
        try:
            self._model.set_jabber(widget.get_text())
        except self._model.ReadError, detail:
            self._jabber_alert.props.msg = detail
            self._jabber_valid = False
            self._jabber_alert.show()
            self.restart_alerts.append('jabber')
        else:
            self._jabber_valid = True
            self._jabber_alert.hide()

        self._validate()
        return False

    def __network_configuration_reset_cb(self, widget):
        # FIXME: takes effect immediately, not after CP is closed with
        # confirmation button
        self._model.clear_networks()
        if not self._model.have_networks():
            self._clear_history_button.set_sensitive(False)

    def __launch_button_clicked_cb(self, launch_button):
        self._model.launch_nm_connection_editor()

