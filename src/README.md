# Application source

This directory contains the code installed on the user's Mac.

| File | Purpose |
| --- | --- |
| [`tesla_xbar.py`](tesla_xbar.py) | Fleet API access, OAuth login and renewal, cached readings, xBar menu output and explicit vehicle actions. Uses the Python standard library. |
| [`keychain.swift`](keychain.swift) | Source for the `tesla-keychain` executable. Reads and writes credentials in macOS Keychain using JSON over stdin and stdout. |
| [`icons/`](icons/README.md) | Editable SVG sources and prebuilt PNG strips for the live climate and unlock indicators. |
| [`__init__.py`](__init__.py) | Allows tests to import the runtime from the checkout. |

Run `python3 -m scripts.install` from the repository root to install the application. The [installer](../scripts/install.py) copies `tesla_xbar.py`, PNG icons and the compiled helpers into the private profile directory. Their installed filenames and locations remain the same regardless of this source layout.

The installer also generates `tesla-action.sh` and the `tesla-battery.1m.sh` xBar entry point with local executable paths. Tesla's Go command helper is built separately by [`scripts/build_commands.py`](../scripts/build_commands.py).

See the [architecture and configuration overview](../README.md#architecture) and [setup guide](../docs/SETUP.md).
