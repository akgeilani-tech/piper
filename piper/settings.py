# SPDX-License-Identifier: GPL-2.0-or-later

import hashlib
import os
import sys
from typing import Optional

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa

COLOR_MODES = ("dark", "light", "system")
DEFAULT_COLOR_MODE = "system"
AUTOSTART_FILE = "org.freedesktop.Piper.desktop"
BREEZE_LIGHT = "Breeze"
BREEZE_DARK = "Breeze-Dark"


class Settings:
    """Persistent Piper settings stored in the user configuration directory."""

    def __init__(self, config_dir: Optional[str] = None) -> None:
        self._config_dir = config_dir or os.path.join(
            GLib.get_user_config_dir(), "piper"
        )
        self._path = os.path.join(self._config_dir, "settings.ini")
        self._keyfile = GLib.KeyFile()
        self._color_subscription = 0
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

    @property
    def selected_device(self) -> tuple:
        """Return ``(model, name)`` of the last mouse selected by the user."""
        try:
            model = self._keyfile.get_string("devices", "model")
            name = self._keyfile.get_string("devices", "name")
        except GLib.Error:
            return ("", "")
        return (model, name)

    def set_selected_device(self, model: str, name: str) -> None:
        self._keyfile.set_string("devices", "model", model or "")
        self._keyfile.set_string("devices", "name", name or "")
        self._save()

    @staticmethod
    def _profile_name_key(model: str, name: str, index: int) -> str:
        raw = f"{model}\0{name}\0{index}".encode()
        return hashlib.sha1(raw).hexdigest()

    def profile_name(self, model: str, name: str, index: int):
        """Return the saved name for a profile, or None."""
        key = self._profile_name_key(model, name, index)
        try:
            return self._keyfile.get_string("profile-names", key)
        except GLib.Error:
            return None

    def set_profile_name(self, model: str, name: str, index: int, value: str) -> None:
        key = self._profile_name_key(model, name, index)
        if value:
            self._keyfile.set_string("profile-names", key, value)
        else:
            try:
                self._keyfile.remove_key("profile-names", key)
            except GLib.Error:
                return
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
        if gtk_settings is None:
            return

        gtk_settings.set_property("gtk-application-prefer-dark-theme", prefer_dark)

        # Breeze ignores prefer-dark; switch between its two GTK themes.
        theme = gtk_settings.get_property("gtk-theme-name") or ""
        if "Breeze" in theme:
            target = BREEZE_DARK if prefer_dark else BREEZE_LIGHT
            if self._theme_available(target):
                gtk_settings.set_property("gtk-theme-name", target)

    def watch_color_scheme(self) -> None:
        """React to system light/dark changes when the mode is System."""
        if self._color_subscription:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return
        self._color_subscription = bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Settings",
            "SettingChanged",
            "/org/freedesktop/portal/desktop",
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_color_scheme_changed,
        )

    def _on_color_scheme_changed(
        self, connection, sender, path, interface, signal, parameters
    ) -> None:
        try:
            namespace, key, _value = parameters.unpack()
        except (TypeError, ValueError):
            return
        if (
            namespace == "org.freedesktop.appearance"
            and key == "color-scheme"
            and self.color_mode == "system"
        ):
            GLib.idle_add(self.apply_color_mode)

    @staticmethod
    def _theme_available(theme: str) -> bool:
        candidates = [os.path.join(GLib.get_home_dir(), ".themes")]
        candidates += [
            os.path.join(directory, "themes")
            for directory in GLib.get_system_data_dirs()
        ]
        for base in candidates:
            if os.path.exists(os.path.join(base, theme, "gtk-3.0", "gtk.css")):
                return True
        return False

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
        if os.environ.get("FLATPAK_ID"):
            # Flatpak maps the host ~/.config/autostart inside the sandbox.
            base = os.path.join(GLib.get_home_dir(), ".config")
        else:
            base = GLib.get_user_config_dir()
        return os.path.join(base, "autostart", AUTOSTART_FILE)

    @staticmethod
    def _autostart_exec() -> str:
        flatpak_id = os.environ.get("FLATPAK_ID")
        if flatpak_id:
            return f"flatpak run {flatpak_id}"
        return "piper"

    def _write_autostart(self, path: str) -> None:
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Piper\n"
            f"Exec={self._autostart_exec()}\n"
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
