# Python runtime

Contents of this directory. See [Architecture](../../docs/ARCHITECTURE.md) for layer responsibilities, dependency rules and runtime behavior.

| Path | Responsibility |
| --- | --- |
| [`domain/`](domain/README.md) | Pure rules, semantic commands, settings definitions and application failures. |
| [`application/`](application/README.md) | Use cases and dependency ports; no concrete IO or menu syntax. |
| [`presentation/`](presentation/README.md) | CLI adapter, pure xBar rendering and settings form markup. |
| [`infrastructure/`](infrastructure/README.md) | Concrete Tesla, Keychain, profile, clock, map and local input adapters. |
| [`bootstrap.py`](bootstrap.py) | Sole composition root connecting services and adapters. |
| [`__init__.py`](__init__.py) | Package marker. Importing the package performs no requests or profile writes. |
