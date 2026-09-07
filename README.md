# Tesla xBar

[![CI](https://github.com/kolisko/tesla-xbar/actions/workflows/ci.yml/badge.svg)](https://github.com/kolisko/tesla-xbar/actions/workflows/ci.yml)
[![CodeQL](https://github.com/kolisko/tesla-xbar/actions/workflows/codeql.yml/badge.svg)](https://github.com/kolisko/tesla-xbar/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Your Tesla's battery range or percentage in the macOS menu bar, powered by the official Fleet API. Built for [xBar](https://xbarapp.com/), with English menus, local credential storage and explicit charging controls.

<img src="docs/images/menu-bar.png" alt="Menu bar preview: green 360 km with a lightning icon" width="320">

## See it in action

Open the menu to see battery percentage, Tesla's range, charge limit, cable connection, charging power and the time of the last reading.

<img src="docs/images/menu.png" alt="Tesla xBar dropdown showing battery information, charging controls, refresh and account settings" width="420">

*Illustrated previews with fictional data and a neutral background. Native fonts, emoji and transparency vary with macOS and xBar. No personal desktop screenshots are included.*

<img src="docs/images/states.png" alt="Six display states: charging, connected but paused, orange low range, red low range, asleep and offline" width="1000">

## Features

- **Range or percentage:** switch through **Menu bar display**. Range comes directly from Tesla's range fields and uses the vehicle's distance units.
- **Cable and charging status:** green when connected, including scheduled or paused charging; a lightning symbol marks fresh online charging data.
- **Low-range colors:** orange below 350 km and red below 300 km when unplugged. Connected cable status takes precedence.
- **Last known data:** asleep (`☾`) and offline (`⛓️‍💥`) keep the saved range or percentage. A dot marks an old or unverified reading; the original timestamp stays visible in the menu.
- **One refresh schedule:** xBar's filename controls polling (`1m`, `5m`, etc.). **Refresh now** uses the same path. No second polling timer or invented monthly quota.
- **Explicit commands:** wake and refresh, start/stop charging, and open/close the charge port. Normal refresh never sends a wake command.
- **Private profiles:** tokens and Client Secret in Keychain; configuration, signing key and cached readings in the current user's Application Support directory.
- **Updates preserve your setup:** existing keys, credentials, readings and xBar interval remain intact.

## Install

Requires macOS, xBar, Python 3.9+, Go 1.23+, OpenSSL, Git and Apple's Command Line Tools. The installer builds the small Swift Keychain helper and Tesla's official command helper from a pinned source revision.

```sh
git clone https://github.com/kolisko/tesla-xbar.git
cd tesla-xbar
python3 install.py
```

**You need your own Tesla Developer app, credentials and public-key hosting domain.** This project does not supply shared credentials or a hosted Tesla backend. Follow the [complete setup guide](docs/SETUP.md) to publish your public key, configure the developer app, register its region and connect your account.

Tesla controls app approval, API availability, permissions and billing. See [Tesla Fleet API billing](https://developer.tesla.com/docs/fleet-api/billing-and-limits) before enabling polling.

## Privacy and security

The public project contains code, tests and demonstration graphics. Private configuration lives in:

```text
~/Library/Application Support/Tesla xBar/
```

OAuth tokens and Client Secret use macOS Keychain. Signing keys are generated outside the checkout, and private files use restricted permissions. Each user has their own Tesla registration and keys. No analytics or vehicle location is collected by the plugin.

The temporary OAuth callback runs only on localhost. Signed command tokens travel through stdin rather than process arguments or temporary files. Physical commands are bound to the vehicle displayed in the menu. Concurrent manual actions are rejected with a visible notice instead of queued.

GitHub checks include **CodeQL for Python and Swift, Gitleaks, a privacy scan, Dependabot, unit tests, macOS builds and a Go dependency vulnerability audit**. See [SECURITY.md](SECURITY.md) for the security model and private vulnerability reporting.

## Behavior and limits

- Offline is not proof of sleep. An HTTP 408 is treated as unavailable; only an explicit `asleep` state gets the moon.
- An offline/asleep reading can be old. The plugin keeps it and shows its timestamp; it never fabricates a fresh value.
- Range is never estimated from battery percentage. API miles are converted to kilometers only when required by the vehicle's units.
- Range/percentage selection is local. Automatic synchronization with the Tesla mobile app's display preference is not implemented.
- Smooth green pulsing is not implemented; charging uses a static green label and lightning icon.
- Avoiding wake commands does not guarantee that frequent live data reads cannot delay an already awake vehicle's sleep. Tesla recommends Fleet Telemetry for ongoing data needs; this local plugin uses polling. See [Tesla's API best practices](https://developer.tesla.com/docs/fleet-api/getting-started/best-practices).
- Signed charging commands may require pairing the app key in the Tesla mobile app. Charging schedules, current and charge limit are not changed by the plugin.
- **Command accepted** is not the same as confirmed physical state. Confirmation appears only after a subsequent vehicle data read verifies the change.

## Update

```sh
git pull --ff-only
python3 install.py
```

For Python-only updates with unchanged helpers, use `python3 install.py --runtime-only`. Change intervals through xBar's plugin management so the running app picks up the new filename.

## Development

```sh
python3 -B -m unittest test_tesla_xbar test_commands test_reliability test_install
python3 scripts/check_public_files.py
```

The tests use fake Tesla clients and temporary profiles; they do not send commands to real vehicles. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT for this project's code and illustrations. Tesla's separately built command SDK is Apache-2.0; see [third-party notices](THIRD_PARTY_NOTICES.md). This project is independent and is not affiliated with or endorsed by Tesla or xBar.
