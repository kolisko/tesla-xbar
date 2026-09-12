# Application

Contents of this directory. See [Architecture](../../../docs/ARCHITECTURE.md) for layer responsibilities, dependency rules and runtime behavior.

| File | Contents |
| --- | --- |
| [`ports.py`](ports.py) | Profile, clock, vehicle, credentials, identity, input, map/geocoder contracts; request/result/menu context. |
| [`plugin.py`](plugin.py) | Dispatch application requests, hold locks and return data/results. |
| [`vehicle.py`](vehicle.py) | Vehicle selection, refresh, last-reading retention and explicit wake wait. |
| [`commands.py`](commands.py) | Consent/current-state checks, semantic command dispatch and result verification. |
| [`accounts.py`](accounts.py) | Account registration and profile updates after authorization. |
| [`settings.py`](settings.py) | Shared settings/credential update rules. |
| [`location.py`](location.py) | Location timestamp/address reuse and map-refresh policy. |
| [`__init__.py`](__init__.py) | Package marker. |
