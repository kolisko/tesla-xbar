# Domain

Contents of this directory. See [Architecture](../../../docs/ARCHITECTURE.md) for layer responsibilities, dependency rules and runtime behavior.

| File | Contents |
| --- | --- |
| [`models.py`](models.py) | Reading interpretation, range, cable/color/freshness rules, status indicators and command labels. |
| [`commands.py`](commands.py) | `VehicleCommand`, parameter validation and observed-state confirmation rules. |
| [`settings.py`](settings.py) | Shared settings definitions, defaults, choices and validation. |
| [`location.py`](location.py) | Geographic coordinate validation. |
| [`errors.py`](errors.py) | Safe errors and transport-independent failure categories. |
| [`__init__.py`](__init__.py) | Package marker. |
