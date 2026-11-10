#!/usr/bin/env python3

import argparse
import sys
import tempfile
import unittest


class TestSettings(unittest.TestCase):
    def setUp(self):
        from piper.settings import Settings

        self._tmp = tempfile.TemporaryDirectory()
        self.Settings = Settings

    def tearDown(self):
        self._tmp.cleanup()

    def _settings(self):
        return self.Settings(self._tmp.name)

    def test_selected_device_roundtrip(self):
        settings = self._settings()
        settings.set_selected_device("usb:046d:4085:0", "Logitech G604")

        reloaded = self._settings()

        self.assertEqual(reloaded.selected_device, ("usb:046d:4085:0", "Logitech G604"))

    def test_profile_name_roundtrip(self):
        settings = self._settings()
        settings.set_profile_name("usb:046d:4085:0", "Logitech G604", 1, "Juego")

        reloaded = self._settings()

        self.assertEqual(
            reloaded.profile_name("usb:046d:4085:0", "Logitech G604", 1), "Juego"
        )

    def test_empty_profile_name_removes_entry(self):
        settings = self._settings()
        settings.set_profile_name("usb:046d:4085:0", "Logitech G604", 1, "Juego")
        settings.set_profile_name("usb:046d:4085:0", "Logitech G604", 1, "")

        self.assertIsNone(
            self._settings().profile_name("usb:046d:4085:0", "Logitech G604", 1)
        )

    def test_profile_names_are_per_device_and_index(self):
        settings = self._settings()
        settings.set_profile_name("usb:046d:4085:0", "G604", 0, "Uno")
        settings.set_profile_name("usb:046d:c539:0", "G Pro", 0, "Otro")

        self.assertEqual(settings.profile_name("usb:046d:4085:0", "G604", 0), "Uno")
        self.assertEqual(settings.profile_name("usb:046d:c539:0", "G Pro", 0), "Otro")
        self.assertIsNone(settings.profile_name("usb:046d:4085:0", "G604", 1))


def main():
    parser = argparse.ArgumentParser(description="piper.settings tests")
    parser.add_argument("sourcedir", nargs=1, help="Path to the source tree root")
    args, remainder = parser.parse_known_args()

    sys.path.insert(0, args.sourcedir[0])

    unittest.main(argv=[sys.argv[0], *remainder])


if __name__ == "__main__":
    main()
