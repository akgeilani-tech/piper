# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _

from .globalshortcuts import GlobalShortcuts
from .settings import Settings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa


class SettingsDialog(Gtk.Dialog):
    """Modal settings dialog, using the same window format as About Piper."""

    def __init__(
        self, shortcuts: GlobalShortcuts, settings: Settings, *args, **kwargs
    ) -> None:
        Gtk.Dialog.__init__(self, *args, **kwargs)
        self._shortcuts = shortcuts
        self._settings = settings
        self.set_title(_("Settings"))
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_size_request(480, -1)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(_("Settings"))
        self.set_titlebar(header)
        self.connect("delete-event", self._on_delete_event)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

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
            max_width_chars=58,
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

        content.add(Gtk.Separator())

        appearance_heading = Gtk.Label(xalign=0)
        appearance_heading.set_markup(
            "<b>{}</b>".format(GLib.markup_escape_text(_("Appearance")))
        )
        content.add(appearance_heading)

        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        color_group = None
        for label, mode in (
            (_("Dark"), "dark"),
            (_("Light"), "light"),
            (_("System"), "system"),
        ):
            if color_group is None:
                button = Gtk.RadioButton.new_with_label(None, label)
                color_group = button
            else:
                button = Gtk.RadioButton.new_with_label_from_widget(color_group, label)
            button.set_active(self._settings.color_mode == mode)
            button.connect("toggled", self._on_color_mode_toggled, mode)
            color_row.add(button)
        content.add(color_row)

        content.add(Gtk.Separator())

        startup_heading = Gtk.Label(xalign=0)
        startup_heading.set_markup(
            "<b>{}</b>".format(GLib.markup_escape_text(_("Startup")))
        )
        content.add(startup_heading)

        self._autostart_check = Gtk.CheckButton(
            label=_("Start automatically with the system")
        )
        self._autostart_check.set_active(self._settings.autostart)
        self._autostart_check.connect("toggled", self._on_autostart_toggled)
        content.add(self._autostart_check)

        self._minimized_check = Gtk.CheckButton(
            label=_("Start minimized in the system tray")
        )
        self._minimized_check.set_active(self._settings.start_minimized)
        self._minimized_check.connect("toggled", self._on_minimized_toggled)
        content.add(self._minimized_check)

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

    def _on_color_mode_toggled(self, button: Gtk.RadioButton, mode: str) -> None:
        if not button.get_active():
            return
        self._settings.set_color_mode(mode)
        self._settings.apply_color_mode()

    def _on_autostart_toggled(self, button: Gtk.CheckButton) -> None:
        self._settings.set_autostart(button.get_active())
        if self._settings.autostart != button.get_active():
            button.set_active(self._settings.autostart)

    def _on_minimized_toggled(self, button: Gtk.CheckButton) -> None:
        self._settings.set_start_minimized(button.get_active())

    def _on_shortcut_changed(self, shortcuts: GlobalShortcuts, description) -> None:
        self._update_shortcut(shortcuts, description)

    def _update_shortcut(self, shortcuts: GlobalShortcuts, description) -> None:
        if description:
            self._shortcut_label.set_text(_("Current shortcut: %s") % description)
        else:
            self._shortcut_label.set_text(_("Not configured"))

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        self._shortcuts.disconnect(self._shortcut_handler)
