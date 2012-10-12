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
import StringIO
import time
import os

import cairo
from gi.repository import GObject
import glib
from gi.repository import Gtk
from gi.repository import Gdk
import simplejson

from sugar3.graphics import style
from sugar3.graphics.xocolor import XoColor
from sugar3.graphics.icon import EventIcon
from sugar3.util import format_size

from jarabe.journal.keepicon import KeepIcon
from jarabe.journal.palettes import ObjectPalette, BuddyPalette
from jarabe.journal import misc
from jarabe.journal import model


class Separator(Gtk.VBox):
    def __init__(self, orientation):
        Gtk.VBox.__init__(self,
                background_color=style.COLOR_PANEL_GREY.get_gdk_color())


class BuddyList(Gtk.Alignment):
    def __init__(self, buddies):
        Gtk.Alignment.__init__(self, 0, 0, 0, 0)

        hbox = Gtk.HBox()
        for buddy in buddies:
            nick_, color = buddy
            icon = EventIcon(icon_name='computer-xo',
                             xo_color=XoColor(color),
                             pixel_size=style.STANDARD_ICON_SIZE)
            icon.set_palette(BuddyPalette(buddy))
            hbox.pack_start(icon, True, True, 0)
        self.add(hbox)


class ExpandedEntry(Gtk.EventBox):
    def __init__(self):
        Gtk.EventBox.__init__(self)
        self._vbox = Gtk.VBox()
        self.add(self._vbox)

        self._metadata = None
        self._update_title_sid = None

        self.modify_bg(Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())

        # Create a header
        header = Gtk.HBox()
        self._vbox.pack_start(header, False, False, style.DEFAULT_SPACING * 2)

        # Create a two-column body
        body_box = Gtk.EventBox()
        body_box.set_border_width(style.DEFAULT_SPACING)
        body_box.modify_bg(Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())
        self._vbox.pack_start(body_box, True, True, 0)
        body = Gtk.HBox()
        body_box.add(body)

        first_column = Gtk.VBox()
        body.pack_start(first_column, False, False, style.DEFAULT_SPACING)

        second_column = Gtk.VBox()
        body.pack_start(second_column, True, True, 0)

        # Header
        self._keep_icon = self._create_keep_icon()
        header.pack_start(self._keep_icon, False, False, style.DEFAULT_SPACING)

        self._icon = None
        self._icon_box = Gtk.HBox()
        header.pack_start(self._icon_box, False, False, style.DEFAULT_SPACING)

        self._title = self._create_title()
        header.pack_start(self._title, True, True, 0)

        # TODO: create a version list popup instead of a date label
        self._date = self._create_date()
        header.pack_start(self._date, False, False, style.DEFAULT_SPACING)

        if Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL:
            header.reverse()

        # First body column
        self._preview_box = Gtk.Frame()
        first_column.pack_start(self._preview_box, False, True, 0)

        self._technical_box = Gtk.VBox()
        first_column.pack_start(self._technical_box, True, False, 0)

        # Second body column
        description_box, self._description = self._create_description()
        second_column.pack_start(description_box, True, True,
                                 style.DEFAULT_SPACING)

        tags_box, self._tags = self._create_tags()
        second_column.pack_start(tags_box, True, True,
                                 style.DEFAULT_SPACING)

        self._buddy_list = Gtk.VBox()
        second_column.pack_start(self._buddy_list, True, False, 0)

        self.show_all()

    def set_metadata(self, metadata):
        if self._metadata == metadata:
            return
        self._metadata = metadata

        self._keep_icon.set_active(int(metadata.get('keep', 0)) == 1)

        self._icon = self._create_icon()
        for child in self._icon_box.get_children():
            self._icon_box.remove(child)
            #FIXME: self._icon_box.foreach(self._icon_box.remove)
        self._icon_box.pack_start(self._icon, False, False, 0)

        self._date.set_text(misc.get_date(metadata))

        self._title.set_text(metadata.get('title', _('Untitled')))

        if self._preview_box.get_child():
            self._preview_box.remove(self._preview_box.get_child())
        self._preview_box.add(self._create_preview())

        for child in self._technical_box.get_children():
            self._technical_box.remove(child)
            #FIXME: self._technical_box.foreach(self._technical_box.remove)
        self._technical_box.pack_start(self._create_technical(),
                                       False, False, style.DEFAULT_SPACING)

        for child in self._buddy_list.get_children():
            self._buddy_list.remove(child)
            #FIXME: self._buddy_list.foreach(self._buddy_list.remove)
        self._buddy_list.pack_start(self._create_buddy_list(), False, False,
                                    style.DEFAULT_SPACING)

        # TRANS: Do not translate the """%s""".
        uploader_nick_text = self.__create_text_description(
                _('Source XO Nick :: \n%s'), metadata.get('uploader-nick', ''))

        # TRANS: Do not translate the """%s""".
        uploader_serial_text = self.__create_text_description(
                _('Source XO Serial Number :: \n%s'), metadata.get('uploader-serial', ''))

        # TRANS: Do not translate the """%s""".
        misc_info_text = self.__create_text_description(
                _('Misellaneous Information :: \n%s'), metadata.get('description', ''))

        description = uploader_nick_text + uploader_serial_text + misc_info_text
        self._description.get_buffer().set_text(description)

        tags = metadata.get('tags', '')
        self._tags.get_buffer().set_text(tags)

    def __create_text_description(self, heading, value):
        if (value == '') or (value is None):
            return ''

        return ((heading % value) + '\n\n')

    def _create_keep_icon(self):
        keep_icon = KeepIcon()
        keep_icon.connect('toggled', self._keep_icon_toggled_cb)
        return keep_icon

    def _create_icon(self):
        icon = EventIcon(file_name=misc.get_icon_name(self._metadata))
        icon.connect_after('button-release-event',
                           self._icon_button_release_event_cb)

        if misc.is_activity_bundle(self._metadata):
            xo_color = XoColor('%s,%s' % (style.COLOR_BUTTON_GREY.get_svg(),
                                          style.COLOR_TRANSPARENT.get_svg()))
        else:
            xo_color = misc.get_icon_color(self._metadata)
        icon.props.xo_color = xo_color

        icon.set_palette(ObjectPalette(self._metadata))

        return icon

    def _create_title(self):
        entry = Gtk.Entry()
        entry.connect('focus-out-event', self._title_focus_out_event_cb)

        bg_color = style.COLOR_WHITE.get_gdk_color()
        entry.modify_bg(Gtk.StateType.INSENSITIVE, bg_color)
        entry.modify_base(Gtk.StateType.INSENSITIVE, bg_color)

        return entry

    def _create_date(self):
        date = Gtk.Label()
        return date

    def _create_preview(self):
        width = style.zoom(320)
        height = style.zoom(240)

        box = Gtk.EventBox()
        box.modify_bg(Gtk.StateType.NORMAL, style.COLOR_WHITE.get_gdk_color())

        if len(self._metadata.get('preview', '')) > 4:
            if self._metadata['preview'][1:4] == 'PNG':
                preview_data = self._metadata['preview']
            else:
                # TODO: We are close to be able to drop this.
                import base64
                preview_data = base64.b64decode(
                        self._metadata['preview'])

            png_file = StringIO.StringIO(preview_data)
            try:
                # Load image and scale to dimensions
                im = Gtk.Image()
                surface = cairo.ImageSurface.create_from_png(png_file)
                png_width = surface.get_width()
                png_height = surface.get_height()

                preview_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                                     width, height)
                cr = cairo.Context(preview_surface)

                scale_w = width * 1.0 / png_width
                scale_h = height * 1.0 / png_height
                scale = min(scale_w, scale_h)

                cr.scale(scale, scale)

                cr.set_source_rgba(1, 1, 1, 0)
                cr.set_operator(cairo.OPERATOR_SOURCE)
                cr.paint()
                cr.set_source_surface(surface)
                cr.paint()

                pixbuf_bg = Gdk.pixbuf_get_from_surface(preview_surface, 0, 0,
                                                        width, height)
                im.set_from_pixbuf(pixbuf_bg)

                has_preview = True
            except Exception:
                logging.exception('Error while loading the preview')
                has_preview = False
        else:
            has_preview = False

        if has_preview:
            box.add(im)
            im.show()
        else:
            label = Gtk.Label()
            label.set_text(_('No preview'))
            label.set_size_request(width, height)
            box.add(label)
            label.show()

        box.connect_after('button-release-event',
                          self._preview_box_button_release_event_cb)
        return box

    def _create_technical(self):
        vbox = Gtk.VBox()
        vbox.props.spacing = style.DEFAULT_SPACING

        label = \
            _('Kind: %s') % (self._metadata.get('mime_type') or \
                                 _('Unknown'),) + '\n' + \
            _('Date: %s') % (self._format_date(),) + '\n' + \
            _('Size: %s') % (format_size(int(self._metadata.get(
                        'filesize',
                        model.get_file_size(self._metadata['uid'])))))

        text = Gtk.Label()
        text.set_markup('<span foreground="%s">%s</span>' % (
                style.COLOR_BUTTON_GREY.get_html(), label))
        halign = Gtk.Alignment.new(0, 0, 0, 0)
        halign.add(text)
        vbox.pack_start(halign, False, False, 0)

        return vbox

    def _format_date(self):
        if 'timestamp' in self._metadata:
            try:
                timestamp = float(self._metadata['timestamp'])
            except (ValueError, TypeError):
                logging.warning('Invalid timestamp for %r: %r',
                                self._metadata['uid'],
                                self._metadata['timestamp'])
            else:
                return time.strftime('%x', time.localtime(timestamp))
        return _('No date')

    def _create_buddy_list(self):

        vbox = Gtk.VBox()
        vbox.props.spacing = style.DEFAULT_SPACING

        text = Gtk.Label()
        text.set_markup('<span foreground="%s">%s</span>' % (
                style.COLOR_BUTTON_GREY.get_html(), _('Participants:')))
        halign = Gtk.Alignment.new(0, 0, 0, 0)
        halign.add(text)
        vbox.pack_start(halign, False, False, 0)

        if self._metadata.get('buddies'):
            buddies = simplejson.loads(self._metadata['buddies']).values()
            vbox.pack_start(BuddyList(buddies), False, False, 0)
            return vbox
        else:
            return vbox

    def _create_scrollable(self, label):
        vbox = Gtk.VBox()
        vbox.props.spacing = style.DEFAULT_SPACING

        text = Gtk.Label()
        text.set_markup('<span foreground="%s">%s</span>' % (
                style.COLOR_BUTTON_GREY.get_html(), label))

        halign = Gtk.Alignment.new(0, 0, 0, 0)
        halign.add(text)
        vbox.pack_start(halign, False, False, 0)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        text_buffer = Gtk.TextBuffer()
        text_view = Gtk.TextView()
        text_view.set_buffer(text_buffer)
        text_view.set_left_margin(style.DEFAULT_PADDING)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scrolled_window.add(text_view)
        vbox.pack_start(scrolled_window, True, True, 0)

        # text_view.text_view_widget.connect('focus-out-event',
        #                  self._description_focus_out_event_cb)

        return vbox, text_view

    def _create_description(self):
        return self._create_scrollable(_('Description:'))

    def _create_tags(self):
        return self._create_scrollable(_('Tags:'))

    def _title_notify_text_cb(self, entry, pspec):
        if not self._update_title_sid:
            self._update_title_sid = GObject.timeout_add_seconds(1,
                                                         self._update_title_cb)

    def _title_focus_out_event_cb(self, entry, event):
        self._update_entry()

    def _description_focus_out_event_cb(self, text_view, event):
        self._update_entry()

    def _tags_focus_out_event_cb(self, text_view, event):
        self._update_entry()

    def _update_entry(self, needs_update=False):
        if not model.is_editable(self._metadata):
            return

        old_title = self._metadata.get('title', None)
        new_title = self._title.get_text()
        if old_title != new_title:
            label = glib.markup_escape_text(new_title)
            self._icon.palette.props.primary_text = label
            self._metadata['title'] = new_title
            self._metadata['title_set_by_user'] = '1'
            needs_update = True

        bounds = self._tags.get_buffer().get_bounds()
        old_tags = self._metadata.get('tags', None)
        new_tags = self._tags.get_buffer().get_text(bounds[0], bounds[1],
                                                    include_hidden_chars=False)

        if old_tags != new_tags:
            self._metadata['tags'] = new_tags
            needs_update = True

        bounds = self._description.get_buffer().get_bounds()
        old_description = self._metadata.get('description', None)
        new_description = self._description.get_buffer().get_text(
            bounds[0], bounds[1], include_hidden_chars=False)
        if old_description != new_description:
            self._metadata['description'] = new_description
            needs_update = True

        if needs_update:
            from jarabe.journal.journalactivity import get_journal
            self._metadata['mountpoint'] = \
                    get_journal().get_detail_toolbox().get_mount_point()

            model.update_only_metadata_and_preview_files_and_return_file_paths(self._metadata)

        self._update_title_sid = None

    def _keep_icon_toggled_cb(self, keep_icon):
        # If it is a locally-mounted remote-share, return without doing
        # any processing.
        if model.is_current_mount_point_for_remote_share(model.DETAIL_VIEW):
            return

        if keep_icon.get_active():
            self._metadata['keep'] = 1
        else:
            self._metadata['keep'] = 0
        self._update_entry(needs_update=True)

    def _icon_button_release_event_cb(self, button, event):
        logging.debug('_icon_button_release_event_cb')
        misc.resume(self._metadata)
        return True

    def _preview_box_button_release_event_cb(self, button, event):
        logging.debug('_preview_box_button_release_event_cb')
        misc.resume(self._metadata)
        return True
