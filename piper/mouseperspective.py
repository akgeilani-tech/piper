# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _
from typing import List, Optional

from .buttonspage import ButtonsPage
from .devices import PointerDevice, display_name
from .profilerow import ProfileRow
from .ratbagd import (
    RatbagdDBusTimeoutError,
    RatbagdDevice,
    RatbagdProfile,
    RatbagError,
)
from .resolutionspage import ResolutionsPage
from .advancedpage import AdvancedPage
from .ledspage import LedsPage
from .settings import Settings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, GObject, Gtk, Pango  # noqa

# Devices known to expose settings in ratbagd but not persist them. Remove an
# entry once libratbag can commit to that model.
PARTIAL_SUPPORT_MODELS = {
    "usb:046d:402c",  # Logitech G602 (libratbag PR #1837, not released)
}

PARTIAL_SUPPORT_MESSAGE = _(
    "Saving is disabled: this device may have partial support in " "ratbagd/libratbag."
)


@Gtk.Template(resource_path="/org/freedesktop/Piper/ui/MousePerspective.ui")
class MousePerspective(Gtk.Overlay):
    """The perspective to configure a mouse."""

    __gtype_name__ = "MousePerspective"

    __gsignals__ = {
        "device-selected": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (GObject.TYPE_PYOBJECT,),
        ),
    }

    _titlebar: Gtk.HeaderBar = Gtk.Template.Child()  # type: ignore
    add_profile_button: Gtk.Button = Gtk.Template.Child()  # type: ignore
    button_commit: Gtk.Button = Gtk.Template.Child()  # type: ignore
    button_device: Gtk.MenuButton = Gtk.Template.Child()  # type: ignore
    button_profile: Gtk.MenuButton = Gtk.Template.Child()  # type: ignore
    label_device: Gtk.Label = Gtk.Template.Child()  # type: ignore
    label_profile: Gtk.Label = Gtk.Template.Child()  # type: ignore
    listbox_devices: Gtk.ListBox = Gtk.Template.Child()  # type: ignore
    listbox_profiles: Gtk.ListBox = Gtk.Template.Child()  # type: ignore
    no_device_label: Gtk.Label = Gtk.Template.Child()  # type: ignore
    notification_error: Gtk.Revealer = Gtk.Template.Child()  # type: ignore
    notification_error_label: Gtk.Label = Gtk.Template.Child()  # type: ignore
    stack: Gtk.Stack = Gtk.Template.Child()  # type: ignore

    def __init__(self, settings: Settings, *args, **kwargs) -> None:
        """Instantiates a new MousePerspective."""
        Gtk.Overlay.__init__(self, *args, **kwargs)
        self._settings = settings
        self._device: Optional[RatbagdDevice] = None
        self._profile: Optional[RatbagdProfile] = None
        self._connections = []
        self._notification_error_timeout_id = 0
        self._commit_check_id = 0
        self._commit_unsupported = False
        self.connect("destroy", self._on_destroy)

    @GObject.Property
    def name(self) -> str:
        """The name of this perspective."""
        return "mouse_perspective"

    @GObject.Property
    def titlebar(self) -> Gtk.Widget:
        """The titlebar to this perspective."""
        return self._titlebar

    @GObject.Property
    def can_go_back(self) -> bool:
        """The device selector replaces the old welcome screen."""
        return False

    @GObject.Property
    def can_shutdown(self) -> bool:
        if self._device is None:
            return True

        """Whether this perspective can safely shutdown."""
        return all(not profile.dirty for profile in self._device.profiles)

    @GObject.Property
    def device(self) -> Optional[RatbagdDevice]:
        return self._device

    def set_devices(
        self,
        devices: List[RatbagdDevice],
        selected: Optional[RatbagdDevice],
        incompatible: List[PointerDevice],
        status_text: str,
    ) -> None:
        """Refresh the mouse selector."""
        self.listbox_devices.foreach(Gtk.Widget.destroy)

        for device in devices:
            row = self._make_device_row(
                display_name(device), device, checked=device is selected
            )
            self.listbox_devices.insert(row, -1)

        if devices:
            for pointer in incompatible:
                name = pointer.name or f"{pointer.vendor}:{pointer.product}"
                row = self._make_device_row(
                    _("Mouse not supported: %s") % name, None, sensitive=False
                )
                self.listbox_devices.insert(row, -1)
        else:
            self.listbox_devices.insert(
                self._make_device_row(status_text, None, sensitive=False), -1
            )

        if selected is not None:
            self.label_device.set_text(display_name(selected))
        else:
            self.label_device.set_text(status_text)

        self.button_profile.set_visible(True)
        self.button_profile.set_sensitive(selected is not None)
        if selected is None:
            self.label_profile.set_text(_("Profile"))
        self.no_device_label.set_text(status_text)
        self.no_device_label.set_visible(selected is None)

    @staticmethod
    def _make_device_row(
        text: str,
        device: Optional[RatbagdDevice],
        sensitive: bool = True,
        checked: bool = False,
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.device = device
        row.set_sensitive(sensitive)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(label, True, True, 0)
        if checked:
            check = Gtk.Image.new_from_icon_name(
                "object-select-symbolic", Gtk.IconSize.BUTTON
            )
            box.pack_end(check, False, False, 0)
        row.add(box)
        row.show_all()
        return row

    def set_device(self, device: Optional[RatbagdDevice]) -> None:
        """Configure the given mouse, or clear the view when there is none."""
        self._disconnect_all()
        self._device = device
        self._profile = None
        self._cancel_commit_check()
        self._commit_unsupported = False
        self.button_commit.set_tooltip_text(_("Commit the changes to the device"))
        self._hide_notification_error()

        self.listbox_profiles.foreach(Gtk.Widget.destroy)
        self.stack.foreach(Gtk.Widget.destroy)

        if device is None:
            self.label_profile.set_text(_("Profile"))
            self.button_profile.set_sensitive(False)
            self.add_profile_button.set_sensitive(False)
            self.button_commit.set_sensitive(False)
            self.no_device_label.set_visible(True)
            return

        self.no_device_label.set_visible(False)
        self._connect(device, "resync", lambda dev: self._on_resync(dev))
        self._connect(device, "active-profile-changed", self._on_active_profile_changed)

        self._seed_profile_names(device)

        active_profile = device.active_profile
        if active_profile is None:
            self.button_profile.set_sensitive(False)
            return

        self.button_profile.set_visible(True)
        # Keep the selector usable even for devices with a single profile so
        # the active profile is visible and selectable.
        self.button_profile.set_sensitive(True)
        self._set_profile(active_profile)

        for profile in device.profiles:
            self._connect(profile, "notify::disabled", self._on_profile_notify_disabled)
            self._connect(profile, "notify::dirty", self._on_profile_notify_dirty)
            self._connect(profile, "notify::name", self._on_profile_notify_name)
            row = ProfileRow(profile, self._profile_name(profile))
            row.connect("name-changed", self._on_profile_name_changed)
            row.connect("notification", self._on_row_notification)
            self.listbox_profiles.insert(row, profile.index)

        self._on_profile_notify_disabled(active_profile, None)
        self._select_profile_row(active_profile)
        self._update_support_state()

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        self._cancel_commit_check()
        self._disconnect_all()

    def _connect(self, obj, signal: str, func) -> None:
        handler = obj.connect(signal, func)
        self._connections.append((obj, handler))

    def _disconnect_all(self) -> None:
        for obj, handler in self._connections:
            try:
                obj.disconnect(handler)
            except (TypeError, GLib.Error):
                pass
        self._connections.clear()

    def _select_profile_row(self, profile: RatbagdProfile) -> None:
        for row in self.listbox_profiles.get_children():
            if row.profile is profile:
                self.listbox_profiles.select_row(row)
                self.label_profile.set_text(row.name)
                break

    def _set_profile(self, profile: RatbagdProfile) -> None:
        if self._device is None:
            return

        self._select_profile_row(profile)

        self._profile = profile

        self.stack.foreach(Gtk.Widget.destroy)
        if profile.resolutions:
            self.stack.add_titled(
                ResolutionsPage(self._device, profile), "resolutions", _("Resolutions")
            )
        if profile.buttons:
            self.stack.add_titled(
                ButtonsPage(self._device, profile), "buttons", _("Buttons")
            )
        if profile.leds:
            self.stack.add_titled(LedsPage(self._device, profile), "leds", _("LEDs"))
        # TODO: get rid of this duplicated logic.
        are_report_rates_supported = (
            profile.report_rate != 0 and len(profile.report_rates) != 0
        )
        if (
            profile.angle_snapping != -1
            or profile.debounces
            or are_report_rates_supported
        ):
            self.stack.add_titled(
                AdvancedPage(self._device, profile), "advanced", _("Advanced")
            )

        self._on_profile_notify_dirty(profile, None)

    def _hide_notification_error(self) -> None:
        if self._notification_error_timeout_id != 0:
            GLib.Source.remove(self._notification_error_timeout_id)
            self._notification_error_timeout_id = 0
        self.notification_error.set_reveal_child(False)

    def _show_notification_error(
        self, message: Optional[str] = None, timeout: int = 5
    ) -> None:
        if self._notification_error_timeout_id:
            GLib.Source.remove(self._notification_error_timeout_id)
            self._notification_error_timeout_id = 0
        self.notification_error_label.set_text(
            message
            or _("Something went wrong. The device has been reset to a previous state.")
        )
        self.notification_error.set_reveal_child(True)
        if timeout:
            self._notification_error_timeout_id = GLib.timeout_add_seconds(
                timeout, self._on_notification_error_timeout
            )

    def _cancel_commit_check(self) -> None:
        if self._commit_check_id:
            GLib.Source.remove(self._commit_check_id)
            self._commit_check_id = 0

    def _update_support_state(self) -> None:
        if self._device is None:
            return
        model = self._device.model or ""
        key = ":".join(model.split(":")[:3])
        if key in PARTIAL_SUPPORT_MODELS:
            self._set_commit_unsupported(PARTIAL_SUPPORT_MESSAGE)
        else:
            self.button_commit.set_tooltip_text(_("Commit the changes to the device"))

    def _set_commit_unsupported(self, message: str) -> None:
        self._commit_unsupported = True
        self.button_commit.set_sensitive(False)
        self.button_commit.get_style_context().remove_class("suggested-action")
        self.button_commit.set_tooltip_text(message)
        self._show_notification_error(message, timeout=0)

    def _check_commit_result(self, device: RatbagdDevice) -> bool:
        self._commit_check_id = 0
        if device is not self._device:
            return False
        if any(profile.dirty for profile in device.profiles):
            self._set_commit_unsupported(PARTIAL_SUPPORT_MESSAGE)
        return False

    def _on_resync(self, device: RatbagdDevice) -> None:
        if device is self._device:
            self._show_notification_error()

    def show_notification(self, message: str) -> None:
        """Show a transient message in the in-app notification banner."""
        self._show_notification_error(message)

    def _on_active_profile_changed(
        self, device: RatbagdDevice, profile: RatbagdProfile
    ) -> None:
        if device is not self._device:
            return
        if profile.disabled:
            return
        self._set_profile(profile)

    def _on_profile_notify_name(
        self, profile: RatbagdProfile, pspec: Optional[GObject.ParamSpec]
    ) -> None:
        if self._device is None or profile not in self._device.profiles:
            return
        if profile is self._profile:
            self.label_profile.set_text(self._profile_name(profile))

    def _profile_name(self, profile: RatbagdProfile) -> str:
        fallback = _("Profile %d") % profile.index
        if self._device is not None:
            saved = self._settings.profile_name(
                self._device.model, self._device.name, profile.index
            )
            if saved:
                return saved
        return profile.name or fallback

    def _on_profile_name_changed(self, row: ProfileRow, name: str) -> None:
        if row.profile is self._profile:
            self.label_profile.set_text(name or (_("Profile %d") % row.profile.index))
        if self._device is None:
            return
        # G604 and other devices silently ignore Name, so persist the name in
        # Piper's settings and use it for display on the next start.
        self._settings.set_profile_name(
            self._device.model, self._device.name, row.profile.index, name
        )

    def _seed_profile_names(self, device: RatbagdDevice) -> None:
        """Keep names already provided by ratbagd in Piper's settings."""
        for profile in device.profiles:
            saved = self._settings.profile_name(
                device.model, device.name, profile.index
            )
            if saved is None and profile.name:
                self._settings.set_profile_name(
                    device.model, device.name, profile.index, profile.name
                )

    def _on_row_notification(self, row: ProfileRow, message: str) -> None:
        self._show_notification_error(message)

    def _on_notification_error_timeout(self) -> bool:
        self._hide_notification_error()
        return False

    @Gtk.Template.Callback("_on_save_button_clicked")
    def _on_save_button_clicked(self, _button: Gtk.Button) -> None:
        if self._device is None or self._commit_unsupported:
            return
        device = self._device
        try:
            device.commit()
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
            self._show_notification_error(str(error))
            self._set_commit_unsupported(PARTIAL_SUPPORT_MESSAGE)
            return
        self._cancel_commit_check()
        self._commit_check_id = GLib.timeout_add_seconds(
            4, self._check_commit_result, device
        )

    @Gtk.Template.Callback("_on_notification_error_close_clicked")
    def _on_notification_error_close_clicked(self, button: Gtk.Button) -> None:
        self._hide_notification_error()

    @Gtk.Template.Callback("_on_profile_row_activated")
    def _on_profile_row_activated(self, listbox: Gtk.ListBox, row: ProfileRow) -> None:
        row.set_active()

    @Gtk.Template.Callback("_on_device_row_activated")
    def _on_device_row_activated(
        self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow
    ) -> None:
        device = getattr(row, "device", None)
        if device is not None:
            self.emit("device-selected", device)

    @Gtk.Template.Callback("_on_add_profile_button_clicked")
    def _on_add_profile_button_clicked(self, button: Gtk.Button) -> None:
        if self._device is None:
            return
        # Enable the first disabled profile we find.
        for profile in self._device.profiles:
            if not profile.disabled:
                continue
            try:
                if RatbagdProfile.CAP_DISABLE not in profile.capabilities:
                    continue
                profile.disabled = False
            except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
                self._show_notification_error(str(error))
            break

    def _on_profile_notify_disabled(
        self, profile: RatbagdProfile, pspec: Optional[GObject.ParamSpec]
    ) -> None:
        if self._device is None or profile not in self._device.profiles:
            return

        self.add_profile_button.set_sensitive(
            any(p.disabled and self._can_disable(p) for p in self._device.profiles)
        )

    @staticmethod
    def _can_disable(profile: RatbagdProfile) -> bool:
        try:
            return RatbagdProfile.CAP_DISABLE in profile.capabilities
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error):
            return False

    def _on_profile_notify_dirty(
        self, profile: RatbagdProfile, pspec: Optional[GObject.ParamSpec]
    ) -> None:
        if self._device is None or profile not in self._device.profiles:
            return

        device_dirty = any(p.dirty for p in self._device.profiles)

        style_context = self.button_commit.get_style_context()
        if self._commit_unsupported:
            style_context.remove_class("suggested-action")
            self.button_commit.set_sensitive(False)
            self.button_commit.set_tooltip_text(PARTIAL_SUPPORT_MESSAGE)
        elif device_dirty:
            style_context.add_class("suggested-action")
            self.button_commit.set_sensitive(True)
        else:
            # There is no way to make a single profile non-dirty, so this works
            # for now. Ideally, this should however check if there are any other
            # profiles on the device that are dirty.
            style_context.remove_class("suggested-action")
            self.button_commit.set_sensitive(False)
