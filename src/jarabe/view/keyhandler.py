# Copyright (C) 2006-2007, Red Hat, Inc.
# Copyright (C) 2009 Simon Schampijer
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

import os
import subprocess
import logging

import dbus
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GConf

from gi.repository import SugarExt

from jarabe.model import sound
from jarabe.model import shell
from jarabe.model import session
from jarabe.view.tabbinghandler import TabbingHandler
from jarabe.model.shell import ShellModel
from jarabe import config
from jarabe.journal import journalactivity


_VOLUME_STEP = sound.VOLUME_STEP
_VOLUME_MAX = 100
_TABBING_MODIFIER = Gdk.ModifierType.MOD1_MASK

_actions_table = {
    'F1': 'zoom_mesh',
    'F2': 'zoom_group',
    'F3': 'zoom_home',
    'F4': 'zoom_activity',
    'F5': 'open_search',
    'F6': 'frame',
    'KP_Prior': 'accumulate_osk',
    'KP_Next': 'unaccumulate_osk',
    'XF86AudioMute': 'volume_mute',
    'F11': 'volume_down',
    'XF86AudioLowerVolume': 'volume_down',
    'F12': 'volume_up',
    'XF86AudioRaiseVolume': 'volume_up',
    '<alt>F11': 'volume_min',
    '<alt>F12': 'volume_max',
    'XF86MenuKB': 'frame',
    '<alt>Tab': 'next_window',
    '<alt><shift>Tab': 'previous_window',
    '<alt>Escape': 'close_window',
    'XF86WebCam': 'open_search',
# the following are intended for emulator users
    '<alt><shift>f': 'frame',
    '<alt><shift>q': 'quit_emulator',
    'XF86Search': 'open_search',
    '<alt><shift>o': 'open_search'
}


_instance = None


