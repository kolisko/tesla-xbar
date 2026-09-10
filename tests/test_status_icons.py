import base64
import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app
from tests.test_tesla_xbar import FakeClient


class StatusClient(FakeClient):
    def __init__(self, sections):
        super().__init__()
        self.sections = sections

    def get(self, path):
        result = super().get(path)
        if "vehicle_data?" in path:
            result["response"].update(self.sections)
        return result


class StatusIconTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = patch.object(app, "APP_DIR", Path(directory.name))
        self.home.start()
        self.addCleanup(self.home.stop)
        self.now = time.time()
        self.config = app.DEFAULTS | {"client_id": "example", "vin": "EXAMPLEVIN"}

    def cache(self, mode="camp", climate=True, locked=False):
        return {"state": "online", "updated_at": self.now,
                "gui_settings": {"gui_distance_units": "km/hr", "gui_range_display": "Rated"},
                "charge": {"battery_level": 73, "battery_range": 360 / 1.609344, "charging_state": "Stopped"},
                "climate": {"climate_keeper_mode": mode, "is_climate_on": climate, "updated_at": self.now},
                "vehicle_status": {"locked": locked, "updated_at": self.now}}

    def test_status_fields_share_battery_request_and_filter_private_response(self):
        client = StatusClient({
            "climate_state": {"climate_keeper_mode": "camp", "is_climate_on": True,
                              "timestamp": (self.now - 5) * 1000, "inside_temp": 22},
            "vehicle_state": {"locked": False, "timestamp": (self.now - 10) * 1000,
                              "odometer": 1000, "vehicle_name": "Private name"}})
        cache = app.fetch_state(self.config, client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(cache["climate"], {"climate_keeper_mode": "camp", "is_climate_on": True, "updated_at": self.now - 5})
        self.assertEqual(cache["vehicle_status"], {"locked": False, "updated_at": self.now - 10})
        for excluded in ("inside_temp", "odometer", "vehicle_name", "latitude"):
            self.assertNotIn(excluded, json.dumps(cache))
        self.assertEqual(app.active_status_icons(cache), ["camp", "fan", "unlocked"])

    def test_modes_and_boolean_fields_have_independent_indicators(self):
        for mode, expected in (("camp", ["camp"]), ("dog", ["pet"]), ("pet", ["pet"]),
                               (" CAMP ", ["camp"]), ("on", []), ("off", []), (None, []), ("unknown", [])):
            with self.subTest(mode=mode):
                self.assertEqual(app.active_status_icons(self.cache(mode, False, True)), expected)
        self.assertEqual(app.active_status_icons(self.cache("dog")), ["pet", "fan", "unlocked"])
        self.assertEqual(app.active_status_icons(self.cache("off")), ["fan", "unlocked"])

    def test_missing_or_malformed_values_do_not_mean_on_or_unlocked(self):
        for value in (None, 0, 1, "true", "false", [], {}):
            with self.subTest(value=value):
                cache = self.cache(value, value, value)
                self.assertEqual(app.active_status_icons(cache), [])
                self.assertEqual(app.status_menu_lines(cache), [])
        cache = self.cache()
        cache["climate"] = {"updated_at": self.now}
        cache["vehicle_status"] = {"updated_at": self.now}
        self.assertEqual(app.active_status_icons(cache), [])

    def test_each_section_uses_its_own_timestamp(self):
        cache = self.cache()
        cache["climate"]["updated_at"] = self.now - app.STALE_AFTER_SECONDS
        with patch.object(app.time, "time", return_value=self.now):
            self.assertEqual(app.active_status_icons(cache), ["unlocked"])
            self.assertIn("Last known climate mode: Camp Mode", app.status_menu_lines(cache))
            cache["vehicle_status"]["updated_at"] = self.now + 1
            self.assertEqual(app.active_status_icons(cache), [])
            cache = self.cache() | {"updated_at": 1}
            self.assertEqual(app.active_status_icons(cache), ["camp", "fan", "unlocked"])

    def test_unavailable_hides_active_icons_but_retains_range_cable_and_details(self):
        for changes in ({"state": "asleep"}, {"state": "offline"}, {"state": "unknown"}, {"error": "Network unavailable"}):
            with self.subTest(changes=changes):
                cache = self.cache() | changes
                menu = app.render(cache, self.config)
                self.assertEqual(menu.splitlines()[0], "360 km | color=#32CD66")
                self.assertIn("Last known climate mode: Camp Mode", menu)
                self.assertIn("Last known climate: on", menu)
                self.assertIn("Last known vehicle lock: unlocked", menu)
                self.assertEqual(app.render(cache, self.config | {"display_mode": "percent"}).splitlines()[0], "73% | color=#32CD66")

    def test_partial_success_replaces_old_active_fields(self):
        for sections in ({}, {"climate_state": None, "vehicle_state": None},
                         {"climate_state": {"is_climate_on": False}, "vehicle_state": {"odometer": 100}}):
            with self.subTest(sections=sections):
                app.save_json("cache.json", self.cache() | {"vin": "EXAMPLEVIN"})
                cache = app.fetch_state(self.config, client=StatusClient(sections))
                self.assertEqual(app.active_status_icons(cache), [])
                self.assertNotIn("climate_keeper_mode", cache["climate"])
                self.assertNotIn("locked", cache["vehicle_status"])

    def test_later_reading_clears_modes_climate_and_unlock(self):
        app.save_json("cache.json", self.cache() | {"vin": "EXAMPLEVIN"})
        cache = app.fetch_state(self.config, client=StatusClient({
            "climate_state": {"climate_keeper_mode": "off", "is_climate_on": False},
            "vehicle_state": {"locked": True}}))
        self.assertEqual(app.active_status_icons(cache), [])
        self.assertIn("Climate: off", app.status_menu_lines(cache))
        self.assertIn("Vehicle: locked", app.status_menu_lines(cache))

    def test_sleep_retains_optional_snapshot_without_live_vehicle_request(self):
        app.save_json("cache.json", self.cache() | {"vin": "EXAMPLEVIN"})
        client = FakeClient("asleep")
        cache = app.fetch_state(self.config, client=client)
        self.assertEqual(client.calls, ["/api/1/vehicles"])
        self.assertEqual(cache["climate"], self.cache()["climate"])
        self.assertEqual(app.active_status_icons(cache), [])

    def test_menu_embeds_image_without_changing_range_or_color(self):
        cache = self.cache()
        title = app.render(cache, self.config).splitlines()[0]
        self.assertTrue(title.startswith("360 km | color=#32CD66 templateImage="))
        self.assertEqual(base64.b64decode(title.split("templateImage=")[1]),
                         (app.HERE / "icons" / "camp-fan-unlocked.png").read_bytes())
        self.assertIn("Climate mode: Camp Mode", app.render(cache, self.config))
        self.assertTrue(app.render(cache, self.config | {"display_mode": "percent"}).startswith("73% |"))
        cache["charge"]["charging_state"] = "Charging"
        self.assertTrue(app.render(cache, self.config).startswith("360 km ⚡ |"))

    def test_all_valid_combinations_are_retina_pngs_at_menu_bar_size(self):
        combinations = []
        for mode in (None, "camp", "pet"):
            for fan in (False, True):
                for unlocked in (False, True):
                    names = [name for name in (mode, "fan" if fan else None, "unlocked" if unlocked else None) if name]
                    if not names:
                        continue
                    combinations.append(names)
                    with self.subTest(names=names):
                        png = base64.b64decode(app.status_icon_image(names))
                        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
                        self.assertEqual(struct.unpack(">II", png[16:24]), ((len(names) * 19 - 3) * 2, 32))
                        offset = 8
                        chunks = {}
                        while offset < len(png):
                            length = struct.unpack(">I", png[offset:offset + 4])[0]
                            chunks[png[offset + 4:offset + 8]] = png[offset + 8:offset + 8 + length]
                            offset += length + 12
                        self.assertEqual(struct.unpack(">IIB", chunks[b"pHYs"]), (5669, 5669, 1))
        self.assertEqual(len(combinations), 11)
        self.assertEqual(app.status_icon_image(["camp", "pet"]), "")

    def test_missing_asset_keeps_textual_status_available(self):
        with patch.object(app, "HERE", app.APP_DIR):
            menu = app.render(self.cache(), self.config)
        self.assertNotIn("templateImage=", menu)
        self.assertIn("Climate mode: Camp Mode", menu)


if __name__ == "__main__":
    unittest.main()
