# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _
from typing import Optional

from .globalshortcuts import (
    DEFAULT_DEVICE_TRIGGER,
    DEFAULT_PROFILE_TRIGGER,
    DEVICE_SHORTCUT_ID,
    PROFILE_SHORTCUT_ID,
    SESSION_HANDLE_TOKEN,
    GlobalShortcuts,
)
from .ratbagd import Ratbagd
from .settings import Settings
from .settingsdialog import SettingsDialog
from .tray import TrayIcon
from .window import Window

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa


class Application(Gtk.Application):
    """A Gtk.Application subclass to handle the application's initialization and
    integration with the GNOME stack. It implements the do_startup and
    do_activate methods and is responsible for the application's menus, icons,
    title and lifetime."""

    def __init__(self, ratbagd_api_version: int) -> None:
        """Instantiates a new Application."""
        Gtk.Application.__init__(
            self,
            application_id="org.freedesktop.Piper",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        GLib.set_application_name("Piper")
        GLib.set_prgname("org.freedesktop.Piper")
        self._required_ratbagd_version = ratbagd_api_version
        self._settings = Settings()
        self._window: Optional[Window] = None
        self._tray: Optional[TrayIcon] = None
        self._started_minimized = False

    def do_startup(self) -> None:
        """This function is called when the application is first started. All
        initialization should be done here, to prevent doing duplicate work in
        case another window is opened."""
        Gtk.Application.do_startup(self)
        self._settings.apply_color_mode()
        self._build_app_menu()
        self._ratbagd: Optional[Ratbagd] = None
        self._settings_dialog: Optional[SettingsDialog] = None
        self._profile_shortcuts = GlobalShortcuts(
            PROFILE_SHORTCUT_ID,
            _("Switch to the next profile"),
            DEFAULT_PROFILE_TRIGGER,
            SESSION_HANDLE_TOKEN,
        )
        self._device_shortcuts = GlobalShortcuts(
            DEVICE_SHORTCUT_ID,
            _("Switch to the next mouse"),
            DEFAULT_DEVICE_TRIGGER,
            "piper_device",
        )
        for shortcuts in (self._profile_shortcuts, self._device_shortcuts):
            shortcuts.connect("activated", self._on_shortcut_activated)
            shortcuts.start()

    def init_ratbagd(self) -> Ratbagd:
        if self._ratbagd is None:
            self._ratbagd = Ratbagd(self._required_ratbagd_version)
        return self._ratbagd

    def do_activate(self) -> None:
        """This function is called when the user requests a new window to be
        opened."""
        if self._window is None:
            self._window = self._create_window()
        if self._settings.start_minimized and not self._started_minimized:
            self._started_minimized = True
            self._window.hide()
            self.hold()
            self._show_tray()
        else:
            self._window.present()

    def _show_tray(self) -> None:
        if self._tray is not None:
            return
        self._tray = TrayIcon(
            "org.freedesktop.Piper",
            "org.freedesktop.Piper",
            "Piper",
            self._show_window,
            self.quit,
        )
        if not self._tray.available:
            self._tray = None
            self.release()
            self._window.present()

    def _create_window(self) -> Window:
        window = Window(self.init_ratbagd, self._settings, application=self)
        window.connect("delete-event", self._on_window_delete_event)
        window.connect("destroy", self._on_window_destroyed)
        return window

    def _on_window_delete_event(self, window: Window, event) -> bool:
        if self._tray is not None:
            window.hide()
            return True
        return False

    def _on_window_destroyed(self, window: Window) -> None:
        if self._window is window:
            self._window = None

    def _show_window(self) -> None:
        if self._window is None:
            self._window = self._create_window()
        self._window.present()

    def do_shutdown(self) -> None:
        if self._tray is not None:
            self._tray.destroy()
            self._tray = None
        Gtk.Application.do_shutdown(self)

    def _build_app_menu(self) -> None:
        # Set up the app menu
        actions = [
            ("settings", self._show_settings),
            ("about", self._about),
            ("quit", self._quit),
        ]
        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _show_settings(self, action: Gio.SimpleAction, param: None) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.present()
            return
        window = self.get_active_window()
        if window is None:
            return
        dialog = SettingsDialog(
            self._profile_shortcuts,
            self._device_shortcuts,
            self._settings,
            transient_for=window,
        )
        dialog.connect("destroy", self._on_settings_destroyed)
        self._settings_dialog = dialog
        dialog.show_all()

    def _on_settings_destroyed(self, dialog: SettingsDialog) -> None:
        self._settings_dialog = None

    def _on_shortcut_activated(
        self, shortcuts: GlobalShortcuts, shortcut_id: str
    ) -> None:
        if self._window is None:
            return
        if shortcut_id == PROFILE_SHORTCUT_ID:
            self._window.cycle_profile()
        elif shortcut_id == DEVICE_SHORTCUT_ID:
            self._window.cycle_device()

    def _about(self, action: Gio.SimpleAction, param: None) -> None:
        # Set up the about dialog.
        builder = Gtk.Builder().new_from_resource(
            "/org/freedesktop/Piper/AboutDialog.ui"
        )
        about: Optional[Gtk.AboutDialog] = builder.get_object("about_dialog")  # type: ignore
        assert about is not None
        about.add_credit_section(_("Contributors"), ["akgeilani-tech"])
        about.set_transient_for(self.get_active_window())
        about.connect("response", lambda about, param: about.destroy())
        about.show()

    def _quit(self, action: Gio.SimpleAction, param: None) -> None:
        # Quit the application.
        windows = self.get_windows()
        for window in windows:
            window.destroy()
        self.quit()
