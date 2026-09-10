# Installation and development tools

Run these commands from the repository root.

| File | Purpose | Command |
| --- | --- | --- |
| [`install.py`](install.py) | Build helpers, install the application and generate shell launchers while preserving an existing private profile and refresh interval. | `python3 -m scripts.install` |
| [`build_commands.py`](build_commands.py) | Download the pinned Tesla SDK, test the local climate-keeper adapter and build the command helper using a Go overlay. The SDK checkout remains unchanged. | `python3 -m scripts.build_commands` |
| [`check_public_files.py`](check_public_files.py) | Scan Git-tracked files for private profile data, personal identifiers and image metadata. | `python3 scripts/check_public_files.py` |
| [`render_previews.py`](render_previews.py) | Generate SVG documentation illustrations using fictional vehicle data. | `python3 scripts/render_previews.py` |
| [`render_status_icons.cjs`](render_status_icons.cjs) | Generate Retina PNG status icons and their fictional documentation preview from the SVG sources in `src/icons/`. Development only; requires Node.js and `sharp`. | `node scripts/render_status_icons.cjs` |

For runtime and icon updates with unchanged helpers, use `python3 -m scripts.install --runtime-only`. The installer and command builder run as Python modules; `__init__.py` provides their package. Use `python3 -m scripts.install --help` for installer options.

The Clima controls update requires a full install to rebuild `tesla-control` with
the adapter. `build/command-overlay.json` is generated locally for builds, adapter
tests and the dependency audit; it contains local paths and must remain untracked.

To regenerate status icons without adding runtime dependencies, install the optional
renderer in the ignored build directory:

```sh
npm install --prefix build/icon-tools --no-save sharp@0.35.4
NODE_PATH="$PWD/build/icon-tools/node_modules" node scripts/render_status_icons.cjs
```

Commit the regenerated `src/icons/*.png` and `docs/images/status-icons.*` alongside
any SVG changes. The plugin uses only the committed PNGs.

The shell entry point is generated inside `install.py`, rather than stored with a hard-coded path. Compilation outputs, module caches and the downloaded SDK belong in the ignored root `build/` directory. Credentials and signing keys belong in the user's private profile, outside the repository.

See the [setup guide](../docs/SETUP.md) and [contribution guide](../.github/CONTRIBUTING.md).
