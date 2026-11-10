# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.9] - 2026-11-09

### Added

- **Settings and global profile shortcut.** A new *Settings* entry (before
  *About Piper*) opens a modal, borderless panel inside the main window. It
  registers a global keyboard shortcut through the XDG Desktop Portal
  (`org.freedesktop.portal.GlobalShortcuts`) that switches every connected
  mouse to its next enabled profile. The cycle wraps around and skips disabled
  profiles. It works while another window (for example a game) has focus, as
  long as Piper is running.
- Spanish translations for the new Settings UI.
- Unit test for the profile cycling logic.
- CI matrix entry (`runtime-checks`) that configures with runtime dependency
  checks enabled.

### Fixed

- `Application.init_ratbagd()` stored the new instance in `self._ratbag` but
  checked `self._ratbagd`, so every call created a new `Ratbagd` object.
- CI now runs `meson test` and no longer keeps the libratbag-specific
  `data/devices` step.
- Configure now validates the GTK 3.22+ and librsvg typelibs instead of
  failing later at application startup.
- The Flatpak manifest now uses the GNOME 50 runtime, current `evdev`/`lxml`
  releases and a pinned Piper commit. The build no longer tries to uninstall
  the SDK's read-only `lxml` copy.
- The main CI workflow pins its GitHub Actions by commit SHA.
- Hardened the global shortcut integration: it supports portal v1/v2, bounds
  portal requests with timeouts, recovers from transient errors and cancelled
  sessions, and confines keyboard focus inside the Settings panel with Tab.

### Changed

- The Settings window is now a standard modal dialog, matching the About Piper
  window format.
- Version bumped to 0.9.
- README updated with the new Settings feature, build notes and contributor
  information.
