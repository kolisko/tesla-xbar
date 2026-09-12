# Presentation

| File | Contents |
| --- | --- |
| [`cli.py`](cli.py) | Parse arguments into `Request`; print the application's result through a supplied presenter. |
| [`menu.py`](menu.py) | Pure `MenuRenderer`: xBar text, submenus, command arguments and image encoding. |
| [`settings_form.py`](settings_form.py) | Pure settings form markup using the shared schema. |
| [`__init__.py`](__init__.py) | Package marker. |

The renderer receives data plus a prepared `MenuContext`: one timestamp, launcher path, image bytes, command results and notices. It never reads files, obtains credentials, fetches data or starts helpers. Infrastructure must not be imported here. Interactive terminal/HTTP IO lives in the input adapters, which receive the form and settings callbacks from bootstrap.
