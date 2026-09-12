# Python runtime

The runtime uses four dependency-separated layers. See the [architecture guide](../../docs/ARCHITECTURE.md) for diagrams, ports, communication flow and configuration details.

| Path | Responsibility |
| --- | --- |
| [`domain/`](domain/README.md) | Pure rules, semantic commands, settings definitions and application failures. |
| [`application/`](application/README.md) | Use cases and dependency ports; no concrete IO or menu syntax. |
| [`presentation/`](presentation/README.md) | CLI adapter, pure xBar rendering and settings form markup. |
| [`infrastructure/`](infrastructure/README.md) | Concrete Tesla, Keychain, profile, clock, map and local input adapters. |
| [`bootstrap.py`](bootstrap.py) | Sole composition root connecting services and adapters. |
| [`__init__.py`](__init__.py) | Package marker. Importing the package performs no requests or profile writes. |

Application services import only the domain and application layer. Presentation and infrastructure may use domain rules and application contracts, but never each other. Architecture tests enforce these directions and reject cycles.

The installer includes all nested `.py` files in one deterministic, atomically replaced `tesla-runtime.zip`. Swift/Go helpers and icons stay beside it. The runtime uses only Python's standard library and remains short-lived.
