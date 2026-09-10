# Automated tests

These tests use fake Tesla clients and temporary local profiles. They do not require a Tesla account or send commands to a real vehicle.

| File | Coverage |
| --- | --- |
| [`test_tesla_xbar.py`](test_tesla_xbar.py) | Refresh behavior, token renewal, range and percentage display, colors, cached readings and manual wake. |
| [`test_commands.py`](test_commands.py) | Charging and port commands, required permissions, signed command handling and target validation. |
| [`test_reliability.py`](test_reliability.py) | Offline/asleep states, rate-limit responses, concurrent actions and vehicle selection. |
| [`test_install.py`](test_install.py) | Installation, generated launchers, private-key handling and preservation of profiles, helpers and refresh intervals. |
| [`test_status_icons.py`](test_status_icons.py) | Camp/Pet/climate/unlock field selection, section freshness, partial responses, offline behavior and prebuilt menu-bar image combinations. |

Run the full suite from the repository root:

```sh
python3 -B -m unittest discover -s tests
```

To run only installer tests, use `python3 -B -m unittest tests.test_install`. The package marker `__init__.py` allows test modules to share their fake clients.

These automated tests do not replace testing menu interactions in the real xBar application. See the [contribution guide](../.github/CONTRIBUTING.md).
