#!/usr/bin/env python3

import argparse
import sys
import unittest


class FakeProfile:
    def __init__(self, active=False, disabled=False):
        self.is_active = active
        self.disabled = disabled
        self.activations = 0

    def set_active(self):
        self.activations += 1


def load_next_profile():
    from piper.profiles import next_profile

    return next_profile


class TestNextProfile(unittest.TestCase):
    def setUp(self):
        self.next_profile = load_next_profile()

    def test_cycles_three_enabled_profiles(self):
        profiles = [
            FakeProfile(active=True),
            FakeProfile(),
            FakeProfile(),
        ]

        expected = [profiles[1], profiles[2], profiles[0]]
        for index, following in enumerate(expected):
            self.assertIs(self.next_profile(profiles), following)
            profiles[index].is_active = False
            following.is_active = True

        self.assertIs(self.next_profile(profiles), profiles[1])

    def test_skips_disabled_profiles(self):
        profiles = [
            FakeProfile(active=True),
            FakeProfile(disabled=True),
            FakeProfile(),
        ]

        self.assertIs(self.next_profile(profiles), profiles[2])

        profiles[0].is_active = False
        profiles[2].is_active = True
        self.assertIs(self.next_profile(profiles), profiles[0])

    def test_single_enabled_profile_returns_none(self):
        profiles = [
            FakeProfile(active=True),
            FakeProfile(disabled=True),
        ]

        self.assertIsNone(self.next_profile(profiles))

    def test_no_active_profile_returns_first_enabled(self):
        profiles = [
            FakeProfile(disabled=True),
            FakeProfile(),
            FakeProfile(),
        ]

        self.assertIs(self.next_profile(profiles), profiles[1])

    def test_active_disabled_profile_returns_first_enabled(self):
        profiles = [
            FakeProfile(active=True, disabled=True),
            FakeProfile(),
            FakeProfile(),
        ]

        self.assertIs(self.next_profile(profiles), profiles[1])

    def test_empty_list_returns_none(self):
        self.assertIsNone(self.next_profile([]))

    def test_single_disabled_profile_returns_none(self):
        self.assertIsNone(self.next_profile([FakeProfile(disabled=True)]))

    def test_missing_disabled_flag_is_treated_as_enabled(self):
        first = FakeProfile(active=True)
        second = FakeProfile()
        second.disabled = None

        self.assertIs(self.next_profile([first, second]), second)

    def test_wraps_from_last_enabled_to_first(self):
        profiles = [
            FakeProfile(),
            FakeProfile(disabled=True),
            FakeProfile(active=True),
        ]

        self.assertIs(self.next_profile(profiles), profiles[0])


def main():
    parser = argparse.ArgumentParser(description="piper.profiles.next_profile test")
    parser.add_argument("sourcedir", nargs=1, help="Path to the source tree root")
    args, remainder = parser.parse_known_args()

    sys.path.insert(0, args.sourcedir[0])

    unittest.main(argv=[sys.argv[0], *remainder])


if __name__ == "__main__":
    main()
