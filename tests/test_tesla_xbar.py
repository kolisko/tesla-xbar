import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app


class Vault:
    def __init__(self, tokens):
        self.values = {"oauth": json.dumps(tokens)}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


class FakeClient:
    def __init__(self, state="online", level=72, vin="EXAMPLEVIN"):
        self.calls = []
        self.state, self.level, self.vin = state, level, vin

    def get(self, path):
        self.calls.append(path)
        if path == "/api/1/vehicles":
            return {"response": [{"vin": self.vin, "state": self.state, "display_name": "My Tesla"}]}
        return {"response": {"charge_state": {"battery_level": self.level,
            "charging_state": "Charging", "battery_range": 100,
            "ideal_battery_range": 120, "timestamp": time.time() * 1000},
            "gui_settings": {"gui_distance_units": "km/hr", "gui_range_display": "Rated", "unrelated": "omit"},
            "drive_state": {"latitude": 50}}}


class WakeClient(FakeClient):
    def __init__(self, ready=True, error=None):
        super().__init__(state="asleep")
        self.ready, self.error, self.wakes = ready, error, []

    def wake(self, vin):
        self.wakes.append(vin)
        if self.error:
            raise self.error
        return {"response": {"state": "asleep"}}

    def get(self, path):
        if path == "/api/1/vehicles/" + self.vin:
            self.calls.append(path)
            self.state = "online" if self.ready else "asleep"
            return {"response": {"state": self.state}}
        return super().get(path)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = patch.object(app, "APP_DIR", Path(self.temp.name))
        self.home.start()
        self.config = app.DEFAULTS | {"client_id": "example", "vin": "EXAMPLEVIN"}

    def tearDown(self):
        self.home.stop()
        self.temp.cleanup()

    def test_sleep_keeps_battery_and_does_not_query_car(self):
        app.save_json("cache.json", {"vin": "EXAMPLEVIN", "charge": {"battery_level": 42}, "updated_at": 10})
        client = FakeClient("asleep")
        result = app.fetch_state(self.config, client=client)
        self.assertEqual(result["charge"]["battery_level"], 42)
        self.assertEqual(result["updated_at"], 10)
        self.assertEqual(client.calls, ["/api/1/vehicles"])
        self.assertEqual(app.render(result, self.config | {"display_mode": "percent"}).splitlines()[0],
                         "42% | color=#A0A6AD")

    def test_online_fetches_charge_and_display_preferences_once(self):
        client = FakeClient()
        result = app.fetch_state(self.config, client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(client.calls[1].endswith("?endpoints=charge_state%3Bgui_settings"))
        self.assertEqual(result["charge"]["battery_level"], 72)
        self.assertEqual(result["gui_settings"], {"gui_distance_units": "km/hr", "gui_range_display": "Rated"})
        self.assertNotIn("latitude", json.dumps(result))

    def test_network_error_preserves_last_good_reading(self):
        app.save_json("cache.json", {"vin": "EXAMPLEVIN", "charge": {"battery_level": 80}, "updated_at": 100})
        client = FakeClient()
        with patch.object(client, "get", side_effect=app.AppError("Offline")):
            result = app.fetch_state(self.config, client=client)
        self.assertEqual(result["charge"]["battery_level"], 80)
        self.assertEqual(result["updated_at"], 100)
        self.assertEqual(app.render(result, self.config | {"display_mode": "percent"}).splitlines()[0],
                         "80% | color=#A0A6AD")

    def test_rotation_saved_before_next_use(self):
        vault = Vault({"access_token": "old", "refresh_token": "refresh-old", "expires_at": 0})
        client = app.Client(self.config, vault)
        with patch.object(app, "request_json", return_value={"access_token": "new", "refresh_token": "refresh-new", "expires_in": 3600}) as http:
            self.assertEqual(client.access_token(), "new")
            self.assertEqual(client.access_token(), "new")
        self.assertEqual(http.call_count, 1)
        self.assertEqual(json.loads(vault.get("oauth"))["refresh_token"], "refresh-new")

    def test_every_run_fetches_despite_old_poll_setting_and_future_cache_timer(self):
        client = WakeClient()
        client.state = "online"
        config = self.config | {"poll_minutes": 20}
        app.save_json("config.json", config)
        first = app.fetch_state(config, client=client)
        app.save_json("cache.json", first | {"next_poll": time.time() + 1200})
        client.level = 71
        for command in ("menu", "refresh"):
            with patch.object(app, "Client", return_value=client), patch("sys.argv", ["tesla_xbar.py", command]), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(app.main(), 0)
            fresh = app.read_json("cache.json")
            self.assertEqual(fresh["charge"]["battery_level"], client.level)
            self.assertNotIn("next_poll", fresh)
            client.level -= 1
        self.assertEqual(len(client.calls), 6)
        self.assertEqual(client.wakes, [])
        self.assertNotIn("poll_minutes", app.configuration())
        self.assertIn("Refresh now | refresh=true", app.render(fresh, config).splitlines())

    def test_next_run_retries_network_or_sleep_error_without_local_delay(self):
        for error in (app.AppError("Offline"), app.APIError(408)):
            with self.subTest(error=str(error)):
                client = FakeClient()
                with patch.object(client, "get", side_effect=error):
                    app.fetch_state(self.config, client=client)
                fresh = app.fetch_state(self.config, client=client)
                self.assertEqual(fresh["charge"]["battery_level"], 72)
                self.assertNotIn("error", fresh)
                self.assertEqual(len(client.calls), 2)

    def test_401_refreshes_once(self):
        vault = Vault({"access_token": "old", "refresh_token": "refresh-old", "expires_at": time.time() + 3600})
        client = app.Client(self.config, vault)
        responses = [app.APIError(401), {"access_token": "new", "refresh_token": "refresh-new"}, {"response": []}]
        with patch.object(app, "request_json", side_effect=responses) as http:
            self.assertEqual(client.get("/api/1/vehicles"), {"response": []})
        self.assertEqual(http.call_count, 3)

    def test_rate_limit_honored_even_manual_refresh(self):
        client = FakeClient()
        with patch.object(client, "get", side_effect=app.APIError(429, 7200)) as http:
            result = app.fetch_state(self.config, client=client)
            app.fetch_state(self.config, client=client)
        self.assertEqual(http.call_count, 1)
        self.assertGreater(result["retry_at"], time.time() + 7100)

    def test_new_vehicle_never_inherits_old_battery(self):
        app.save_json("cache.json", {"vin": "OLD", "charge": {"battery_level": 99}, "updated_at": 100})
        result = app.fetch_state(self.config | {"vin": "NEW"}, client=FakeClient("asleep", vin="NEW"))
        self.assertNotIn("charge", result)

    def test_revoked_selected_vehicle_does_not_silently_switch(self):
        result = app.fetch_state(self.config | {"vin": "missing"}, client=FakeClient())
        self.assertIn("error", result)
        self.assertNotIn("charge", result)

    def test_invalid_battery_is_not_published_as_fresh(self):
        result = app.fetch_state(self.config, client=FakeClient(level=None))
        self.assertNotIn("updated_at", result)
        self.assertIn("error", result)

    def test_zero_is_valid(self):
        result = app.fetch_state(self.config, client=FakeClient(level=0))
        self.assertIn("0%", app.render(result, self.config | {"display_mode": "percent"}))

    def test_range_uses_tesla_value_and_vehicle_units_independent_of_percent(self):
        cache = app.fetch_state(self.config, client=FakeClient(level=54))
        self.assertTrue(app.render(cache, self.config).startswith("161 km"))
        cache["charge"]["battery_level"] = 90
        self.assertTrue(app.render(cache, self.config).startswith("161 km"))
        cache["gui_settings"]["gui_distance_units"] = "mi/hr"
        cache["gui_settings"]["gui_range_display"] = "Ideal"
        self.assertTrue(app.render(cache, self.config).startswith("120 mi"))

    def test_missing_range_or_units_does_not_substitute_percent_or_estimate(self):
        cache = app.fetch_state(self.config, client=FakeClient())
        cache["charge"].pop("battery_range")
        self.assertEqual(app.render(cache, self.config).splitlines()[0].split(" |")[0], "— ⚡")
        cache["charge"]["battery_range"] = 0
        self.assertTrue(app.render(cache, self.config).startswith("0 km"))
        cache["gui_settings"].pop("gui_distance_units")
        self.assertEqual(app.render(cache, self.config).splitlines()[0].split(" |")[0], "— ⚡")

    def test_sleep_keeps_range_and_preferences(self):
        app.fetch_state(self.config, client=FakeClient())
        cache = app.fetch_state(self.config, client=FakeClient("asleep"))
        self.assertEqual(app.render(cache, self.config).splitlines()[0], "161 km | color=#32CD66")

    def test_remote_menu_injection_removed(self):
        value = app.safe_text("---evil\nOpen | shell=/bin/sh\nparam1=bad")
        self.assertNotIn("|", value)
        self.assertNotIn("\n", value)
        self.assertFalse(value.startswith("--"))

    def test_old_charging_reading_has_no_live_lightning(self):
        cache = {"state": "online", "updated_at": 1, "charge": {"battery_level": 80, "charging_state": "Charging"}}
        self.assertNotIn("⚡", app.render(cache, self.config).splitlines()[0])

    def test_obsolete_local_limit_does_not_block_requests(self):
        vault = Vault({"access_token": "token", "expires_at": time.time() + 3600})
        client = app.Client(self.config | {"monthly_request_limit": 1}, vault)
        app.save_json("usage.json", {"requests": 4000})
        with patch.object(app, "request_json", return_value={"response": []}) as http:
            client.get("/api/1/vehicles")
        http.assert_called_once()
        self.assertNotIn("4000", app.render({}, self.config))
        self.assertNotIn("requests", app.render({}, self.config))
        self.assertNotIn("billing", app.render({}, self.config))

    def test_runtime_files_private(self):
        app.save_json("cache.json", {"charge": {"battery_level": 10}})
        self.assertEqual((app.APP_DIR / "cache.json").stat().st_mode & 0o777, 0o600)

    def test_manual_wake_once_then_wait_for_online_and_read(self):
        client = WakeClient()
        with patch.object(app.time, "sleep"):
            cache = app.wake_and_refresh(self.config, client=client)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])
        self.assertEqual(cache["state"], "online")
        self.assertEqual(cache["charge"]["battery_level"], 72)
        self.assertNotIn("wake_in_progress", cache)
        self.assertEqual(sum("vehicle_data?" in path for path in client.calls), 1)

    def test_automatic_and_normal_manual_refresh_never_wake(self):
        client = WakeClient()
        app.fetch_state(self.config, client=client)
        app.fetch_state(self.config, client=client)
        self.assertEqual(client.wakes, [])
        client.state = "online"
        app.wake_and_refresh(self.config, client=client)
        self.assertEqual(client.wakes, [])

    def test_wake_timeout_keeps_last_range_and_does_not_repeat_wake(self):
        app.fetch_state(self.config, client=FakeClient())
        client = WakeClient(ready=False)
        cache = app.wake_and_refresh(self.config, client=client, timeout=0)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])
        self.assertEqual(cache["charge"]["battery_range"], 100)
        self.assertIn("did not connect", cache["error"])
        self.assertNotIn("wake_in_progress", app.read_json("cache.json"))
        self.assertFalse(any("vehicle_data?" in path for path in client.calls))

    def test_wake_permission_error_explains_new_consent(self):
        client = WakeClient(error=app.APIError(403))
        cache = app.wake_and_refresh(self.config, client=client)
        self.assertIn("Vehicle Commands", cache["error"])
        self.assertNotIn("wake_in_progress", cache)

    def test_wake_respects_tesla_cooldown(self):
        client = WakeClient(error=app.APIError(429, 3600))
        app.wake_and_refresh(self.config, client=client)
        calls = len(client.calls)
        app.wake_and_refresh(self.config, client=client)
        self.assertEqual(len(client.calls), calls)
        self.assertEqual(len(client.wakes), 1)

    def test_wake_can_follow_previous_sleep_timeout(self):
        app.save_json("cache.json", {"vin": "EXAMPLEVIN", "state": "asleep", "retry_status": 408,
                                    "error": "Vehicle asleep", "retry_at": time.time() + 1200})
        client = WakeClient()
        with patch.object(app.time, "sleep"):
            cache = app.wake_and_refresh(self.config, client=client)
        self.assertNotIn("error", cache)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])

    def test_wake_never_targets_a_revoked_vehicle(self):
        client = WakeClient()
        cache = app.wake_and_refresh(self.config | {"vin": "missing"}, client=client)
        self.assertEqual(client.wakes, [])
        self.assertIn("error", cache)

    def test_wake_post_does_not_retry_uncertain_network_result(self):
        vault = Vault({"access_token": "token", "expires_at": time.time() + 3600})
        client = app.Client(self.config, vault)
        with patch.object(app, "request_json", side_effect=app.AppError("Network unavailable")) as http:
            with self.assertRaises(app.AppError):
                client.wake("EXAMPLEVIN")
        http.assert_called_once_with(app.REGIONS["eu"] + "/api/1/vehicles/EXAMPLEVIN/wake_up", token="token", body={})

    def test_disconnected_color_thresholds_use_displayed_kilometers(self):
        for km, expected in ((400, None), (350, None), (349, "#F5A623"), (300, "#F5A623"), (299, "#EF4444")):
            cache = {"gui_settings": {"gui_range_display": "Rated"},
                     "charge": {"charging_state": "Disconnected", "battery_range": km / 1.609344}}
            with self.subTest(km=km):
                self.assertEqual(app.battery_color(cache), expected)

    def test_connected_cable_has_priority_even_without_charging(self):
        cache = app.fetch_state(self.config, client=FakeClient())
        for state in ("Stopped", "Complete", "NoPower"):
            cache["charge"]["charging_state"] = state
            with self.subTest(state=state):
                self.assertEqual(app.battery_color(cache), "#32CD66")
                self.assertFalse(app.charging_is_current(cache, self.config))
                self.assertNotIn("⚡", app.render(cache, self.config).splitlines()[0])

    def test_only_fresh_online_charging_pulses(self):
        cache = app.fetch_state(self.config, client=FakeClient())
        self.assertTrue(app.charging_is_current(cache, self.config))
        for changes in ({"state": "asleep"}, {"updated_at": 1}, {"error": "Offline"}):
            self.assertFalse(app.charging_is_current(cache | changes, self.config))

    def test_unknown_cable_is_not_invented_from_open_charge_port(self):
        self.assertIsNone(app.cable_connected({"conn_charge_cable": "<invalid>", "charge_port_door_open": True}))
        self.assertFalse(app.cable_connected({"charging_state": "Disconnected", "conn_charge_cable": "IEC"}))

    def test_published_display_is_private_and_contains_no_full_vehicle_data(self):
        cache = app.fetch_state(self.config, client=FakeClient())
        app.publish_display(cache, self.config, app.render(cache, self.config))
        display = app.APP_DIR / "display.txt"
        self.assertEqual(display.stat().st_mode & 0o777, 0o600)
        self.assertTrue(display.read_text().startswith("TESLA_XBAR_DISPLAY_V1 "))
        self.assertNotIn("latitude", display.read_text())

    def test_scope_upgrade_keeps_last_reading_while_vehicle_is_offline(self):
        old = app.fetch_state(self.config, client=FakeClient())
        app.reset_after_authorization()
        client = FakeClient("offline")
        cache = app.fetch_state(self.config, client=client)
        self.assertEqual(cache["charge"], old["charge"])
        self.assertEqual(cache["updated_at"], old["updated_at"])
        self.assertEqual(cache["gui_settings"], old["gui_settings"])
        self.assertEqual(client.calls, ["/api/1/vehicles"])
        self.assertTrue(app.render(cache, self.config).startswith("161 km"))


if __name__ == "__main__":
    unittest.main()
