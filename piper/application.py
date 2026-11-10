# SPDX-License-Identifier: GPL-2.0-or-later

import sys
from gettext import gettext as _
from typing import Optional

from .globalshortcuts import SHORTCUT_ID, GlobalShortcuts
from .profiles import next_profile
from .ratbagd import (
    Ratbagd,
    RatbagdDBusTimeoutError,
    RatbagdIncompatibleError,
    RatbagdUnavailableError,
    RatbagError,
)
from .settingsdialog import SettingsDialog
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

    def do_startup(self) -> None:
        """This function is called when the application is first started. All
        initialization should be done here, to prevent doing duplicate work in
        case another window is opened."""
        Gtk.Application.do_startup(self)
        self._build_app_menu()
        self._ratbagd: Optional[Ratbagd] = None
        self._settings_dialog: Optional[SettingsDialog] = None
        self._global_shortcuts = GlobalShortcuts()
        self._global_shortcuts.connect("activated", self._on_shortcut_activated)
        self._global_shortcuts.start()

    def init_ratbagd(self) -> Ratbagd:
        if self._ratbagd is None:
            self._ratbagd = Ratbagd(self._required_ratbagd_version)
        return self._ratbagd

    def do_activate(self) -> None:
        """This function is called when the user requests a new window to be
        opened."""
        window = Window(self.init_ratbagd, application=self)
        window.present()

    def _build_app_menu(self) -> None:
        # Set up the app menu
        actions = [
            ("settings", self._settings),
            ("about", self._about),
            ("quit", self._quit),
        ]
        for name, callback in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _settings(self, action: Gio.SimpleAction, param: None) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.present()
            return
        window = self.get_active_window()
        if window is None:
            return
        dialog = SettingsDialog(self._global_shortcuts, transient_for=window)
        dialog.connect("destroy", self._on_settings_destroyed)
        self._settings_dialog = dialog
        dialog.show_all()

    def _on_settings_destroyed(self, dialog: SettingsDialog) -> None:
        self._settings_dialog = None

    def _on_shortcut_activated(
        self, shortcuts: GlobalShortcuts, shortcut_id: str
    ) -> None:
        if shortcut_id == SHORTCUT_ID:
            self._cycle_profiles()

    def _cycle_profiles(self) -> None:
        try:
            ratbagd = self.init_ratbagd()
        except (RatbagdUnavailableError, RatbagdIncompatibleError) as error:
            print(
                f"piper: cannot switch profiles: {error}",
                file=sys.stderr,
            )
            return
        for device in ratbagd.devices:
            profile = next_profile(device.profiles)
            if profile is None:
                continue
            try:
                profile.set_active()
            except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
                print(
                    f"piper: failed to switch the profile of {device.name}: {error}",
                    file=sys.stderr,
                )

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
