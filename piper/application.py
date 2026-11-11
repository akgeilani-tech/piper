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
from .ratbagd import (
    Ratbagd,
    RatbagdIncompatibleError,
    RatbagdUnavailableError,
)
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
        GLib.set_application_name("Piper by AKGeilani-tech")
        GLib.set_prgname("org.freedesktop.Piper")
        self._required_ratbagd_version = ratbagd_api_version
        self._settings = Settings()
        self._window: Optional[Window] = None
        self._tray: Optional[TrayIcon] = None
        self._started_minimized = False
        self._reconnect_id = 0
        self._reconnect_attempt = 0
        self._keepalive_id = 0

    def do_startup(self) -> None:
        """This function is called when the application is first started. All
        initialization should be done here, to prevent doing duplicate work in
        case another window is opened."""
        Gtk.Application.do_startup(self)
        self._settings.apply_color_mode()
        self._settings.watch_color_scheme()
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
        self._show_tray()
        self._keepalive_id = GLib.timeout_add_seconds(600, self._keepalive)

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
            if self._tray is not None and self._tray.available:
                self._window.hide()
                self.hold()
            else:
                self._window.present()
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
            self._open_settings,
        )

    def _create_window(self) -> Window:
        window = Window(self.init_ratbagd, self._settings, application=self)
        window.connect("delete-event", self._on_window_delete_event)
        window.connect("destroy", self._on_window_destroyed)
        window.connect("daemon-lost", self._on_daemon_lost)
        return window

    def _on_daemon_lost(self, window: Window) -> None:
        self._ratbagd = None
        self._reconnect_attempt = 0
        if self._reconnect_id:
            return
        self._reconnect_id = GLib.timeout_add_seconds(2, self._try_reconnect)

    def _keepalive(self) -> bool:
        if self._ratbagd is not None:
            self._ratbagd.ping()
        return True

    def _try_reconnect(self) -> bool:
        self._reconnect_id = 0
        try:
            ratbagd = self.init_ratbagd()
        except (RatbagdUnavailableError, RatbagdIncompatibleError, GLib.Error):
            self._reconnect_attempt += 1
            if self._reconnect_attempt < 15:
                self._reconnect_id = GLib.timeout_add_seconds(
                    min(2 + self._reconnect_attempt, 10), self._try_reconnect
                )
            return False

        old_window = self._window
        self._window = None
        if old_window is not None:
            old_window.destroy()
        self._window = self._create_window()
        self._window.present()
        # Keep the Ratbagd object alive in the application cache.
        self._ratbagd = ratbagd
        self._reconnect_attempt = 0
        return False

    def _on_window_delete_event(self, window: Window, event) -> bool:
        if self._tray is not None and self._tray.available:
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
        if self._reconnect_id:
            GLib.Source.remove(self._reconnect_id)
            self._reconnect_id = 0
        if self._keepalive_id:
            GLib.Source.remove(self._keepalive_id)
            self._keepalive_id = 0
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
        self._open_settings()

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.present()
            return
        window = self.get_active_window() or self._window
        if window is None:
            return
        if not window.get_visible():
            window.present()
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
        version = (about.get_version() or "").replace("Version:", "").strip()
        if not version:
            version = "0.9.0-akg"
        comments = (
            _(
                "Version %s (2026). The features added in this fork are the "
                "contribution of Ahmed Geilani "
                '(<a href="https://github.com/akgeilani-tech">akgeilani-tech</a>). '
                "Original Piper by the "
                '<a href="https://github.com/libratbag/piper">libratbag</a> '
                "developers."
            )
            % version
        )
        about.set_comments(comments)
        comments_label = self._find_label(about, comments)
        if comments_label is not None:
            comments_label.set_markup(comments)
            comments_label.connect("activate-link", self._on_about_link)
        about.add_credit_section(
            _("Fork maintained by"),
            [
                "Ahmed Geilani "
                '(<a href="https://github.com/akgeilani-tech">akgeilani-tech</a>)'
            ],
        )
        about.add_credit_section(
            _("Fork contributions"),
            [
                _(
                    "Version %s (2026) — Ahmed Geilani "
                    '(<a href="https://github.com/akgeilani-tech">akgeilani-tech</a>)'
                )
                % version
            ],
        )
        about.add_credit_section(
            _("Original project"),
            ['<a href="https://github.com/libratbag/piper">libratbag</a> developers'],
        )
        about.set_size_request(440, 430)
        about.set_transient_for(self.get_active_window())
        about.connect("response", lambda about, param: about.destroy())
        about.show()

    @staticmethod
    def _find_label(widget: Gtk.Widget, text: str):
        if isinstance(widget, Gtk.Label) and widget.get_text() == text:
            return widget
        try:
            children = widget.get_children()
        except AttributeError:
            return None
        for child in children:
            found = Application._find_label(child, text)
            if found is not None:
                return found
        return None

    @staticmethod
    def _on_about_link(label: Gtk.Label, uri: str) -> bool:
        try:
            Gtk.show_uri_on_window(
                label.get_toplevel(), uri, Gtk.get_current_event_time()
            )
        except GLib.Error:
            pass
        return True

    def _quit(self, action: Gio.SimpleAction, param: None) -> None:
        # Quit the application.
        windows = self.get_windows()
        for window in windows:
            window.destroy()
        self.quit()
