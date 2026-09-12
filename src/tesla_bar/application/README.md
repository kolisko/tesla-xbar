# Application

Use cases depend on the domain and the interfaces in `ports.py`. Dependencies arrive through constructors; services never create concrete adapters.

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

All physical actions use `VehicleGateway.execute(VehicleCommand)`. Services see pairing readiness and safe failure categories, not signing algorithms or HTTP errors. No file paths, network requests, helper execution or xBar output are allowed here.
