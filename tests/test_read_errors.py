"""Repeated read failures must never present a saved value as a healthy live state."""
import base64
import copy
import struct
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar.application.accounts import reset_authorized_state
from src.tesla_bar.application.plugin import PluginService
from src.tesla_bar.application.ports import MenuContext, Record, Request, Visibility
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.domain.errors import AppError, Failure, RemoteError
from src.tesla_bar.domain.models import active_status_icons, battery_color, charging_is_current, consecutive_read_errors, read_error_alert
from src.tesla_bar.infrastructure.display import status_icon_bytes
from src.tesla_bar.presentation.menu import MenuRenderer
from tests.test_layers import MemoryProfile, TestClock, MemoryGateway


class ReadErrorTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.clock, self.gateway = MemoryProfile(), TestClock(), MemoryGateway()
        self.location = Mock()
        self.factory = Mock(return_value=self.gateway)
        self.service = VehicleService(self.profile, self.clock, self.factory, self.location)
        self.config = self.profile.config
        self.baseline = self.service.fetch_state(self.config)

    def menu(self, cache, **settings):
        context = MenuContext(self.clock.now(), "/example/action",
                              icon_image=status_icon_bytes(active_status_icons(cache, now=self.clock.now())))
        return MenuRenderer(context).render(cache, self.config | settings)

    def test_third_failed_attempt_hides_value_and_color_but_keeps_saved_details(self):
        for stage in ("vehicles", "reading"):
            self.profile.write(Record.STATE, self.baseline)
            with patch.object(self.gateway, stage, side_effect=RemoteError(Failure.FORBIDDEN, "Tesla denied access.")):
                for count in range(1, 5):
                    self.clock.value += 300
                    cache = self.service.fetch_state(self.config)
                    self.assertEqual(consecutive_read_errors(cache), count)
                    self.assertEqual(cache["charge"], self.baseline["charge"])
                    self.assertEqual(cache["updated_at"], self.baseline["updated_at"])
                    menu = self.menu(cache)
                    top = menu.splitlines()[0]
                    self.assertIn("Battery: 70 %", menu)
                    self.assertIn("Tesla range: 354 km", menu)
                    self.assertIn("Battery reading from", menu)
                    self.assertIn("Last known cable state: connected", menu)
                    self.assertIn(f"Consecutive failed refreshes: {count}", menu)
                    if count < 3:
                        self.assertEqual(top, "354 km | color=#32CD66")
                    else:
                        self.assertTrue(top.startswith("— km | templateImage="))
                        self.assertNotIn("color=", top)
                        self.assertEqual(base64.b64decode(top.split("templateImage=")[1]), status_icon_bytes(["api-error"]))
                        self.assertIn("Last known readings below; current values unavailable.", menu)
                        self.assertNotIn("Green text reflects", menu)
                        self.assertEqual(active_status_icons(cache, now=self.clock.now()), ["api-error"])

    def test_success_breaks_series_and_restores_current_value(self):
        self.gateway.failure = AppError("Network unavailable.")
        for _ in range(3):
            self.service.fetch_state(self.config)
        self.gateway.failure = None
        self.clock.value += 300
        cache = self.service.fetch_state(self.config)
        self.assertEqual(consecutive_read_errors(cache), 0)
        self.assertFalse(read_error_alert(cache))
        self.assertEqual(cache["updated_at"], self.clock.now())
        self.assertNotIn("error", cache)
        self.assertTrue(self.menu(cache).startswith("354 km | color=#32CD66"))
        self.gateway.failure = AppError("Network unavailable.")
        self.assertEqual(consecutive_read_errors(self.service.fetch_state(self.config)), 1)

    def test_sleep_offline_and_unavailable_response_are_not_error_alerts(self):
        for state in ("offline", "asleep", "unknown", "408"):
            self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 3})
            self.gateway.state = state
            self.gateway.failure = RemoteError(Failure.UNAVAILABLE, "Vehicle unavailable.") if state == "408" else None
            self.gateway.calls.clear()
            for _ in range(4):
                cache = self.service.fetch_state(self.config)
                self.assertEqual(consecutive_read_errors(cache), 0)
                self.assertFalse(read_error_alert(cache))
                self.assertEqual(cache["charge"], self.baseline["charge"])
                self.assertEqual(cache["updated_at"], self.baseline["updated_at"])
                self.assertTrue(self.menu(cache).startswith("354 km"))
                self.assertEqual(active_status_icons(cache, now=self.clock.now()), [])
            self.assertNotIn("reading", self.gateway.calls)

    def test_pauses_and_retry_after_do_not_advance_or_clear_failure_series(self):
        for count in (2, 3):
            cache = self.baseline | {"consecutive_read_errors": count, "error": "Try later.",
                                     "retry_reason": Failure.RATE_LIMITED, "retry_at": self.clock.now() + 600}
            self.profile.write(Record.STATE, cache)
            self.factory.reset_mock()
            actual = self.service.fetch_state(self.config)
            self.assertEqual(actual, cache)
            self.factory.assert_not_called()
            desktop = Mock()
            app = PluginService(self.profile, self.clock, Mock(), self.service, Mock(), self.location, desktop)
            for state in Visibility:
                if state == Visibility.VISIBLE:
                    continue
                desktop.state.return_value = state
                paused = app.handle(Request()).cache
                self.assertEqual(consecutive_read_errors(paused), count)
                self.assertEqual(self.profile.read(Record.STATE), cache)
                self.assertEqual(read_error_alert(paused), count >= 3)
            self.factory.assert_not_called()

    def test_rate_limited_attempt_counts_once_before_waiting(self):
        self.gateway.failure = RemoteError(Failure.RATE_LIMITED, "Try later.", retry_after=600)
        for count in (1, 2, 3):
            cache = self.service.fetch_state(self.config)
            self.assertEqual(consecutive_read_errors(cache), count)
            self.assertEqual(consecutive_read_errors(self.service.fetch_state(self.config)), count)
            self.clock.value += 600

    def test_location_fallback_does_not_count_a_recovered_read_as_failed(self):
        self.config["location_enabled"] = True
        reading = self.gateway.reading("EXAMPLE", False, self.clock.now())
        self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 2})
        with patch.object(self.gateway, "reading", side_effect=[RemoteError(Failure.FORBIDDEN, "Location denied."), reading]) as read:
            cache = self.service.fetch_state(self.config)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(consecutive_read_errors(cache), 0)
        with patch.object(self.gateway, "reading", side_effect=RemoteError(Failure.FORBIDDEN, "Access denied.")) as read:
            cache = self.service.fetch_state(self.config)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(consecutive_read_errors(cache), 1)

    def test_consent_does_not_fabricate_a_successful_read(self):
        cache = reset_authorized_state(self.baseline | {"consecutive_read_errors": 3, "error": "Access denied."})
        self.assertTrue(read_error_alert(cache))
        self.assertTrue(self.menu(cache).startswith("— km | templateImage="))
        self.assertEqual(cache["updated_at"], self.baseline["updated_at"])

    def test_neutral_placeholder_respects_units_and_suppresses_all_live_indicators(self):
        for state in ("online", "offline", "asleep"):
            for charging in ("Charging", "Stopped", "Disconnected"):
                cache = copy.deepcopy(self.baseline)
                cache.update(state=state, consecutive_read_errors=3)
                cache["charge"]["charging_state"] = charging
                self.assertIsNone(battery_color(cache))
                self.assertFalse(charging_is_current(cache, now=self.clock.now()))
                for units, mode, expected in (("km/hr", "range", "— km"), ("mi/hr", "range", "— mi"),
                                               (None, "range", "—"), (None, "percent", "—%")):
                    cache["gui_settings"]["gui_distance_units"] = units
                    self.assertTrue(self.menu(cache, display_mode=mode).startswith(expected + " | templateImage="))
        no_reading = {"consecutive_read_errors": 3}
        self.assertTrue(self.menu(no_reading).startswith("— | templateImage="))

    def test_invalid_counter_and_vehicle_selection_do_not_reuse_another_vehicle_warning(self):
        for value in (None, True, False, "3", [], {}, -1, 3.5):
            self.assertEqual(consecutive_read_errors({"consecutive_read_errors": value}), 0)
        self.profile.write(Record.STATE, self.baseline | {"vin": "PREVIOUS", "consecutive_read_errors": 3})
        cache = self.service.fetch_state(self.config)
        self.assertEqual(cache["vin"], "EXAMPLE")
        self.assertEqual(consecutive_read_errors(cache), 0)
        self.assertNotIn("error", cache)
        self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 3})
        with patch.object(self.gateway, "vehicles", return_value=[]):
            cache = self.service.fetch_state(self.config)
        self.assertEqual(consecutive_read_errors(cache), 0)
        self.assertNotIn("charge", cache)

    def test_error_icon_is_a_matching_retina_template_asset(self):
        data = status_icon_bytes(["api-error"])
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", data[16:24]), (32, 32))
        offset = 8
        while offset < len(data):
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            if kind == b"pHYs":
                self.assertEqual(struct.unpack(">IIB", data[offset + 8:offset + 8 + size]), (5669, 5669, 1))
                break
            offset += size + 12
        else:
            self.fail("Retina density is missing")
