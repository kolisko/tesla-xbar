# Domain

Pure rules with explicit inputs. This layer has no filesystem, network, credentials, process execution or implicit clock.

| File | Contents |
| --- | --- |
| [`models.py`](models.py) | Reading interpretation, range, cable/color/freshness rules, status indicators and command labels. |
| [`commands.py`](commands.py) | `VehicleCommand`, parameter validation and observed-state confirmation rules. |
| [`settings.py`](settings.py) | Shared settings definitions, defaults, choices and validation. |
| [`location.py`](location.py) | Geographic coordinate validation. |
| [`errors.py`](errors.py) | Safe errors and transport-independent failure categories. |
| [`__init__.py`](__init__.py) | Package marker. |

Tesla URLs, HTTP status mappings, numeric keeper command codes and CLI argument mappings belong in infrastructure. Pass `now` explicitly to freshness rules.