class KeyHandler(object):
    def __init__(self, frame):
        self._frame = frame
        self._key_pressed = None
        self._keycode_pressed = 0
        self._keystate_pressed = 0
        self._key_handlers_active = True

        self._key_grabber = SugarExt.KeyGrabber()
        self._key_grabber.connect('key-pressed',
                                  self._key_pressed_cb)
        self._key_grabber.connect('key-released',
                                  self._key_released_cb)

        self._tabbing_handler = TabbingHandler(self._frame, _TABBING_MODIFIER)

        for f in os.listdir(os.path.join(config.ext_path, 'globalkey')):
            if f.endswith('.py') and not f.startswith('__'):
                module_name = f[:-3]
                try:
                    logging.debug('Loading module %r', module_name)
                    module = __import__('globalkey.' + module_name, globals(),
                                        locals(), [module_name])
                    for key in module.BOUND_KEYS:
                        if key in _actions_table:
                            raise ValueError('Key %r is already bound' % key)
                        _actions_table[key] = module
                except Exception:
                    logging.exception('Exception while loading extension:')

        self._key_grabber.grab_keys(_actions_table.keys())

    def _change_volume(self, step=None, value=None):
        if step is not None:
            volume = sound.get_volume() + step
        elif value is not None:
            volume = value

        volume = min(max(0, volume), _VOLUME_MAX)

        sound.set_volume(volume)
        sound.set_muted(volume == 0)

    def handle_previous_window(self, event_time):
        self._tabbing_handler.previous_activity(event_time)

    def handle_next_window(self, event_time):
        self._tabbing_handler.next_activity(event_time)

    def handle_close_window(self, event_time):
        active_activity = shell.get_model().get_active_activity()
        if active_activity.is_journal():
            return

        active_activity.get_window().close()

    def handle_zoom_mesh(self, event_time):
        shell.get_model().set_zoom_level(ShellModel.ZOOM_MESH, event_time)

    def handle_zoom_group(self, event_time):
        shell.get_model().set_zoom_level(ShellModel.ZOOM_GROUP, event_time)

    def handle_zoom_home(self, event_time):
        shell.get_model().set_zoom_level(ShellModel.ZOOM_HOME, event_time)

    def handle_zoom_activity(self, event_time):
        shell.get_model().set_zoom_level(ShellModel.ZOOM_ACTIVITY, event_time)

    def handle_volume_max(self, event_time):
        self._change_volume(value=_VOLUME_MAX)

    def handle_volume_min(self, event_time):
        self._change_volume(value=0)

    def handle_volume_mute(self, event_time):
        if sound.get_muted() is True:
            sound.set_muted(False)
        else:
            sound.set_muted(True)

    def handle_volume_up(self, event_time):
        self._change_volume(step=_VOLUME_STEP)

    def handle_volume_down(self, event_time):
        self._change_volume(step=-_VOLUME_STEP)

    def handle_frame(self, event_time):
        self._frame.notify_key_press()

    def handle_quit_emulator(self, event_time):
        session.get_session_manager().shutdown()

    def handle_open_search(self, event_time):
        journalactivity.get_journal().show_journal()

    def handle_accumulate_osk(self, event_time):
        from jarabe.model.shell import get_model
        if get_model().get_active_activity().get_bundle_id() == 'org.laptop.AbiWordActivity':
            return

        # If we are not in ebook-mode, do not do anything.
        is_ebook_mode = False

        command = 'evtest --query /dev/input/event4 EV_SW SW_TABLET_MODE; echo $?'
        try:
            return_code = subprocess.Popen([command],
                                           stdout=subprocess.PIPE,
                                           shell=True).stdout.readlines()[0].rstrip('\n')
            if return_code == '10':
                is_ebook_mode = True
        except Exception, e:
            logging.exception(e)

        if not is_ebook_mode:
            return

        screen = Gdk.Screen.get_default()
        active_window = screen.get_active_window()

        screen_width  = screen.get_width()
        screen_height = screen.get_height()

        client = GConf.Client.get_default()
        if screen_width > screen_height:
            factor = client.get_float('/desktop/sugar/graphics/window_osk_scaling_factor')
        else:
            factor = client.get_float('/desktop/sugar/graphics/window_osk_scaling_factor_in_portrait_mode')

        active_window.resize(screen_width, screen_height * factor)

    def handle_unaccumulate_osk(self, event_time):
        screen = Gdk.Screen.get_default()
        active_window = screen.get_active_window()
        active_window.resize(screen.get_width(), screen.get_height())

    def _key_pressed_cb(self, grabber, keycode, state, event_time):
        key = grabber.get_key(keycode, state)
        logging.debug('_key_pressed_cb: %i %i %s', keycode, state, key)
        if key is not None:
            self._key_pressed = key
            self._keycode_pressed = keycode
            self._keystate_pressed = state

            action = _actions_table[key]
            if self._tabbing_handler.is_tabbing():
                # Only accept window tabbing events, everything else
                # cancels the tabbing operation.
                if not action in ['next_window', 'previous_window']:
                    self._tabbing_handler.stop(event_time)
                    return True

            if hasattr(action, 'handle_key_press'):
                action.handle_key_press(key)
            elif isinstance(action, basestring):
                if not self._key_handlers_active:
                    return

                method = getattr(self, 'handle_' + action)
                method(event_time)
            else:
                raise TypeError('Invalid action %r' % action)

            return True
        else:
            # If this is not a registered key, then cancel tabbing.
            if self._tabbing_handler.is_tabbing():
                if not grabber.is_modifier(keycode):
                    self._tabbing_handler.stop(event_time)
                return True

        return False

    def _key_released_cb(self, grabber, keycode, state, event_time):
        if not self._key_handlers_active:
            return

        logging.debug('_key_released_cb: %i %i', keycode, state)
        if self._tabbing_handler.is_tabbing():
            # We stop tabbing and switch to the new window as soon as the
            # modifier key is raised again.
            if grabber.is_modifier(keycode, mask=_TABBING_MODIFIER):
                self._tabbing_handler.stop(event_time)

            return True
        return False


def setup(frame):
    global _instance

    if _instance:
        del _instance

    _instance = KeyHandler(frame)


def set_key_handlers_active(active):
    """
    The setup(frame) is already run at sugar-session startup.
    So, we can safely assume the "_instance" is fully-grown up.
    """

    _instance._key_handlers_active = active


def get_handle_accumulate_osk_func():
    return _instance.handle_accumulate_osk

def get_handle_unaccumulate_osk_func():
    return _instance.handle_unaccumulate_osk
