# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _

from .globalshortcuts import GlobalShortcuts
from .settings import Settings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa


class SettingsDialog(Gtk.Dialog):
    """Modal settings dialog, using the same window format as About Piper."""

    _compact_css_loaded = False

    def __init__(
        self,
        profile_shortcuts: GlobalShortcuts,
        device_shortcuts: GlobalShortcuts,
        settings: Settings,
        *args,
        **kwargs,
    ) -> None:
        Gtk.Dialog.__init__(self, *args, **kwargs)
        self._settings = settings
        self._shortcut_handlers = []
        self.set_title(_("Settings"))
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_size_request(520, -1)
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

        shortcuts_heading = Gtk.Label(xalign=0)
        shortcuts_heading.set_markup(
            "<b>{}</b>".format(GLib.markup_escape_text(_("Global shortcuts")))
        )
        content.add(shortcuts_heading)

        shortcuts_description = Gtk.Label(
            label=_(
                "These shortcuts work while Piper is running, even when another "
                "window has focus."
            ),
            xalign=0,
            wrap=True,
            max_width_chars=60,
        )
        self._set_small(shortcuts_description)
        content.add(shortcuts_description)

        self._add_shortcut_section(
            content,
            _("Profile shortcut"),
            _("Switch to the next profile of the selected mouse."),
            profile_shortcuts,
        )
        self._add_shortcut_section(
            content,
            _("Mouse shortcut"),
            _("Switch to the next compatible mouse."),
            device_shortcuts,
        )

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

        self.connect("destroy", self._on_destroy)

    @staticmethod
    def _set_small(label: Gtk.Label) -> None:
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_scale_new(0.9))
        label.set_attributes(attributes)
        label.set_justify(Gtk.Justification.FILL)

    @classmethod
    def _make_compact(cls, button: Gtk.Button) -> None:
        if not cls._compact_css_loaded:
            provider = Gtk.CssProvider()
            provider.load_from_data(
                b"button.piper-compact { padding: 2px 10px; min-height: 0; }"
            )
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            cls._compact_css_loaded = True
        button.get_style_context().add_class("piper-compact")

    def _add_shortcut_section(
        self,
        content: Gtk.Box,
        title: str,
        description: str,
        shortcuts: GlobalShortcuts,
    ) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        title_label = Gtk.Label(xalign=0)
        title_label.set_markup(f"<b>{GLib.markup_escape_text(title)}:</b>")
        row.pack_start(title_label, False, False, 0)

        help_icon = Gtk.Image.new_from_icon_name(
            "help-about-symbolic", Gtk.IconSize.BUTTON
        )
        help_icon.set_tooltip_text(description)
        help_icon.set_valign(Gtk.Align.CENTER)
        row.pack_start(help_icon, False, False, 0)

        button = Gtk.Button(label=_("Configure shortcut…"))
        button.set_halign(Gtk.Align.START)
        button.set_valign(Gtk.Align.CENTER)
        self._make_compact(button)
        button.connect("clicked", self._on_configure_clicked, shortcuts)
        row.pack_start(button, False, False, 0)

        shortcut_label = Gtk.Label(xalign=0)
        shortcut_label.set_ellipsize(Pango.EllipsizeMode.END)
        shortcut_label.set_hexpand(True)
        row.pack_start(shortcut_label, True, True, 0)
        content.add(row)

        if not shortcuts.available:
            shortcut_label.set_text(
                _("Global shortcuts are not available on this system.")
            )
            button.set_sensitive(False)
        else:
            self._update_shortcut(
                shortcuts, shortcuts.shortcut_description, shortcut_label
            )
            handler = shortcuts.connect(
                "shortcut-changed",
                lambda source, desc, label=shortcut_label: self._update_shortcut(
                    source, desc, label
                ),
            )
            self._shortcut_handlers.append((shortcuts, handler))

    def _on_delete_event(self, widget: Gtk.Widget, event) -> bool:
        self.destroy()
        return True

    def _on_configure_clicked(
        self, button: Gtk.Button, shortcuts: GlobalShortcuts
    ) -> None:
        button.set_sensitive(False)
        try:
            shortcuts.configure("")
        finally:
            button.set_sensitive(shortcuts.available)

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

    def _update_shortcut(
        self, shortcuts: GlobalShortcuts, description, label: Gtk.Label
    ) -> None:
        if description:
            label.set_text(_("Current shortcut: %s") % description)
        else:
            label.set_text(_("Not configured"))

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        for shortcuts, handler in self._shortcut_handlers:
            shortcuts.disconnect(handler)
        self._shortcut_handlers.clear()
