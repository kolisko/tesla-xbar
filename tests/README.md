# Automated tests

These tests use fake Tesla clients and temporary local profiles. They do not require a Tesla account or send commands to a real vehicle.

| File | Coverage |
| --- | --- |
| [`test_tesla_xbar.py`](test_tesla_xbar.py) | Refresh behavior, token renewal, range and percentage display, colors, cached readings and manual wake. |
| [`test_commands.py`](test_commands.py) | Charging and port commands, required permissions, signed command handling and target validation. |
| [`test_locks_trunks.py`](test_locks_trunks.py) | Grouped lock/trunk menu, signed and legacy commands, scoped access, vehicle binding, cached closure readings, one-shot toggles and acknowledgement versus observed state. |
| [`test_reliability.py`](test_reliability.py) | Offline/asleep states, rate-limit responses, concurrent actions and vehicle selection. |
| [`test_install.py`](test_install.py) | Installation, generated launchers, private-key handling and preservation of profiles, helpers and refresh intervals. |
| [`test_status_icons.py`](test_status_icons.py) | Camp/Pet/climate/unlock/trunk field selection, closure and lock independence, section freshness, partial responses, offline behavior and all 191 prebuilt menu-bar image combinations. |
| [`test_clima.py`](test_clima.py) | Climate mode and power transitions, temperature validation, signed/legacy command parameters, scope checks, partial failures, acknowledgement versus confirmation and menu argument routing. |
| [`test_command_audit.py`](test_command_audit.py) | The dependency audit's source copy includes the adapter and preserves the pinned SDK checkout. |

Run the full suite from the repository root:

```sh
python3 -B -m unittest discover -s tests
```

To run only installer tests, use `python3 -B -m unittest tests.test_install`. The package marker `__init__.py` allows test modules to share their fake clients.

These automated tests do not replace testing menu interactions in the real xBar application. See the [contribution guide](../.github/CONTRIBUTING.md).

`test_location_map.py` covers explicit map opt-in, reuse while asleep, vehicle/position binding, map failures, corrupt images, provider Retry-After, disabling and transport bounds. Tests use generated PNG fixtures and fake services; they never send a vehicle position to a map provider.

`python3 -m scripts.build_commands` also runs the Go adapter tests from
[`src/commands/climate_test.go`](../src/commands/climate_test.go) in the pinned SDK
package using the build overlay. They never connect to a vehicle.

`test_sentry_location.py` covers Sentry authorization, signed/legacy command mapping, menu dispatch, active-state freshness, opt-in GPS access, revoked scopes, stale/moved locations, address failures and disabling location. No vehicle or geocoding service is contacted.
