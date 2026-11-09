# SPDX-License-Identifier: GPL-2.0-or-later

import sys
import uuid
from gettext import gettext as _

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject  # noqa

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
GLOBAL_SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"

# A stable session token lets the portal remember the configured shortcut
# between Piper runs.
SESSION_HANDLE_TOKEN = "piper"
SHORTCUT_ID = "next-profile"
DEFAULT_TRIGGER = "CTRL+ALT+p"


class _PortalError(Exception):
    """Raised when a portal request returns a failure response."""


def _unpack_options(options):
    """Converts a dictionary of ``v`` variants into plain Python values."""
    return {
        key: value.unpack() if isinstance(value, GLib.Variant) else value
        for key, value in options.items()
    }


class GlobalShortcuts(GObject.GObject):
    """Registers and configures a global shortcut through the XDG desktop portal.

    The ``activated`` signal is emitted with the shortcut id when the portal
    reports that the shortcut was pressed. The ``shortcut-changed`` signal is
    emitted with a human readable description of the current shortcut, or
    ``None`` when no shortcut is configured.
    """

    __gsignals__ = {
        "activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "shortcut-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.available = False
        self._bus = None
        self._portal = None
        self._session_handle = None
        self._shortcut_description = None
        self._bound = False
        self._connect()

    @property
    def shortcut_description(self):
        """The current shortcut as described by the portal, or None."""
        return self._shortcut_description

    def _connect(self):
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._portal = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None,
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                GLOBAL_SHORTCUTS_INTERFACE,
                None,
            )
        except GLib.Error as error:
            self._fail(error)
            return
        self._portal.connect("g-signal", self._on_portal_signal)
        self.available = True

    def start(self):
        """Creates the portal session and re-binds an already known shortcut.

        A shortcut that was never configured is left unbound so that starting
        Piper does not surprise the user with a key-binding dialog.
        """
        if not self.available:
            return
        try:
            self._session_handle = self._create_session()
            shortcuts = self._list_shortcuts()
        except (GLib.Error, _PortalError) as error:
            self._fail(error)
            return

        if shortcuts is None:
            self._set_shortcut_description(None)
            return

        existing = next((s for s in shortcuts if s[0] == SHORTCUT_ID), None)
        if existing is None:
            self._set_shortcut_description(None)
            return

        try:
            description = self._bind("")
        except (GLib.Error, _PortalError) as error:
            self._fail(error)
            return

        if description is None:
            description = _unpack_options(existing[1]).get("trigger_description")
        self._set_shortcut_description(description)

    def configure(self, parent_window=""):
        """Opens the portal dialog to change the shortcut.

        If the shortcut was never bound in this run, the first Configure call
        has to create the binding, which also shows the portal dialog.
        """
        if not self.available:
            return
        try:
            if self._bound:
                parameters = GLib.Variant(
                    "(osa{sv})", (self._session_handle, parent_window, {})
                )
                self._portal.call_sync(
                    "ConfigureShortcuts", parameters, Gio.DBusCallFlags.NONE, -1, None
                )
            else:
                description = self._bind(parent_window)
                if description is not None:
                    self._set_shortcut_description(description)
        except (GLib.Error, _PortalError) as error:
            self._fail(error)

    def close(self):
        """Closes the portal session.

        Piper intentionally does not call this on shutdown: the portal cleans
        the session up on its own and keeping it lets the portal remember the
        configured shortcut for the next run.
        """
        if not self.available or self._session_handle is None:
            return
        try:
            session = Gio.DBusProxy.new_sync(
                self._bus,
                Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None,
                PORTAL_BUS_NAME,
                self._session_handle,
                SESSION_INTERFACE,
                None,
            )
            session.call_sync("Close", None, Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as error:
            print(
                f"piper: could not close the global shortcuts session: {error}",
                file=sys.stderr,
            )
        self._session_handle = None

    def _create_session(self):
        results = self._call_with_response(
            "CreateSession",
            lambda token: GLib.Variant(
                "(a{sv})",
                (
                    self._options(
                        handle_token=token,
                        session_handle_token=SESSION_HANDLE_TOKEN,
                    ),
                ),
            ),
        )
        if results is None:
            raise _PortalError("the global shortcuts session was cancelled")
        handle = results.get("session_handle")
        if isinstance(handle, GLib.Variant):
            handle = handle.unpack()
        if not handle:
            # Some backends (notably KDE) only return the shortcuts here. The
            # session handle is derivable from our stable session token.
            sender = self._bus.get_unique_name()
            if sender.startswith(":"):
                sender = sender[1:]
            sender = sender.replace(".", "_")
            handle = (
                "/org/freedesktop/portal/desktop/session/"
                f"{sender}/{SESSION_HANDLE_TOKEN}"
            )
        return handle

    def _list_shortcuts(self):
        results = self._call_with_response(
            "ListShortcuts",
            lambda token: GLib.Variant(
                "(oa{sv})",
                (self._session_handle, self._options(handle_token=token)),
            ),
        )
        if results is None:
            return None
        return [
            (shortcut_id, _unpack_options(properties))
            for shortcut_id, properties in self._shortcuts_from_results(results)
        ]

    def _bind(self, parent_window):
        shortcut = (
            SHORTCUT_ID,
            {
                "description": GLib.Variant("s", _("Switch to the next profile")),
                "preferred_trigger": GLib.Variant("s", DEFAULT_TRIGGER),
            },
        )
        results = self._call_with_response(
            "BindShortcuts",
            lambda token: GLib.Variant(
                "(oa(sa{sv})sa{sv})",
                (
                    self._session_handle,
                    [shortcut],
                    parent_window,
                    self._options(handle_token=token),
                ),
            ),
        )
        if results is None:
            return None
        self._bound = True
        return self._shortcut_description_from(results)

    def _call_with_response(self, method, parameters_builder):
        token = "piper_" + uuid.uuid4().hex
        request_path = self._request_path(token)
        request = Gio.DBusProxy.new_sync(
            self._bus,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None,
            PORTAL_BUS_NAME,
            request_path,
            REQUEST_INTERFACE,
            None,
        )

        response = {}
        loop = GLib.MainLoop()

        def on_response(proxy, sender_name, signal_name, signal_parameters):
            if signal_name != "Response":
                return
            code, results = signal_parameters.unpack()
            response["code"] = code
            response["results"] = results
            loop.quit()

        handler = request.connect("g-signal", on_response)
        try:
            self._portal.call_sync(
                method,
                parameters_builder(token),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            if "code" not in response:
                loop.run()
        finally:
            request.disconnect(handler)

        code = response.get("code")
        if code == 1:
            return None
        if code != 0:
            results = response.get("results") or {}
            error = results.get("error")
            if isinstance(error, GLib.Variant):
                error = error.unpack()
            raise _PortalError(error or f"the portal returned response {code}")
        return response.get("results") or {}

    def _request_path(self, token):
        sender = self._bus.get_unique_name()
        if sender.startswith(":"):
            sender = sender[1:]
        sender = sender.replace(".", "_")
        return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    @staticmethod
    def _options(**values):
        return {key: GLib.Variant("s", value) for key, value in values.items()}

    @staticmethod
    def _shortcuts_from_results(results):
        shortcuts = results.get("shortcuts")
        if isinstance(shortcuts, GLib.Variant):
            shortcuts = shortcuts.unpack()
        return shortcuts or []

    @classmethod
    def _shortcut_description_from(cls, results):
        for shortcut_id, properties in cls._shortcuts_from_results(results):
            if shortcut_id != SHORTCUT_ID:
                continue
            return _unpack_options(properties).get("trigger_description")
        return None

    def _set_shortcut_description(self, description):
        self._shortcut_description = description
        self.emit("shortcut-changed", description)

    def _on_portal_signal(self, proxy, sender_name, signal_name, parameters):
        if signal_name == "Activated":
            unpacked = parameters.unpack()
            if unpacked[0] == self._session_handle and unpacked[1] == SHORTCUT_ID:
                self.emit("activated", SHORTCUT_ID)
        elif signal_name == "ShortcutsChanged":
            unpacked = parameters.unpack()
            if unpacked[0] != self._session_handle:
                return
            for shortcut_id, properties in unpacked[1]:
                if shortcut_id != SHORTCUT_ID:
                    continue
                description = _unpack_options(properties).get("trigger_description")
                self._set_shortcut_description(description)

    def _fail(self, error):
        print(
            f"piper: global shortcuts are unavailable: {error}",
            file=sys.stderr,
        )
        self.available = False
