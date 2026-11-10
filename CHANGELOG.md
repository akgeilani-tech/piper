# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.9] - 2026-11-09

### Added

- **Settings and global profile shortcut.** A new *Settings* entry (before
  *About Piper*) opens a modal dialog. It registers a global keyboard shortcut
  through the XDG Desktop Portal
  (`org.freedesktop.portal.GlobalShortcuts`) that switches the selected mouse
  to its next enabled profile. The cycle wraps around and skips disabled
  profiles. It works while another window (for example a game) has focus, as
  long as Piper is running.
- **Mouse selector.** A selector to the left of *Profile* lists the mice
  reported by ratbagd, remembers the current mouse in `settings.ini`, and
  detects hotplug events. It shows *Mouse not supported* or *Mouse not
  available* when there is no usable mouse and disables the profile controls
  and shortcut.
- **Mouse shortcut.** A second global shortcut switches between compatible
  mice. The profile shortcut always applies to the selected mouse and commits
  immediately, without asking about unrelated pending changes.
- **Persistent profile names.** Profiles can be renamed inline. Since many
  devices (including the Logitech G604) silently ignore ratbagd's writable
  `Name` property, Piper stores names in `settings.ini` and restores them on
  the next start.
- **Appearance and startup settings.** The Settings dialog adds a color mode
  (Dark, Light or System, following the desktop appearance portal), an option
  to start Piper automatically with the session, and an option to start
  minimized in the system tray. Settings persist in
  `$XDG_CONFIG_HOME/piper/settings.ini`.
- **System tray icon.** Piper registers a KDE StatusNotifierItem so it can keep
  running in the tray, restore its window from the icon and hide instead of
  quitting when the window is closed. The tray is always created, retries the
  watcher at login and exposes a DBusMenu with *Show Piper*, *Settings* and
  *Quit*.
- **Partial device support warning.** Devices whose `Commit` does not persist
  (for example the Logitech G602 with libratbag 0.18) show a warning and have
  *Apply* disabled. The check is generic: if a device remains dirty four
  seconds after a successful commit, saving is disabled for that device.
- **Single-profile devices.** The profile selector is usable even when the
  mouse only exposes one profile, so the active profile is visible.
- **Quit menu entry.** *Salir*/*Quit* appears after *About Piper* and exits the
  application and its tray icon for the current session without changing the
  saved configuration.
- English and Spanish translation profiles, with Spanish translations for the
  complete interface.
- Unit test for the profile cycling logic.
- Tests for mouse discovery/status, profile-name persistence and device
  selection.
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
- Flatpak no longer splits translations into a separate `Locale` runtime
  extension, so rebuilt bundles always ship their current `.mo` files instead
  of loading a stale extension.
- The `.ui` templates declare the `piper` translation domain and gettext is
  configured before the application modules load, so translated templates no
  longer fall back to English.
- Switching the selected mouse disconnects the previous device signals, so
  profile changes no longer render another mouse's profiles.
- The active profile cannot be disabled from the profile list, and profile
  enable/disable operations respect `CAP_DISABLE` and report D-Bus errors in
  the in-app banner.
- If the portal advertises `ConfigureShortcuts` v2 but returns
  `UnknownMethod`, Piper now falls back to the v1 rebind path instead of
  leaving the shortcut inactive.
- The Breeze GTK theme switches between `Breeze` and `Breeze-Dark`, and the
  System color mode reacts to `SettingChanged`.
- Autostart uses `flatpak run` only inside the Flatpak and respects
  `XDG_CONFIG_HOME` for native installs.
- `Escape` closes the Settings dialog, and the shortcut help icon and value
  have accessible names and tooltips.
- ratbagd exits after 20 minutes without D-Bus activity. Piper now sends a
  keepalive every 10 minutes and reconnects automatically, rebuilding the
  window, if the daemon disappears anyway.

### Changed

- The Settings window is now a standard modal dialog, matching the About Piper
  window format.
- Version bumped to 0.9.
- README updated with the new Settings feature, build notes and contributor
  information.
