# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _

from .globalshortcuts import GlobalShortcuts

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa

_CSS = b"""
.piper-settings-panel {
    background-color: @theme_bg_color;
    border-radius: 8px;
    padding: 18px;
}
"""


class SettingsPanel(Gtk.Box):
    """Modal settings panel shown over the main window content.

    It is intentionally not a toplevel window: KWin draws a title bar on every
    toplevel in this setup and ignores set_decorated(False), so an in-window
    overlay is the only way to get a borderless, focused settings UI.
    """

    def __init__(self, shortcuts: GlobalShortcuts, on_close, *args, **kwargs) -> None:
        Gtk.Box.__init__(
            self, *args, orientation=Gtk.Orientation.VERTICAL, spacing=8, **kwargs
        )
        self._shortcuts = shortcuts
        self._on_close = on_close
        self.set_can_focus(True)
        self.set_size_request(380, -1)

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        self._css_provider = provider
        context = self.get_style_context()
        context.add_class("piper-settings-panel")
        context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        title = Gtk.Label(xalign=0.5)
        title.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Settings"))))
        self.add(title)

        heading = Gtk.Label(xalign=0)
        heading.set_markup(
            "<b>{}</b>".format(GLib.markup_escape_text(_("Global shortcut")))
        )
        self.add(heading)

        description = Gtk.Label(
            label=_(
                "Switch to the next profile on all connected mice. Works while "
                "Piper is running, even when another window has focus."
            ),
            xalign=0,
            wrap=True,
            max_width_chars=48,
        )
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_scale_new(0.9))
        description.set_attributes(attributes)
        description.set_justify(Gtk.Justification.FILL)
        self.add(description)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._configure_button = Gtk.Button(label=_("Configure shortcut…"))
        self._configure_button.connect("clicked", self._on_configure_clicked)
        row.pack_start(self._configure_button, False, False, 0)
        self._shortcut_label = Gtk.Label(xalign=1)
        self._shortcut_label.set_halign(Gtk.Align.END)
        row.pack_end(self._shortcut_label, False, False, 0)
        self.add(row)

        if not shortcuts.available:
            unavailable = Gtk.Label(
                label=_("Global shortcuts are not available on this system."),
                xalign=0,
                wrap=True,
            )
            self.add(unavailable)
            self._configure_button.set_sensitive(False)

        close_button = Gtk.Button(label=_("Close"))
        close_button.connect("clicked", self._on_close_clicked)
        self.add(close_button)

        self._update_shortcut(self._shortcuts, self._shortcuts.shortcut_description)
        self._shortcut_handler = self._shortcuts.connect(
            "shortcut-changed", self._on_shortcut_changed
        )
        self.connect("destroy", self._on_destroy)

    def _on_configure_clicked(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        try:
            self._shortcuts.configure("")
        finally:
            button.set_sensitive(self._shortcuts.available)

    def _on_close_clicked(self, button: Gtk.Button) -> None:
        self._on_close()

    def _on_shortcut_changed(self, shortcuts: GlobalShortcuts, description) -> None:
        self._update_shortcut(shortcuts, description)

    def _update_shortcut(self, shortcuts: GlobalShortcuts, description) -> None:
        if description:
            self._shortcut_label.set_text(_("Current shortcut: %s") % description)
        else:
            self._shortcut_label.set_text(_("Not configured"))

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        self._shortcuts.disconnect(self._shortcut_handler)
