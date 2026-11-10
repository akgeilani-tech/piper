# SPDX-License-Identifier: GPL-2.0-or-later

import sys

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

WATCHER_BUS = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"


class TrayIcon:
    """Minimal KDE StatusNotifierItem used to restore a hidden Piper window."""

    def __init__(
        self,
        app_id: str,
        icon_name: str,
        title: str,
        on_activate,
        on_quit,
    ) -> None:
        self._app_id = app_id
        self._icon_name = icon_name
        self._title = title
        self._on_activate = on_activate
        self._on_quit = on_quit
        self.available = False
        self._connection = None
        self._registration_id = 0
        self._owner_id = 0
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
            self.available = True
        except GLib.Error as error:
            print(
                f"piper: could not register the status notifier item: {error}",
                file=sys.stderr,
            )
            self.destroy()

    def destroy(self) -> None:
        if self._connection is not None and self._registration_id:
            self._connection.unregister_object(self._registration_id)
            self._registration_id = 0
        if self._connection is not None and self._owner_id:
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
        if method_name in ("Activate", "ContextMenu"):
            # D-Bus method callbacks may run on a GDBus worker thread; GTK
            # must only be touched from the main loop.
            GLib.idle_add(self._on_activate)
        invocation.return_value(None)

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
            "Menu": ("o", "/NO_DBUSMENU"),
        }
        signature, value = values[property_name]
        return GLib.Variant(signature, value)
