"""No Tesla or map traffic while the desktop is hidden; resume on the next run."""
import copy
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar.application.plugin import PluginService
from src.tesla_bar.application.ports import MenuContext, Record, Request, Visibility
from src.tesla_bar.domain.models import active_status_icons, charging_is_current
from src.tesla_bar.infrastructure.visibility import DesktopVisibility, visibility_from_snapshot
from src.tesla_bar.presentation.menu import MenuRenderer
from tests.test_layers import MemoryProfile, TestClock, MemoryGateway
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.application.location import LocationService
from src.tesla_bar.application.commands import CommandService


VISIBLE = dict(session_active=True, locked=False, display_awake=True,
               screensaver=False, menu_bar_visible=True)


class VisibilityTests(unittest.TestCase):
    def test_snapshot_classification_including_external_display(self):
        self.assertEqual(visibility_from_snapshot(VISIBLE), Visibility.VISIBLE)
        for field, value, expected in (
            ("session_active", False, Visibility.INACTIVE),
            ("locked", True, Visibility.LOCKED),
            ("display_awake", False, Visibility.DISPLAY_OFF),
            ("screensaver", True, Visibility.SCREENSAVER),
            ("menu_bar_visible", False, Visibility.BAR_HIDDEN),
        ):
            with self.subTest(field=field):
                self.assertEqual(visibility_from_snapshot(VISIBLE | {field: value}), expected)
        # display_awake means *any* active display, so a sleeping built-in panel
        # does not pause use of an awake external display.
        self.assertEqual(visibility_from_snapshot(VISIBLE | {"display_awake": True}), Visibility.VISIBLE)
        for invalid in (None, [], {}, VISIBLE | {"locked": "false"}, VISIBLE | {"display_awake": 1}):
            self.assertEqual(visibility_from_snapshot(invalid), Visibility.UNKNOWN)

    def test_native_adapter_fails_closed_and_has_bounded_runtime(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("probe", 3)):
            with patch("src.tesla_bar.infrastructure.visibility.subprocess.run", side_effect=error):
                self.assertEqual(DesktopVisibility().state(), Visibility.UNKNOWN)
        for stdout, code, expected in (("bad json", 0, Visibility.UNKNOWN),
                                        (json.dumps(VISIBLE), 1, Visibility.UNKNOWN),
                                        (json.dumps(VISIBLE), 0, Visibility.VISIBLE)):
            with patch("src.tesla_bar.infrastructure.visibility.subprocess.run",
                       return_value=Mock(stdout=stdout, returncode=code)) as run:
                self.assertEqual(DesktopVisibility().state(), expected)
                self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_hidden_refresh_never_constructs_gateway_or_changes_saved_reading(self):
        profile, clock, desktop = MemoryProfile(), TestClock(), Mock()
        gateway = MemoryGateway()
        factory = Mock(return_value=gateway)
        maps, geocoder = Mock(), Mock()
        location = LocationService(clock, maps, geocoder)
        vehicles = VehicleService(profile, clock, factory, location)
        commands = CommandService(profile, clock, vehicles, factory)
        app = PluginService(profile, clock, Mock(), vehicles, commands, location, desktop)
        profile.write(Record.STATE, {
            "vin": "EXAMPLE", "state": "online", "updated_at": clock.now(), "checked_at": clock.now(),
            "charge": {"battery_level": 70, "battery_range": 220, "charging_state": "Charging"},
            "gui_settings": {"gui_distance_units": "km/hr", "gui_range_display": "Rated"},
            "climate": {"climate_keeper_mode": "camp", "is_climate_on": True, "updated_at": clock.now()},
        })
        before = copy.deepcopy(profile.records)
        for state in Visibility:
            if state == Visibility.VISIBLE:
                continue
            desktop.state.return_value = state
            for command in ("menu", "refresh"):
                result = app.handle(Request(command))
                self.assertEqual(result.cache["charge"], before[Record.STATE]["charge"])
                self.assertEqual(profile.records, before)
                self.assertEqual(active_status_icons(result.cache, now=clock.now()), [])
                self.assertFalse(charging_is_current(result.cache, now=clock.now()))
                menu = MenuRenderer(MenuContext(clock.now(), "/example/action")).render(result.cache, result.config)
                self.assertIn("354 km", menu.splitlines()[0])
                self.assertIn("Automatic refresh paused:", menu)
                self.assertIn("Last known", menu)
        factory.assert_not_called()
        self.assertEqual(maps.mock_calls, [])
        self.assertEqual(geocoder.mock_calls, [])

        # No second timer: the first visible xBar invocation fetches immediately.
        desktop.state.return_value = Visibility.VISIBLE
        result = app.handle(Request())
        self.assertNotIn("polling_paused", result.cache)
        self.assertEqual(gateway.calls, ["vehicles", "reading"])
        self.assertEqual(gateway.commands, [])

        # Explicit user commands remain available, even if visibility changes
        # just after clicking. They do not turn automatic polling back on.
        factory.reset_mock()
        desktop.state.return_value = Visibility.LOCKED
        app.handle(Request("command", "door-unlock", "EXAMPLE"))
        self.assertEqual([c.name for c in gateway.commands], ["door-unlock"])


if __name__ == "__main__":
    unittest.main()
