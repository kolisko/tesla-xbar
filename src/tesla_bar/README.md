# Python runtime

The plugin remains a short-lived standard-library Python program. Each module owns a specific responsibility; importing it performs no vehicle requests or profile writes.

| Module | Responsibility |
| --- | --- |
| [`cli.py`](cli.py) | Dispatch menu actions, hold profile locks and close network connections when the invocation finishes. |
| [`config.py`](config.py) | Shared setting definitions, defaults, validation, loading and saving. No credentials are stored here. |
| [`settings_ui.py`](settings_ui.py) | Terminal prompts and temporary loopback browser form. Both use the same validation and credential update path. |
| [`auth.py`](auth.py) | Keychain access, OAuth callback, token renewal, domain registration and one region check after sign-in. |
| [`api.py`](api.py) | Fleet API requests, one retry after an explicit 401, vehicle capabilities and dispatch to signed commands. |
| [`transport.py`](transport.py) | HTTPS connection reuse per origin during one process. Preserve proxy support, reject redirects and do not replay uncertain requests. |
| [`vehicle.py`](vehicle.py) | Fetch the selected vehicle, preserve cached readings and provide explicit wake-and-refresh. |
| [`models.py`](models.py) | Interpret readings, freshness, range, cable state and active icons; shared command definitions. No I/O. |
| [`commands.py`](commands.py) | Validate and send explicit physical commands, invoke the pinned Go helper when signing is required and verify results from fresh readings. |
| [`location.py`](location.py) | Optional geocoding, bounded map download and private map cache. No Tesla credentials are sent to map services. |
| [`menu.py`](menu.py) | Convert saved state into xBar text/images and menu actions. Rendering never requests live vehicle data. |
| [`runtime.py`](runtime.py) | Profile/helper paths, atomic JSON writes and process locks. |
| [`errors.py`](errors.py) | Safe application/API errors without raw credentials or request bodies. |

Dependency flow: CLI → auth/settings, vehicle/commands and menu → API/models/location → transport/config/runtime. The API client delegates signing to commands only when explicitly asked to issue a command. Normal refresh never takes that path.

In a checkout, modules are ordinary files. The installer puts their `.py` files in `tesla-runtime.zip`, replaced atomically, so it cannot expose a partially copied module set to a new invocation. The Python entrypoint loads this bundle with standard zipimport. Swift/Go helpers and icons remain beside it. No package manager, Python dependency or background service is added.

Keep tests offline: patch the owning module or pass a fake client. `src/tesla_xbar.py` retains explicit imports for older checkout callers, but new implementation code imports the responsible module directly. Do not patch copied facade constants; profile and helper paths belong to `runtime`.
