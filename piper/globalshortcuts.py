# SPDX-License-Identifier: GPL-2.0-or-later

import sys
import uuid

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
PROFILE_SHORTCUT_ID = "next-profile"
DEVICE_SHORTCUT_ID = "next-device"
DEFAULT_PROFILE_TRIGGER = "CTRL+ALT+p"
DEFAULT_DEVICE_TRIGGER = "CTRL+ALT+m"

# Upper bound, in milliseconds, for the portal method call itself. The
# request response is waited for separately, after the call returns.
PORTAL_CALL_TIMEOUT_MS = 5000


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

    def __init__(
        self,
        shortcut_id: str = PROFILE_SHORTCUT_ID,
        description: str = "Switch to the next profile",
        default_trigger: str = DEFAULT_PROFILE_TRIGGER,
        session_token: str = SESSION_HANDLE_TOKEN,
    ):
        GObject.GObject.__init__(self)
        self.shortcut_id = shortcut_id
        self._description = description
        self._default_trigger = default_trigger
        self._session_token = session_token
        self.available = False
        self._bus = None
        self._portal = None
        self._portal_version = 0
        self._session_handle = None
        self._shortcut_description = None
        self._bound = False
        self._configuring = False
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
                Gio.DBusProxyFlags.NONE,
                None,
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                GLOBAL_SHORTCUTS_INTERFACE,
                None,
            )
        except GLib.Error as error:
            self._fail(error)
            return
        version = self._portal.get_cached_property("version")
        self._portal_version = version.unpack() if version is not None else 0
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
            self._handle_request_error(error)
            return

        if shortcuts is None:
            self._set_shortcut_description(None)
            return

        existing = next((s for s in shortcuts if s[0] == self.shortcut_id), None)
        if existing is None:
            self._set_shortcut_description(None)
            return

        try:
            description = self._bind("")
        except (GLib.Error, _PortalError) as error:
            self._handle_request_error(error)
            return

        if description is None:
            # A cancelled BindShortcuts must not leave the session marked as
            # usable: the portal would reject binding it again. The shortcut
            # is not active in the new session, so do not report the old one.
            self._reset_session()
        self._set_shortcut_description(description)

    def configure(self, parent_window=""):
        """Opens the portal dialog to change the shortcut.

        If the shortcut was never bound in this run, the first Configure call
        has to create the binding, which also shows the portal dialog.
        """
        if not self.available or self._configuring:
            return
        self._configuring = True
        try:
            if self._session_handle is None:
                self._session_handle = self._create_session()
            if self._bound:
                if self._portal_version >= 2:
                    parameters = GLib.Variant(
                        "(osa{sv})", (self._session_handle, parent_window, {})
                    )
                    self._portal.call_sync(
                        "ConfigureShortcuts",
                        parameters,
                        Gio.DBusCallFlags.NONE,
                        PORTAL_CALL_TIMEOUT_MS,
                        None,
                    )
                else:
                    # Portal v1 has no ConfigureShortcuts. Closing the session
                    # lets the next BindShortcuts call be accepted.
                    self._reset_session()
                    self._session_handle = self._create_session()
                    description = self._bind(parent_window)
                    if description is None:
                        self._reset_session()
                    else:
                        self._set_shortcut_description(description)
            else:
                description = self._bind(parent_window)
                if description is None:
                    self._reset_session()
                else:
                    self._set_shortcut_description(description)
        except (GLib.Error, _PortalError) as error:
            self._handle_request_error(error)
        finally:
            self._configuring = False

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
            session.call_sync(
                "Close", None, Gio.DBusCallFlags.NONE, PORTAL_CALL_TIMEOUT_MS, None
            )
        except GLib.Error as error:
            print(
                f"piper: could not close the global shortcuts session: {error}",
                file=sys.stderr,
            )
        self._session_handle = None

    def _reset_session(self):
        """Closes the current session so a new bind attempt is allowed."""
        self.close()
        self._session_handle = None
        self._bound = False

    def _create_session(self):
        results = self._call_with_response(
            "CreateSession",
            lambda token: GLib.Variant(
                "(a{sv})",
                (
                    self._options(
                        handle_token=token,
                        session_handle_token=self._session_token,
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
                f"{sender}/{self._session_token}"
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
            self.shortcut_id,
            {
                "description": GLib.Variant("s", self._description),
                "preferred_trigger": GLib.Variant("s", self._default_trigger),
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
            timeout=120,
        )
        if results is None:
            return None
        self._bound = True
        return self._shortcut_description_from(results)

    def _call_with_response(self, method, parameters_builder, timeout=5):
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
        handler = None
        timeout_id = 0

        def on_response(proxy, sender_name, signal_name, signal_parameters):
            if signal_name != "Response":
                return
            code, results = signal_parameters.unpack()
            response["code"] = code
            response["results"] = results
            loop.quit()

        def on_timeout():
            nonlocal timeout_id
            response["timeout"] = True
            timeout_id = 0
            loop.quit()
            return False

        try:
            handler = request.connect("g-signal", on_response)
            try:
                # Bound the method call itself. Otherwise its nested main loop
                # could run forever if the portal never replies.
                self._portal.call_sync(
                    method,
                    parameters_builder(token),
                    Gio.DBusCallFlags.NONE,
                    PORTAL_CALL_TIMEOUT_MS,
                    None,
                )
            except GLib.Error:
                # A response received while the call was being cut off wins
                # over the call timeout.
                if "code" not in response:
                    raise
            # Only wait for the Response after the call returns, so the
            # timeout cannot be consumed inside call_sync's nested loop.
            if "code" not in response:
                timeout_id = GLib.timeout_add_seconds(timeout, on_timeout)
                loop.run()
        finally:
            if timeout_id:
                GLib.source_remove(timeout_id)
            if handler is not None:
                request.disconnect(handler)

        code = response.get("code")
        if code is not None:
            if code == 1:
                return None
            if code != 0:
                results = response.get("results") or {}
                error = results.get("error")
                if isinstance(error, GLib.Variant):
                    error = error.unpack()
                raise _PortalError(error or f"the portal returned response {code}")
            return response.get("results") or {}
        if response.get("timeout"):
            raise _PortalError(f"the portal request timed out after {timeout}s")
        raise _PortalError(f"the portal did not answer the {method} request")

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

    def _shortcut_description_from(self, results):
        for shortcut_id, properties in self._shortcuts_from_results(results):
            if shortcut_id != self.shortcut_id:
                continue
            return _unpack_options(properties).get("trigger_description")
        return None

    def _set_shortcut_description(self, description):
        self._shortcut_description = description
        self.emit("shortcut-changed", description)

    def _on_portal_signal(self, proxy, sender_name, signal_name, parameters):
        if signal_name == "Activated":
            unpacked = parameters.unpack()
            if unpacked[0] == self._session_handle and unpacked[1] == self.shortcut_id:
                self.emit("activated", self.shortcut_id)
        elif signal_name == "ShortcutsChanged":
            unpacked = parameters.unpack()
            if unpacked[0] != self._session_handle:
                return
            for shortcut_id, properties in unpacked[1]:
                if shortcut_id != self.shortcut_id:
                    continue
                description = _unpack_options(properties).get("trigger_description")
                self._set_shortcut_description(description)

    def _handle_request_error(self, error):
        """Logs a transient request failure and resets the session.

        Timeouts, cancellations and portal request errors must not disable the
        feature until the next restart: closing the session lets a later
        attempt start from a clean state.
        """
        print(
            f"piper: global shortcuts request failed: {error}",
            file=sys.stderr,
        )
        self._reset_session()

    def _fail(self, error):
        print(
            f"piper: global shortcuts are unavailable: {error}",
            file=sys.stderr,
        )
        self.available = False
