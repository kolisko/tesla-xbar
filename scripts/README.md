# Installation and development tools

Run these commands from the repository root.

| File | Purpose | Command |
| --- | --- | --- |
| [`install.py`](install.py) | Build helpers, install the application and generate shell launchers while preserving an existing private profile and refresh interval. | `python3 -m scripts.install` |
| [`build_commands.py`](build_commands.py) | Download and build the pinned revision of Tesla's official Go command tool into `build/`. | `python3 -m scripts.build_commands` |
| [`check_public_files.py`](check_public_files.py) | Scan Git-tracked files for private profile data, personal identifiers and image metadata. | `python3 scripts/check_public_files.py` |
| [`render_previews.py`](render_previews.py) | Generate SVG documentation illustrations using fictional vehicle data. | `python3 scripts/render_previews.py` |

For Python-only updates with unchanged helpers, use `python3 -m scripts.install --runtime-only`. The installer and command builder run as Python modules; `__init__.py` provides their package. Use `python3 -m scripts.install --help` for installer options.

The shell entry point is generated inside `install.py`, rather than stored with a hard-coded path. Compilation outputs, module caches and the downloaded SDK belong in the ignored root `build/` directory. Credentials and signing keys belong in the user's private profile, outside the repository.

See the [setup guide](../docs/SETUP.md) and [contribution guide](../.github/CONTRIBUTING.md).
