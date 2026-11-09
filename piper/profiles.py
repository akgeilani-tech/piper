# SPDX-License-Identifier: GPL-2.0-or-later


def next_profile(profiles):
    """Return the next enabled profile after the active one.

    Disabled profiles are skipped. The selection wraps around, and the first
    enabled profile is returned when no profile is active. Less than two
    enabled profiles leaves nothing to cycle through, so None is returned.
    """
    enabled = [profile for profile in profiles if not profile.disabled]
    if len(enabled) < 2:
        return None
    for index, profile in enumerate(enabled):
        if profile.is_active:
            return enabled[(index + 1) % len(enabled)]
    return enabled[0]
