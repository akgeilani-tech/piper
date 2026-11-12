# SPDX-License-Identifier: GPL-2.0-or-later

from gettext import gettext as _
from typing import Callable, List, Optional

from .devices import (
    STATUS_NO_COMPATIBLE,
    STATUS_NO_DEVICE,
    device_key,
    incompatible_pointers,
    list_pointer_devices,
    select_device,
    signature,
    status,
    supported_devices,
)
from .errorperspective import ErrorPerspective
from .mouseperspective import MousePerspective
from .profiles import next_profile
from .ratbagd import (
    Ratbagd,
    RatbagdDBusTimeoutError,
    RatbagdDevice,
    RatbagdIncompatibleError,
    RatbagdProfile,
    RatbagdUnavailableError,
    RatbagError,
)
from .settings import Settings

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Gio, GObject  # noqa


@Gtk.Template(resource_path="/org/freedesktop/Piper/ui/Window.ui")
class Window(Gtk.ApplicationWindow):
    """A Gtk.ApplicationWindow subclass to implement the main application
    window. This window displays the different perspectives (error and mouse)
    that each present their own behavior."""

    __gtype_name__ = "Window"

    __gsignals__ = {
        "daemon-lost": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    primary_menu: Gtk.Menu = Gtk.Template.Child()  # type: ignore
    stack_perspectives: Gtk.Stack = Gtk.Template.Child()  # type: ignore
    stack_titlebar: Gtk.Stack = Gtk.Template.Child()  # type: ignore

    def __init__(
        self,
        init_ratbagd_cb: Callable[[], Ratbagd],
        settings: Settings,
        *args,
        **kwargs,
    ) -> None:
        """Instantiates a new Window.

        @param ratbag The ratbag instance to connect to, as ratbagd.Ratbag
        """
        Gtk.ApplicationWindow.__init__(self, *args, **kwargs)

        self.set_icon_name("org.freedesktop.Piper")
        self.set_title("Piper by AKGeilani-tech")

        self._settings = settings
        self._ratbag: Optional[Ratbagd] = None
        self._supported: List[RatbagdDevice] = []
        self._incompatible = []
        self._status_text = ""
        self._selected: Optional[RatbagdDevice] = None
        self._device_signature = None
        self._poll_id = 0
        self._profile_switch_pending = False
        self._profile_switch_timeout = 0
        self._profile_switch_handler = 0
        self._profile_switch_device: Optional[RatbagdDevice] = None

        self._add_perspective(ErrorPerspective(), None)
        self._mouse_perspective = MousePerspective(self._settings)
        self._mouse_perspective.connect("device-selected", self._on_device_selected)
        self._add_perspective(self._mouse_perspective, None)
        self.connect("destroy", self._on_destroy)

        try:
            ratbag = init_ratbagd_cb()
        except RatbagdUnavailableError:
            self._present_error_perspective(
                _("Connecting to ratbagd…"),
                _("Piper will retry automatically."),
            )
            GLib.idle_add(self.emit, "daemon-lost")
            return
        except RatbagdIncompatibleError as e:
            self._present_error_perspective(
                _(
                    f"Incompatible ratbagd API version (required: {e.required_version}, provided: {e.ratbagd_version})"
                ),
                _("Please update both piper and libratbag to the latest versions"),
            )
            return

        self._ratbag = ratbag
        ratbag.connect("device-added", self._on_device_added)
        ratbag.connect("device-removed", self._on_device_removed)
        ratbag.connect("daemon-disappeared", self._on_daemon_disappeared)

        self._refresh_devices(force=True)
        self._poll_id = GLib.timeout_add_seconds(2, self._poll_devices)

    def do_delete_event(self, event: Gdk.Event) -> bool:
        for perspective in self.stack_perspectives.get_children():
            if not perspective.can_shutdown:
                dialog = Gtk.MessageDialog(
                    self,
                    Gtk.DialogFlags.MODAL,
                    Gtk.MessageType.QUESTION,
                    Gtk.ButtonsType.YES_NO,
                    _("There are unapplied changes. Are you sure you want to quit?"),
                )
                response = dialog.run()
                dialog.destroy()

                if response in [Gtk.ResponseType.NO, Gtk.ResponseType.DELETE_EVENT]:
                    return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        if self._poll_id:
            GLib.Source.remove(self._poll_id)
            self._poll_id = 0
        self._release_profile_switch()

    def _on_daemon_disappeared(self, ratbag: Ratbagd) -> None:
        self._present_error_perspective(
            _("Ooops. ratbagd has disappeared"), _("Reconnecting to ratbagd…")
        )
        self.emit("daemon-lost")

    def _on_device_added(self, ratbag: Ratbagd, device: RatbagdDevice) -> None:
        self._refresh_devices(force=True)

    def _on_device_removed(self, ratbag: Ratbagd, device: RatbagdDevice) -> None:
        if device is self._selected:
            self._selected = None
        self._refresh_devices(force=True)

    def _poll_devices(self) -> bool:
        self._refresh_devices()
        return True

    def _refresh_devices(self, force: bool = False) -> None:
        if self._ratbag is None:
            return

        supported = supported_devices(self._ratbag.devices)
        pointers = list_pointer_devices()
        incompatible = incompatible_pointers(supported, pointers)
        current_signature = signature(supported, pointers)
        if not force and current_signature == self._device_signature:
            return
        self._device_signature = current_signature
        self._supported = supported
        self._incompatible = incompatible

        if self._selected not in supported:
            self._selected = None
            model, name = self._settings.selected_device
            self._selected = select_device(supported, model, name)
            if self._selected is not None:
                self._settings.set_selected_device(*device_key(self._selected))

        if supported:
            self._status_text = ""
        elif status(supported, pointers) == STATUS_NO_COMPATIBLE:
            self._status_text = _("Mouse not supported")
        elif status(supported, pointers) == STATUS_NO_DEVICE:
            self._status_text = _("Mouse not available")
        else:
            self._status_text = _("Mouse not available")

        self._update_selector()
        if self._show_selected_device():
            self._present_mouse_perspective()

    def _update_selector(self) -> None:
        self._mouse_perspective.set_devices(
            self._supported,
            self._selected,
            self._incompatible,
            self._status_text or _("Mouse not available"),
        )
        if self._selected is None:
            self._mouse_perspective.set_device(None)

    def _show_selected_device(self) -> bool:
        if self._mouse_perspective.device is self._selected:
            return True
        try:
            self._mouse_perspective.set_device(self._selected)
        except ValueError as e:
            self._present_error_perspective(_("Cannot display device SVG"), str(e))
            return False
        except GLib.Error as e:
            if e.code == Gio.DBusError.UNKNOWN_METHOD:
                self._present_error_perspective(
                    _("Newer version of ratbagd required"),
                    _("Please update to the latest available version"),
                )
            else:
                self._present_error_perspective(
                    _("Unknown exception occurred"), e.message
                )
            return False
        return True

    def _on_device_selected(self, perspective, device: RatbagdDevice) -> None:
        if device not in self._supported:
            return
        self._selected = device
        self._settings.set_selected_device(*device_key(device))
        self._update_selector()
        if self._show_selected_device():
            self._present_mouse_perspective()

    def cycle_device(self) -> None:
        """Select the next compatible mouse."""
        if not self._supported:
            return
        if self._selected in self._supported:
            index = self._supported.index(self._selected)
        else:
            index = -1
        self._on_device_selected(
            self._mouse_perspective,
            self._supported[(index + 1) % len(self._supported)],
        )

    def cycle_profile(self) -> None:
        """Switch to the next profile of the selected mouse and apply it."""
        device = self._selected
        if device is None or self._profile_switch_pending:
            return
        profile = next_profile(device.profiles)
        if profile is None:
            return

        self._profile_switch_pending = True
        try:
            profile.set_active()
            # ratbagd only applies the new active profile on Commit. Commit is
            # device-wide, so any other pending edits are saved as well.
            device.commit()
        except (RatbagError, RatbagdDBusTimeoutError, GLib.Error) as error:
            self._mouse_perspective.show_notification(str(error))
            self._release_profile_switch()
            return

        self._profile_switch_device = device
        self._profile_switch_handler = device.connect(
            "active-profile-changed", self._on_profile_switch_done
        )
        self._profile_switch_timeout = GLib.timeout_add(
            2000, self._on_profile_switch_timeout
        )

    def _on_profile_switch_done(
        self, device: RatbagdDevice, profile: RatbagdProfile
    ) -> None:
        self._release_profile_switch()

    def _on_profile_switch_timeout(self) -> bool:
        self._profile_switch_timeout = 0
        self._release_profile_switch()
        return False

    def _release_profile_switch(self) -> None:
        if self._profile_switch_handler and self._profile_switch_device is not None:
            try:
                self._profile_switch_device.disconnect(self._profile_switch_handler)
            except (TypeError, GLib.Error):
                # The device or handler may already be gone during shutdown.
                pass
        self._profile_switch_handler = 0
        self._profile_switch_device = None
        if self._profile_switch_timeout:
            GLib.Source.remove(self._profile_switch_timeout)
            self._profile_switch_timeout = 0
        self._profile_switch_pending = False

    def _add_perspective(self, perspective, ratbag: Optional[Ratbagd]) -> None:
        self.stack_perspectives.add_named(perspective, perspective.name)
        self.stack_titlebar.add_named(perspective.titlebar, perspective.name)
        if perspective.can_go_back:
            if ratbag is None:
                raise ValueError(
                    "`ratbag` must be provided if the perspective can go back"
                )
            self._perspective_add_back_button(perspective, ratbag)
        self._perspective_add_primary_menu(perspective)

    def _present_mouse_perspective(self) -> None:
        self.stack_titlebar.set_visible_child_name(self._mouse_perspective.name)
        self.stack_perspectives.set_visible_child_name(self._mouse_perspective.name)

    def _present_error_perspective(self, message: str, detail: str) -> None:
        error_perspective: ErrorPerspective = self._get_child("error_perspective")  # type: ignore
        error_perspective.set_message(message)
        error_perspective.set_detail(detail)

        self.stack_titlebar.set_visible_child_name(error_perspective.name)
        self.stack_perspectives.set_visible_child_name(error_perspective.name)

    def _get_child(self, name: str) -> Gtk.Widget:
        child = self.stack_perspectives.get_child_by_name(name)
        if child is None:
            raise ValueError(f"Child `{name}` was not found")
        return child

    def _perspective_add_back_button(self, perspective, ratbag: Ratbagd) -> None:
        button_back = Gtk.Button.new_from_icon_name(
            "go-previous-symbolic", Gtk.IconSize.BUTTON
        )
        button_back.set_visible(len(ratbag.devices) > 1)
        button_back.connect(
            "clicked",
            lambda _, ratbag: self._present_mouse_perspective(),
            ratbag,
        )
        ratbag.connect(
            "notify::devices",
            lambda ratbag, _: button_back.set_visible(len(ratbag.devices) > 1),
        )
        perspective.titlebar.add(button_back)
        # Place the button first in the titlebar.
        perspective.titlebar.child_set_property(button_back, "position", 0)

    def _perspective_add_primary_menu(self, perspective) -> None:
        hamburger = Gtk.Image.new_from_icon_name(
            "open-menu-symbolic", Gtk.IconSize.BUTTON
        )
        hamburger.set_visible(True)
        button_primary_menu = Gtk.MenuButton.new()
        button_primary_menu.add(hamburger)
        button_primary_menu.set_visible(True)
        button_primary_menu.set_menu_model(self.primary_menu)
        perspective.titlebar.pack_end(button_primary_menu)
        # Place the button last in the titlebar.
        perspective.titlebar.child_set_property(button_primary_menu, "position", 0)
