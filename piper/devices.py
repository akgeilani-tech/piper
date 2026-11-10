# SPDX-License-Identifier: GPL-2.0-or-later

"""Helpers to discover physical pointer devices and match them to ratbagd.

ratbagd only exposes devices it supports, so unsupported mice are invisible to
it.  The Linux input sysfs tree is readable inside the Flatpak sandbox and
lists every pointer device, which lets Piper warn about unsupported hardware.
"""

import ctypes
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

SYSFS_INPUT = "/sys/class/input"

STATUS_AVAILABLE = "available"
STATUS_NO_COMPATIBLE = "no-compatible"
STATUS_NO_DEVICE = "no-device"

_MODEL_RE = re.compile(r"usb:([0-9a-fA-F]{4}):([0-9a-fA-F]{4})")
_POINTER_REL_BITS = (0, 1)  # REL_X, REL_Y
_BTN_LEFT = 0x110


@dataclass(frozen=True)
class PointerDevice:
    """A physical pointer device found in the input sysfs tree."""

    name: str
    vendor: str
    product: str
    node: str

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.name, self.vendor, self.product)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _word_bits() -> int:
    return ctypes.sizeof(ctypes.c_ulong) * 8


def bitmap_has(bitmap: str, bit: int) -> bool:
    """Return whether ``bit`` is set in a sysfs input capability bitmap.

    The kernel prints the bitmap as space separated hexadecimal words, most
    significant word first, using the native ``unsigned long`` width.
    """
    words = bitmap.split()
    if not words:
        return False
    word_bits = _word_bits()
    index, offset = divmod(bit, word_bits)
    if index >= len(words):
        return False
    try:
        word = int(words[-1 - index], 16)
    except ValueError:
        return False
    return bool(word & (1 << offset))


def _is_pointer(device_dir: str) -> bool:
    rel = _read(os.path.join(device_dir, "capabilities", "rel"))
    key = _read(os.path.join(device_dir, "capabilities", "key"))
    return all(bitmap_has(rel, bit) for bit in _POINTER_REL_BITS) and bitmap_has(
        key, _BTN_LEFT
    )


def _looks_like_keyboard(name: str) -> bool:
    # Gaming keyboards often expose a pointer interface for their media wheel.
    # It has REL_X/REL_Y and BTN_LEFT, but it is not a mouse.
    lowered = name.lower()
    return "keyboard" in lowered or lowered.endswith(" kbd")


def list_pointer_devices(root: str = SYSFS_INPUT) -> List[PointerDevice]:
    """List pointer devices (mice/trackballs) from the input sysfs tree."""
    devices = []
    seen = set()
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return devices

    for entry in entries:
        if not entry.startswith("event"):
            continue
        device_dir = os.path.join(root, entry, "device")
        try:
            identity = os.path.realpath(device_dir)
        except OSError:
            continue
        if identity in seen:
            continue
        if not _is_pointer(device_dir):
            continue
        vendor = _read(os.path.join(device_dir, "id", "vendor")).lower()
        product = _read(os.path.join(device_dir, "id", "product")).lower()
        if not vendor or not product or vendor == "0000" or product == "0000":
            continue
        name = _read(os.path.join(device_dir, "name"))
        if _looks_like_keyboard(name):
            continue
        seen.add(identity)
        devices.append(
            PointerDevice(name=name, vendor=vendor, product=product, node=entry)
        )
    return devices


def model_ids(model: Optional[str]) -> Optional[Tuple[str, str]]:
    """Extract the USB vendor/product pair from a ratbagd ``Model`` string."""
    if not model:
        return None
    match = _MODEL_RE.search(model)
    if match is None:
        return None
    return (match.group(1).lower(), match.group(2).lower())


def _device_model_ids(device) -> Optional[Tuple[str, str]]:
    try:
        return model_ids(device.model)
    except (AttributeError, TypeError):
        return None


def _is_mouse(device) -> bool:
    try:
        return int(device.device_type) == 2
    except (AttributeError, TypeError, ValueError):
        return False


def supported_devices(devices: Iterable) -> List:
    """Return only the ratbagd devices that represent mice."""
    return [device for device in devices if _is_mouse(device)]


def incompatible_pointers(
    devices: Iterable, pointers: Iterable[PointerDevice]
) -> List[PointerDevice]:
    """Return pointer devices that ratbagd does not expose as a mouse."""
    known = {
        ids
        for ids in (_device_model_ids(device) for device in devices)
        if ids is not None
    }
    known_names = {
        (getattr(device, "name", "") or "").strip().lower() for device in devices
    }
    result = []
    seen = set()
    for pointer in pointers:
        if (pointer.vendor, pointer.product) in known:
            continue
        if pointer.name.strip().lower() in known_names:
            continue
        if pointer.key in seen:
            continue
        seen.add(pointer.key)
        result.append(pointer)
    return result


def status(devices: Iterable, pointers: Iterable[PointerDevice]) -> str:
    """Return the selector status for the current device set."""
    if any(True for _ in devices):
        return STATUS_AVAILABLE
    if any(True for _ in pointers):
        return STATUS_NO_COMPATIBLE
    return STATUS_NO_DEVICE


def display_name(device) -> str:
    """Human readable name for a ratbagd device."""
    try:
        name = (device.name or "").strip()
    except AttributeError:
        name = ""
    if name:
        return name
    model = getattr(device, "model", "") or ""
    return model.strip() or "Mouse"


def device_key(device) -> Tuple[str, str]:
    """Stable enough identity to remember the selected device across runs."""
    return (getattr(device, "model", "") or "", display_name(device))


def select_device(devices: List, model: str, name: str):
    """Return the remembered device, or the first available one."""
    for device in devices:
        if device_key(device) == (model, name):
            return device
    return devices[0] if devices else None


def signature(devices: Iterable, pointers: Iterable[PointerDevice]) -> Tuple:
    """Cheap signature used to detect hotplug changes."""
    return (
        tuple(sorted(device_key(device) for device in devices)),
        tuple(sorted(pointer.key for pointer in pointers)),
    )
