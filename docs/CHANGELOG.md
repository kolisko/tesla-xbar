# Changelog

Release tags use `vMAJOR.MINOR.PATCH`; the installed xBar plugin metadata uses the same version without the `v` prefix.

## Unreleased

- Split the Python runtime into focused modules while preserving the existing CLI and vehicle behavior.
- Reuse direct HTTPS connections within each invocation; retain proxy support and never automatically replay uncertain commands.
- Verify the account region once after sign-in against official Tesla hosts, with the configured region as fallback.
- Share settings defaults, choices and validation across profile loading, Terminal/browser settings, menu actions and installation.
- Install Python modules as one atomic bundle; preserve existing settings, keys, readings and refresh interval.
- Preserve cached readings when saving credentials for the same application through the browser form.

## v0.2.0 — 2026-09-12

### Added

- **Clima** controls for normal climate, Keep Climate On, Camp Mode, Pet Mode, temperature selection and full climate/mode shutdown. The menu shows inside and outside temperatures separately from the target temperature.
- **Sentry** on/off controls and a matching menu-bar indicator.
- **Locks and trunks** controls for locking/unlocking, opening the front trunk and opening/closing a supported rear trunk. Front and rear closure indicators are independent of the lock state.
- **Location**, enabled with separate consent, with an address, reading timestamp and Apple Maps link. An optional MapMap preview shows the position directly in the menu with a blue dot and no POI pins.
- Matching monochrome charging, Camp, Pet, climate fan, unlocked vehicle, Sentry and trunk icons.
- Expanded architecture, configuration and setup documentation, directory guides and visual previews using fictional readings and a public landmark map.

### Changed and fixed

- Asleep and offline readings retain the last known range or percentage and show a small trailing dot. The last known cable connection stays green; unplugged readings retain their normal range colors.
- Active status icons require fresh, online data. Saved menu readings keep their original timestamps and are labeled as last known when appropriate.
- Clearing a stale location-consent error after authorization no longer depends on the vehicle being awake.
- Source files, installation tools, tests, examples and documentation are organized into dedicated directories.
- The installer now generates plugin metadata with version `0.2.0`.

### Upgrading from v0.1.0

Use the full installer to build the new and updated helpers:

```sh
git fetch --tags
git checkout v0.2.0
python3 -m scripts.install
```

The installer preserves existing private settings, credentials, signing keys, saved readings and the xBar refresh interval. It does not enable Location or map sharing automatically. Location needs Vehicle Location consent; vehicle controls need their documented permissions and virtual-key pairing where required. See the [setup guide](SETUP.md).

This release provides source archives. Build requirements, API access and billing considerations, and current behavior limits are documented in the [README](../README.md).

[Compare v0.1.0…v0.2.0](https://github.com/kolisko/tesla-xbar/compare/v0.1.0...v0.2.0)

## v0.1.0 — 2026-09-07

Initial public release: battery range/percentage, cable and charging status, xBar-controlled refresh scheduling, explicit wake/charging/charge-port actions, private local profiles and Keychain credentials, illustrated setup documentation and automated security checks.

[Release notes](https://github.com/kolisko/tesla-xbar/releases/tag/v0.1.0)
