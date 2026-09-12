# Presentation

Contents of this directory. See [Architecture](../../../docs/ARCHITECTURE.md) for layer responsibilities, dependency rules and runtime behavior.

| File | Contents |
| --- | --- |
| [`cli.py`](cli.py) | Parse arguments into `Request`; print the application's result through a supplied presenter. |
| [`menu.py`](menu.py) | Pure `MenuRenderer`: xBar text, submenus, command arguments and image encoding. |
| [`settings_form.py`](settings_form.py) | Pure settings form markup using the shared schema. |
| [`__init__.py`](__init__.py) | Package marker. |
