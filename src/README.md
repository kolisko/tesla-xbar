# Application source

This directory contains the code installed on the user's Mac.

| File | Purpose |
| --- | --- |
| [`tesla_xbar.py`](tesla_xbar.py) | Small CLI entrypoint calling the composition root. |
| [`tesla_bar/`](tesla_bar/README.md) | Four-layer Python runtime: domain, application services/ports, presentation and infrastructure. Standard library only. |
| [`keychain.swift`](keychain.swift) | Source for the `tesla-keychain` executable. Reads and writes credentials in macOS Keychain using JSON over stdin and stdout. |
| [`location.swift`](location.swift) | Source for `tesla-location`: bounded Apple reverse geocoding of coordinates received over stdin. No Tesla secrets or Mac location access. |
| [`map_image.swift`](map_image.swift) | Source for `tesla-map-image`: local AppKit composition of a blue vehicle dot on MapMap image bytes, returning a 144 DPI PNG. No network or Mac GPS access. |
| [`icons/`](icons/README.md) | Editable SVG sources and prebuilt PNG strips for charging, climate, unlock, Sentry and front/rear trunk indicators. |
| [`commands/`](commands/README.md) | Small Go adapter and tests that expose climate-keeper modes through the pinned Tesla command helper. |
| [`__init__.py`](__init__.py) | Allows tests to import the runtime from the checkout. |

Run `python3 -m scripts.install` from the repository root to install the application. The [installer](../scripts/install.py) copies `tesla_xbar.py`, an atomic `tesla-runtime.zip` module bundle, PNG icons and the compiled helpers into the private profile directory. Their installed filenames and locations remain the same regardless of this source layout.

The installer also generates `tesla-action.sh` and the `tesla-battery.1m.sh` xBar entry point with local executable paths. Tesla's Go command helper is built separately by [`scripts/build_commands.py`](../scripts/build_commands.py).

See the [architecture and configuration overview](../README.md#architecture) and [setup guide](../docs/SETUP.md).
