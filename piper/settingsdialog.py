# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _

from .globalshortcuts import GlobalShortcuts

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa


class SettingsDialog(Gtk.Dialog):
    """Modal settings dialog, using the same window format as About Piper."""

    def __init__(self, shortcuts: GlobalShortcuts, *args, **kwargs) -> None:
        Gtk.Dialog.__init__(self, *args, **kwargs)
        self._shortcuts = shortcuts
        self.set_title(_("Settings"))
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_size_request(380, -1)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("")
        self.set_titlebar(header)
        self.connect("delete-event", self._on_delete_event)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        title = Gtk.Label(xalign=0.5)
        title.set_markup("<b>{}</b>".format(GLib.markup_escape_text(_("Settings"))))
        content.add(title)

        heading = Gtk.Label(xalign=0)
        heading.set_markup(
            "<b>{}</b>".format(GLib.markup_escape_text(_("Global shortcut")))
        )
        content.add(heading)

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
        content.add(description)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._configure_button = Gtk.Button(label=_("Configure shortcut…"))
        self._configure_button.connect("clicked", self._on_configure_clicked)
        row.pack_start(self._configure_button, False, False, 0)
        self._shortcut_label = Gtk.Label(xalign=1)
        self._shortcut_label.set_halign(Gtk.Align.END)
        row.pack_end(self._shortcut_label, False, False, 0)
        content.add(row)

        if not shortcuts.available:
            unavailable = Gtk.Label(
                label=_("Global shortcuts are not available on this system."),
                xalign=0,
                wrap=True,
            )
            content.add(unavailable)
            self._configure_button.set_sensitive(False)

        self._update_shortcut(self._shortcuts, self._shortcuts.shortcut_description)
        self._shortcut_handler = self._shortcuts.connect(
            "shortcut-changed", self._on_shortcut_changed
        )
        self.connect("destroy", self._on_destroy)

    def _on_delete_event(self, widget: Gtk.Widget, event) -> bool:
        self.destroy()
        return True

    def _on_configure_clicked(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        try:
            self._shortcuts.configure("")
        finally:
            button.set_sensitive(self._shortcuts.available)

    def _on_shortcut_changed(self, shortcuts: GlobalShortcuts, description) -> None:
        self._update_shortcut(shortcuts, description)

    def _update_shortcut(self, shortcuts: GlobalShortcuts, description) -> None:
        if description:
            self._shortcut_label.set_text(_("Current shortcut: %s") % description)
        else:
            self._shortcut_label.set_text(_("Not configured"))

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        self._shortcuts.disconnect(self._shortcut_handler)
