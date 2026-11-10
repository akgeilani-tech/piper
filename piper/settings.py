# SPDX-License-Identifier: GPL-2.0-or-later

import os
import sys

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa

COLOR_MODES = ("dark", "light", "system")
DEFAULT_COLOR_MODE = "system"
AUTOSTART_FILE = "org.freedesktop.Piper.desktop"
AUTOSTART_EXEC = "flatpak run org.freedesktop.Piper"


class Settings:
    """Persistent Piper settings stored in the user configuration directory."""

    def __init__(self) -> None:
        self._config_dir = os.path.join(GLib.get_user_config_dir(), "piper")
        self._path = os.path.join(self._config_dir, "settings.ini")
        self._keyfile = GLib.KeyFile()
        self._load()

    def _load(self) -> None:
        try:
            self._keyfile.load_from_file(self._path, GLib.KeyFileFlags.NONE)
        except GLib.Error:
            pass

    def _save(self) -> None:
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            self._keyfile.save_to_file(self._path)
        except (OSError, GLib.Error) as error:
            print(f"piper: could not save settings: {error}", file=sys.stderr)

    @property
    def color_mode(self) -> str:
        try:
            mode = self._keyfile.get_string("ui", "color-mode")
        except GLib.Error:
            return DEFAULT_COLOR_MODE
        return mode if mode in COLOR_MODES else DEFAULT_COLOR_MODE

    def set_color_mode(self, mode: str) -> None:
        if mode not in COLOR_MODES:
            return
        self._keyfile.set_string("ui", "color-mode", mode)
        self._save()

    @property
    def autostart(self) -> bool:
        return os.path.exists(self._autostart_path())

    def set_autostart(self, enabled: bool) -> None:
        path = self._autostart_path()
        if enabled:
            self._write_autostart(path)
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as error:
                print(f"piper: could not remove autostart: {error}", file=sys.stderr)

    @property
    def start_minimized(self) -> bool:
        try:
            return self._keyfile.get_boolean("startup", "minimized")
        except GLib.Error:
            return False

    def set_start_minimized(self, enabled: bool) -> None:
        self._keyfile.set_boolean("startup", "minimized", enabled)
        self._save()

    def apply_color_mode(self) -> None:
        """Applies the selected color mode to the GTK application."""
        mode = self.color_mode
        if mode == "dark":
            prefer_dark = True
        elif mode == "light":
            prefer_dark = False
        else:
            prefer_dark = self._read_portal_color_scheme() == 1

        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            gtk_settings.set_property("gtk-application-prefer-dark-theme", prefer_dark)

    def _read_portal_color_scheme(self) -> int:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings",
                None,
            )
            result = proxy.call_sync(
                "Read",
                GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                Gio.DBusCallFlags.NONE,
                3000,
                None,
            )
            value = result.unpack()[0]
            if isinstance(value, GLib.Variant):
                value = value.unpack()
            if isinstance(value, (tuple, list)):
                value = value[0]
            return int(value)
        except (GLib.Error, TypeError, ValueError):
            return 0

    def _autostart_path(self) -> str:
        return os.path.join(GLib.get_home_dir(), ".config", "autostart", AUTOSTART_FILE)

    def _write_autostart(self, path: str) -> None:
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Piper\n"
            f"Exec={AUTOSTART_EXEC}\n"
            "Icon=org.freedesktop.Piper\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as error:
            print(f"piper: could not write autostart: {error}", file=sys.stderr)
