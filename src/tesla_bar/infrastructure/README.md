# Infrastructure adapters

Contents of this directory. See [Architecture](../../../docs/ARCHITECTURE.md) for layer responsibilities, dependency rules and runtime behavior.

| File | Contents |
| --- | --- |
| [`gateway.py`](gateway.py) | `TeslaGateway`: semantic vehicle operations, filtered snapshots and hidden transport capabilities. |
| [`api.py`](api.py) | Low-level Fleet API client, explicit 401 token renewal and capability requests. |
| [`command_transport.py`](command_transport.py) | REST/official Go helper command mapping, signing invocation and safe command errors. |
| [`auth.py`](auth.py) | Keychain helper, token exchange/renewal, allowed region discovery, registration requests and temporary OAuth callback adapter. |
| [`transport.py`](transport.py) | Bounded HTTPS connection reuse, proxy support, redirect rejection and no uncertain request replay. |
| [`errors.py`](errors.py) | Translate HTTP status codes to domain failure categories. |
| [`profile.py`](profile.py) | File-backed named records, compatibility mapping, system clock, credential-vault and setup-session adapters. |
| [`configuration.py`](configuration.py) | Strict profile JSON loading/saving; regional Tesla endpoint allowlist. |
| [`runtime.py`](runtime.py) | Local paths, atomic private JSON IO and process locks. |
| [`maps.py`](maps.py) | Apple geocoder, MapMap viewport/download, validated private PNG storage and native map renderer. |
| [`display.py`](display.py) | Icon bytes and atomic display-snapshot publication. |
| [`settings_input.py`](settings_input.py) | Terminal prompts and temporary loopback form server with supplied validation/save callbacks. |
| [`__init__.py`](__init__.py) | Package marker. |
