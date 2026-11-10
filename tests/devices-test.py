#!/usr/bin/env python3

import argparse
import os
import sys
import tempfile
import unittest


def write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(value)


def make_event(root, name, vendor, product, pointer=True):
    base = os.path.join(root, name, "device")
    write(os.path.join(base, "name"), name)
    write(os.path.join(base, "id", "vendor"), vendor)
    write(os.path.join(base, "id", "product"), product)
    write(os.path.join(base, "capabilities", "rel"), "3" if pointer else "0")
    write(
        os.path.join(base, "capabilities", "key"), "10000 0 0 0 0" if pointer else "0"
    )


class FakeDevice:
    def __init__(self, model="usb:046d:4085:0", name="Logitech G604", device_type=2):
        self.model = model
        self.name = name
        self.device_type = device_type


class TestDevices(unittest.TestCase):
    def setUp(self):
        from piper import devices

        self.devices = devices

    def test_bitmap_has_uses_most_significant_word_first(self):
        bitmap = "10000 0 0 0 0"
        self.assertTrue(self.devices.bitmap_has(bitmap, 0x110))
        self.assertFalse(self.devices.bitmap_has(bitmap, 0x111))
        self.assertFalse(self.devices.bitmap_has("0", 0x110))

    def test_model_ids(self):
        self.assertEqual(self.devices.model_ids("usb:046d:4085:0"), ("046d", "4085"))
        self.assertIsNone(self.devices.model_ids(""))
        self.assertIsNone(self.devices.model_ids("bluetooth:aa:bb"))

    def test_list_pointer_devices_filters_keyboards_and_non_pointers(self):
        with tempfile.TemporaryDirectory() as root:
            make_event(
                root, "event0", "3842", "260a", pointer=True
            )  # EVGA Z20 keyboard mouse
            write(
                os.path.join(root, "event0", "device", "name"),
                "EVGA Z20 Elite Gaming Keyboard Mouse",
            )
            make_event(root, "event1", "046d", "4085", pointer=True)
            make_event(root, "event2", "1234", "5678", pointer=False)

            found = self.devices.list_pointer_devices(root)

            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].vendor, "046d")
            self.assertEqual(found[0].product, "4085")

    def test_incompatible_pointers_matches_model(self):
        supported = [FakeDevice()]
        pointers = [
            self.devices.PointerDevice("Logitech G604", "046d", "4085", "event8"),
            self.devices.PointerDevice("Other Mouse", "046d", "c539", "event9"),
        ]

        incompatible = self.devices.incompatible_pointers(supported, pointers)

        self.assertEqual([pointer.product for pointer in incompatible], ["c539"])

    def test_status_and_selection(self):
        self.assertEqual(self.devices.status([], []), self.devices.STATUS_NO_DEVICE)
        self.assertEqual(
            self.devices.status([], [object()]), self.devices.STATUS_NO_COMPATIBLE
        )
        first = FakeDevice(model="usb:046d:4085:0", name="G604")
        second = FakeDevice(model="usb:046d:c539:0", name="G Pro")
        self.assertEqual(
            self.devices.status([first], []), self.devices.STATUS_AVAILABLE
        )
        self.assertIs(self.devices.select_device([first, second], "", ""), first)
        self.assertIs(
            self.devices.select_device([first, second], "usb:046d:c539:0", "G Pro"),
            second,
        )

    def test_signature_changes_with_hotplug(self):
        first = FakeDevice()
        pointers = [self.devices.PointerDevice("G604", "046d", "4085", "event8")]
        before = self.devices.signature([first], pointers)
        after = self.devices.signature([first], [])
        self.assertNotEqual(before, after)


def main():
    parser = argparse.ArgumentParser(description="piper.devices tests")
    parser.add_argument("sourcedir", nargs=1, help="Path to the source tree root")
    args, remainder = parser.parse_known_args()

    sys.path.insert(0, args.sourcedir[0])

    unittest.main(argv=[sys.argv[0], *remainder])


if __name__ == "__main__":
    main()
