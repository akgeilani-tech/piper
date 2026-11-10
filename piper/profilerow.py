# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _
from typing import Optional

import gi

from piper.ratbagd import (
    RatbagdDBusTimeoutError,
    RatbagdProfile,
    RatbagError,
)

from .util.gobject import connect_signal_with_weak_ref

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa


@Gtk.Template(resource_path="/org/freedesktop/Piper/ui/ProfileRow.ui")
class ProfileRow(Gtk.ListBoxRow):
    """A Gtk.ListBoxRow subclass containing the widgets to display a profile in
    the profile popover."""

    __gtype_name__ = "ProfileRow"

    __gsignals__ = {
        "name-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "notification": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    delete_button: Gtk.Button = Gtk.Template.Child()  # type: ignore
    edit_button: Gtk.Button = Gtk.Template.Child()  # type: ignore
    title: Gtk.Label = Gtk.Template.Child()  # type: ignore
    title_entry: Gtk.Entry = Gtk.Template.Child()  # type: ignore
    title_stack: Gtk.Stack = Gtk.Template.Child()  # type: ignore

    def __init__(
        self,
        profile: RatbagdProfile,
        display_name: Optional[str] = None,
        *args,
        **kwargs,
    ) -> None:
        Gtk.ListBoxRow.__init__(self, *args, **kwargs)
        self._profile = profile
        self._display_name = display_name
        self._editing = False
        self._cancel_editing = False
        connect_signal_with_weak_ref(
            self, self._profile, "notify::disabled", self._on_profile_notify_disabled
        )
        connect_signal_with_weak_ref(
            self, self._profile, "notify::is-active", self._update_actions
        )
        connect_signal_with_weak_ref(
            self, self._profile, "notify::name", self._on_profile_notify_name
        )

        self._update_title()
        self.show_all()
        self.title_stack.set_visible_child(self.title)
        self._update_actions()
        self.set_visible(not profile.disabled)

    def _update_title(self) -> None:
        if self._display_name is not None:
            name = self._display_name
        else:
            name = self._profile.name
        if not name:
            name = _("Profile %d") % self._profile.index
        self.title.set_text(name)

    def _update_actions(self, *args) -> None:
        try:
            capabilities = self._profile.capabilities
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error):
            capabilities = []
        self.delete_button.set_visible(RatbagdProfile.CAP_DISABLE in capabilities)
        self.delete_button.set_sensitive(not self._profile.is_active)
        if self._profile.is_active:
            self.delete_button.set_tooltip_text(
                _("Switch to another profile before removing this one")
            )
        else:
            self.delete_button.set_tooltip_text(
                _("Remove this profile from the device")
            )

    def _on_profile_notify_disabled(
        self, profile: RatbagdProfile, pspec: Optional[GObject.ParamSpec]
    ) -> None:
        self.set_visible(not profile.disabled)

    def _on_profile_notify_name(
        self, profile: RatbagdProfile, pspec: Optional[GObject.ParamSpec]
    ) -> None:
        if self._display_name is None:
            self._update_title()

    @Gtk.Template.Callback("_on_delete_button_clicked")
    def _on_delete_button_clicked(self, button: Gtk.Button) -> None:
        if self._profile.is_active:
            self.emit(
                "notification",
                _("Switch to another profile before removing this one"),
            )
            return
        try:
            self._profile.disabled = True
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
            self.emit(
                "notification",
                _("Could not remove the profile: %s") % error,
            )

    @Gtk.Template.Callback("_on_edit_button_clicked")
    def _on_edit_button_clicked(self, button: Gtk.Button) -> None:
        # ratbagd API 2 exposes Name as readwrite but has no CAP_WRITABLE_NAME,
        # so there is no capability to check here.
        if self._editing:
            return
        self._editing = True
        self._cancel_editing = False
        name = self._profile.name or (
            self._display_name or (_("Profile %d") % self._profile.index)
        )
        self.title_entry.set_text(name)
        self.title_stack.set_visible_child(self.title_entry)
        self.title_entry.grab_focus()
        self.title_entry.select_region(0, -1)

    @Gtk.Template.Callback("_on_title_entry_activate")
    def _on_title_entry_activate(self, entry: Gtk.Entry) -> None:
        self._commit_name()

    @Gtk.Template.Callback("_on_title_entry_key_press")
    def _on_title_entry_key_press(self, entry: Gtk.Entry, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self._cancel_editing = True
            self._stop_editing()
            return True
        return False

    @Gtk.Template.Callback("_on_title_entry_focus_out")
    def _on_title_entry_focus_out(
        self, entry: Gtk.Entry, event: Gdk.EventFocus
    ) -> bool:
        if self._editing and not self._cancel_editing:
            self._commit_name()
        return False

    def _commit_name(self) -> None:
        if not self._editing:
            return
        name = self.title_entry.get_text().strip()
        try:
            # Devices without writable profile names silently ignore this.
            self._profile.name = name
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
            self.emit(
                "notification",
                _("Could not rename the profile: %s") % error,
            )
        self._display_name = name
        self._stop_editing()
        self._update_title()
        self.emit("name-changed", name)

    def _stop_editing(self) -> None:
        self._editing = False
        self.title_stack.set_visible_child(self.title)

    def set_active(self) -> None:
        """Activates the profile paired with this row."""
        self._profile.set_active()

    @GObject.Property
    def name(self) -> str:
        return self.title.get_text()

    @GObject.Property
    def profile(self) -> RatbagdProfile:
        return self._profile
