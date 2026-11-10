# SPDX-License-Identifier: GPL-2.0-or-later

import sys
from gettext import gettext as _

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="NewTitle"/>
    <signal name="NewToolTip"/>
    <signal name="NewMenu"/>
  </interface>
</node>
"""

DBUSMENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
      <arg name="revision" type="u" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
    <signal name="ItemActivationRequested">
      <arg name="id" type="i"/>
      <arg name="timestamp" type="u"/>
    </signal>
  </interface>
</node>
"""

WATCHER_BUS = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
DBUSMENU_INTERFACE = "com.canonical.dbusmenu"
MENU_REVISION = 1

SHOW_ID = 1
SETTINGS_ID = 2
QUIT_ID = 3


class TrayIcon:
    """KDE StatusNotifierItem with a DBusMenu and watcher retry."""

    def __init__(
        self,
        app_id: str,
        icon_name: str,
        title: str,
        on_activate,
        on_quit,
        on_settings,
    ) -> None:
        self._app_id = app_id
        self._icon_name = icon_name
        self._title = title
        self._on_activate = on_activate
        self._on_quit = on_quit
        self._on_settings = on_settings
        self.available = False
        self._connection = None
        self._registration_id = 0
        self._menu_registration_id = 0
        self._owner_id = 0
        self._retry_id = 0
        self._retry_attempt = 0
        self._watcher_subscription = 0
        self._watcher_signal_subscription = 0
        self._name = "org.kde.StatusNotifierItem-piper-1"
        self._start()

    def _start(self) -> None:
        try:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._owner_id = Gio.bus_own_name_on_connection(
                self._connection,
                self._name,
                Gio.BusNameOwnerFlags.NONE,
                None,
                None,
            )
            node = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
            self._registration_id = self._connection.register_object(
                ITEM_PATH,
                node.interfaces[0],
                self._on_method,
                self._on_get_property,
                None,
            )
            menu_node = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML)
            self._menu_registration_id = self._connection.register_object(
                MENU_PATH,
                menu_node.interfaces[0],
                self._on_menu_method,
                self._on_menu_get_property,
                None,
            )
            self._subscribe_watcher()
            self._register_with_watcher()
        except GLib.Error as error:
            print(
                f"piper: could not create the status notifier item: {error}",
                file=sys.stderr,
            )
            self._schedule_retry()

    def _subscribe_watcher(self) -> None:
        self._watcher_subscription = self._connection.signal_subscribe(
            "org.freedesktop.DBus",
            "org.freedesktop.DBus",
            "NameOwnerChanged",
            "/org/freedesktop/DBus",
            WATCHER_BUS,
            Gio.DBusSignalFlags.NONE,
            self._on_name_owner_changed,
        )
        self._watcher_signal_subscription = self._connection.signal_subscribe(
            WATCHER_BUS,
            WATCHER_INTERFACE,
            None,
            WATCHER_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_watcher_signal,
        )

    def _on_name_owner_changed(
        self, connection, sender, path, interface, signal, parameters
    ) -> None:
        name, old_owner, new_owner = parameters.unpack()
        if name == WATCHER_BUS and new_owner:
            self._retry_attempt = 0
            GLib.idle_add(self._register_with_watcher)

    def _on_watcher_signal(
        self, connection, sender, path, interface, signal, parameters
    ) -> None:
        if signal in (
            "StatusNotifierHostRegistered",
            "StatusNotifierWatcherRegistered",
        ):
            self._retry_attempt = 0
            GLib.idle_add(self._register_with_watcher)

    def _register_with_watcher(self) -> None:
        if self._retry_id:
            GLib.Source.remove(self._retry_id)
            self._retry_id = 0
        try:
            watcher = Gio.DBusProxy.new_sync(
                self._connection,
                Gio.DBusProxyFlags.NONE,
                None,
                WATCHER_BUS,
                WATCHER_PATH,
                WATCHER_INTERFACE,
                None,
            )
            watcher.call_sync(
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._name,)),
                Gio.DBusCallFlags.NONE,
                3000,
                None,
            )
            host = watcher.get_cached_property("IsStatusNotifierHostRegistered")
            if host is not None and not host.unpack():
                self.available = False
                self._schedule_retry()
                return
            self.available = True
            self._retry_attempt = 0
        except GLib.Error as error:
            self.available = False
            print(
                f"piper: status notifier watcher unavailable: {error}",
                file=sys.stderr,
            )
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        if self._retry_id or self._connection is None:
            return
        if self._retry_attempt >= 6:
            return
        delay = min(2**self._retry_attempt, 10)
        self._retry_attempt += 1
        self._retry_id = GLib.timeout_add_seconds(delay, self._retry)

    def _retry(self) -> bool:
        self._retry_id = 0
        self._register_with_watcher()
        return False

    def destroy(self) -> None:
        if self._retry_id:
            GLib.Source.remove(self._retry_id)
            self._retry_id = 0
        if self._connection is not None:
            if self._watcher_subscription:
                self._connection.signal_unsubscribe(self._watcher_subscription)
                self._watcher_subscription = 0
            if self._watcher_signal_subscription:
                self._connection.signal_unsubscribe(self._watcher_signal_subscription)
                self._watcher_signal_subscription = 0
            if self._registration_id:
                self._connection.unregister_object(self._registration_id)
                self._registration_id = 0
            if self._menu_registration_id:
                self._connection.unregister_object(self._menu_registration_id)
                self._menu_registration_id = 0
            if self._owner_id:
                Gio.bus_unown_name(self._owner_id)
                self._owner_id = 0
        self._connection = None
        self.available = False

    def _on_method(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ) -> None:
        if method_name in ("Activate", "SecondaryActivate", "ContextMenu"):
            # D-Bus callbacks may run on a GDBus worker thread; GTK must only be
            # touched from the main loop.
            GLib.idle_add(self._on_activate)
        invocation.return_value(None)

    @staticmethod
    def _menu_item(item_id, label, children=None):
        props = {
            "enabled": GLib.Variant("b", True),
            "visible": GLib.Variant("b", True),
        }
        if label is not None:
            props["label"] = GLib.Variant("s", label)
        if children is not None:
            props["children-display"] = GLib.Variant("s", "submenu")
        child_variants = [
            GLib.Variant("(ia{sv}av)", child) for child in (children or [])
        ]
        return (item_id, props, child_variants)

    def _menu_items(self):
        return {
            SHOW_ID: self._menu_item(SHOW_ID, _("Show Piper")),
            SETTINGS_ID: self._menu_item(SETTINGS_ID, _("Settings")),
            QUIT_ID: self._menu_item(QUIT_ID, _("Quit")),
        }

    def _menu_root(self):
        items = self._menu_items()
        return self._menu_item(
            0, None, [items[SHOW_ID], items[SETTINGS_ID], items[QUIT_ID]]
        )

    def _item_by_id(self, item_id):
        if item_id == 0:
            return self._menu_root()
        return self._menu_items().get(item_id)

    def _on_menu_method(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ) -> None:
        if method_name == "GetLayout":
            parent_id, _depth, _props = parameters.unpack()
            if parent_id == 0:
                layout = self._menu_root()
            else:
                item = self._item_by_id(parent_id)
                layout = (parent_id, (item or (parent_id, {}, []))[1], [])
            invocation.return_value(
                GLib.Variant("(u(ia{sv}av))", (MENU_REVISION, layout))
            )
        elif method_name == "GetGroupProperties":
            ids, _props = parameters.unpack()
            if not ids:
                ids = [0, SHOW_ID, SETTINGS_ID, QUIT_ID]
            items = [self._item_by_id(item_id) for item_id in ids]
            values = [(item[0], item[1]) for item in items if item is not None]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (values,)))
        elif method_name == "GetProperty":
            item_id, name = parameters.unpack()
            item = self._item_by_id(item_id)
            if item is None or name not in item[1]:
                invocation.return_dbus_error(
                    "com.canonical.dbusmenu.Error", "Unknown property"
                )
                return
            invocation.return_value(GLib.Variant("(v)", (item[1][name],)))
        elif method_name == "Event":
            item_id, event_id, _data, _timestamp = parameters.unpack()
            if event_id == "clicked":
                self._activate_item(item_id)
            invocation.return_value(None)
        elif method_name == "EventGroup":
            events, _ = parameters.unpack()
            for item_id, event_id, _data, _timestamp in events:
                if event_id == "clicked":
                    self._activate_item(item_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(bu)", (False, MENU_REVISION)))
        elif method_name == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error(
                "com.canonical.dbusmenu.Error", "Unknown method"
            )

    def _activate_item(self, item_id: int) -> None:
        if item_id == SHOW_ID:
            GLib.idle_add(self._on_activate)
        elif item_id == SETTINGS_ID:
            GLib.idle_add(self._on_settings)
        elif item_id == QUIT_ID:
            GLib.idle_add(self._on_quit)

    def _on_get_property(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        property_name,
    ):
        values = {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", self._app_id),
            "Title": ("s", self._title),
            "Status": ("s", "Active"),
            "IconName": ("s", self._icon_name),
            "IconPixmap": ("a(iiay)", []),
            "OverlayIconName": ("s", ""),
            "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""),
            "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", ("", [], self._title, "")),
            "ItemIsMenu": ("b", False),
            "Menu": ("o", MENU_PATH),
        }
        signature, value = values[property_name]
        return GLib.Variant(signature, value)

    def _on_menu_get_property(
        self,
        connection,
        sender,
        object_path,
        interface_name,
        property_name,
    ):
        values = {
            "Version": ("u", 3),
            "TextDirection": ("s", "ltr"),
            "Status": ("s", "normal"),
            "IconThemePath": ("as", []),
        }
        signature, value = values[property_name]
        return GLib.Variant(signature, value)
