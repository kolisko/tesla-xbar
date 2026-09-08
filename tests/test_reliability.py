import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app
from tests.test_commands import CommandClient
from tests.test_tesla_xbar import FakeClient, WakeClient


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = patch.object(app, "APP_DIR", Path(self.temp.name))
        self.home.start()
        self.addCleanup(self.home.stop)
        network = patch.object(app, "request_json", side_effect=AssertionError("Tests must never call Tesla"))
        network.start()
        self.addCleanup(network.stop)
        self.config = app.DEFAULTS | {"client_id": "example"}
        app.save_json("config.json", self.config)

    def seed(self, vin="EXAMPLEVIN"):
        return app.fetch_state(self.config, client=FakeClient(vin=vin))

    def main(self, args, client=None):
        with patch("sys.argv", ["plugin"] + args), patch("sys.stdout", new_callable=io.StringIO) as output:
            with patch.object(app, "Client", return_value=client) as factory:
                result = app.main()
        return result, output.getvalue(), factory

    def test_connection_icons_survive_missing_range_and_missing_battery(self):
        baseline = self.seed()
        for state, symbol in (("asleep", "☾"), ("offline", "⛓️‍💥")):
            for charge, gui in ((baseline["charge"], baseline["gui_settings"]),
                                (baseline["charge"], {}), ({}, {})):
                cache = baseline | {"state": state, "charge": charge, "gui_settings": gui}
                top = app.render(cache, self.config).splitlines()[0]
                self.assertIn(symbol, top)
                self.assertNotIn("⚡", top)
                self.assertNotIn("☾" if state == "offline" else "⛓️‍💥", top)
        self.assertIn("— ☾", app.render({"state": "asleep"}, self.config))
        self.assertIn("— ⛓️‍💥", app.render({"state": "offline"}, self.config))
        self.assertIn("⚡", app.render(baseline, self.config).splitlines()[0])

    def test_408_is_unavailable_and_only_successful_list_verifies_vehicle(self):
        baseline = self.seed()
        for phase in ("list", "data"):
            app.save_json("cache.json", baseline)
            client = FakeClient()
            original = client.get
            def get(path):
                if phase == "list" or "vehicle_data?" in path:
                    raise app.APIError(408)
                return original(path)
            with patch.object(client, "get", side_effect=get):
                cache = app.fetch_state(self.config, client=client)
            self.assertEqual(cache["state"], "offline")
            self.assertEqual(cache["vehicle_verified"], phase == "data")
            self.assertEqual(cache["charge"], baseline["charge"])
            self.assertEqual(cache["updated_at"], baseline["updated_at"])
            self.assertNotIn("☾", app.render(cache, self.config).splitlines()[0])

    def test_offline_and_sleep_preserve_old_range_percent_and_original_timestamp(self):
        baseline = self.seed()
        baseline["updated_at"] = time.time() - 86400
        for state, icon in (("offline", "⛓️‍💥"), ("asleep", "☾")):
            app.save_json("cache.json", baseline)
            client = FakeClient(state=state)
            cache = app.fetch_state(self.config, client=client)
            self.assertEqual(cache["updated_at"], baseline["updated_at"])
            self.assertEqual(cache["charge"], baseline["charge"])
            self.assertEqual(cache["gui_settings"], baseline["gui_settings"])
            self.assertEqual(client.calls, ["/api/1/vehicles"])
            for mode, value in (("range", "161 km"), ("percent", "72%")):
                menu = app.render(cache, self.config | {"display_mode": mode})
                self.assertTrue(menu.startswith(f"{value} {icon} ·"))
                self.assertIn("Battery reading from", menu)

    def test_list_timeout_never_wakes_or_commands_a_cached_vehicle(self):
        self.seed()
        client = CommandClient()
        with patch.object(client, "get", side_effect=app.APIError(408)), patch.object(client, "command_capabilities") as capabilities:
            app.wake_and_refresh(self.config, client=client)
            app.run_vehicle_command(self.config, "charge-start", client=client)
        self.assertEqual(client.wakes, [])
        self.assertEqual(client.commands, [])
        capabilities.assert_not_called()

    def test_429_uses_exact_server_delay_and_retries_at_deadline(self):
        client = FakeClient()
        with patch.object(app.time, "time", return_value=1000), patch.object(client, "get", side_effect=app.APIError(429, 60)):
            cache = app.fetch_state(self.config, client=client)
        self.assertEqual(cache["retry_at"], 1060)
        with patch.object(app.time, "time", return_value=1059):
            app.fetch_state(self.config, client=client)
        self.assertEqual(client.calls, [])
        with patch.object(app.time, "time", return_value=1060):
            cache = app.fetch_state(self.config, client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn("retry_at", cache)

    def test_429_without_delay_does_not_introduce_its_own_timer(self):
        client = FakeClient()
        with patch.object(client, "get", side_effect=app.APIError(429)):
            app.fetch_state(self.config, client=client)
        cache = app.fetch_state(self.config, client=client)
        self.assertEqual(len(client.calls), 2)
        self.assertNotIn("error", cache)

    def test_retry_after_accepts_seconds_and_http_date(self):
        self.assertEqual(app.retry_after_seconds("60"), 60)
        for value in ("", "garbage", "-20"):
            self.assertEqual(app.retry_after_seconds(value), 0)
        with patch.object(app.time, "time", return_value=0):
            self.assertEqual(app.retry_after_seconds("Thu, 01 Jan 1970 00:01:00 GMT"), 60)

    def test_wake_429_has_no_fifteen_minute_minimum(self):
        self.seed()
        client = WakeClient(error=app.APIError(429, 60))
        with patch.object(app.time, "time", return_value=1000):
            cache = app.wake_and_refresh(self.config, client=client)
        self.assertEqual(cache["retry_at"], 1060)
        self.assertEqual(len(client.wakes), 1)

    def test_busy_manual_actions_exit_without_queue_and_leave_visible_notice(self):
        self.seed()
        cache_before = (app.APP_DIR / "cache.json").read_bytes()
        pending = {"vin": "EXAMPLEVIN", "status": "pending", "at": time.time(), "message": "Command in progress"}
        app.save_json("command-result.json", pending)
        original_flock = app.fcntl.flock
        def nonblocking_only(fd, operation):
            if operation != app.fcntl.LOCK_UN:
                self.assertTrue(operation & app.fcntl.LOCK_NB, "Manual action must never queue")
            return original_flock(fd, operation)
        with app.locked():
            with patch.object(app.fcntl, "flock", side_effect=nonblocking_only):
                for args in (["command", "charge-start"], ["wake-refresh"], ["command-setup"]):
                    code, output, factory = self.main(args + ["--vin", "EXAMPLEVIN"])
                    self.assertEqual(code, 0)
                    self.assertIn("Action not performed", output)
                    factory.assert_not_called()
        self.assertEqual((app.APP_DIR / "cache.json").read_bytes(), cache_before)
        self.assertEqual(app.read_json("command-result.json"), pending)
        _, output, _ = self.main(["menu"], FakeClient())
        self.assertIn("Action not performed", output)

    def test_successful_manual_action_clears_previous_busy_notice(self):
        self.seed()
        app.save_json("action-notice.json", {"message": "Action not performed"})
        client = CommandClient()
        _, output, _ = self.main(["command", "charge-start", "--vin", "EXAMPLEVIN"], client)
        self.assertEqual(client.commands, [("EXAMPLEVIN", "charge-start")])
        self.assertNotIn("Action not performed", output)
        self.assertFalse((app.APP_DIR / "action-notice.json").exists())

    def test_menu_binds_commands_and_wake_to_displayed_vin(self):
        menu = app.render(self.seed(), self.config)
        for label in ("Start charging", "Stop charging", "Open charge port", "Close charge port", "Wake vehicle and refresh"):
            line = next(line for line in menu.splitlines() if label in line)
            self.assertIn('"--vin"', line)
            self.assertIn('"EXAMPLEVIN"', line)
        empty = app.render({}, self.config)
        line = next(line for line in empty.splitlines() if "Wake vehicle and refresh" in line)
        self.assertNotIn("shell=", line)

    def test_stale_or_old_menu_never_sends_a_command(self):
        self.seed()
        client = CommandClient()
        for args in (["command", "charge-start"], ["wake-refresh"],
                     ["command", "charge-start", "--vin", "PREVIOUSVIN"],
                     ["wake-refresh", "--vin", "PREVIOUSVIN"]):
            _, output, factory = self.main(args, client)
            self.assertTrue("Refresh the menu" in output)
            factory.assert_not_called()
        self.assertEqual(client.commands, [])
        self.assertEqual(client.wakes, [])

    def test_vehicle_list_reorder_preserves_displayed_and_commanded_vehicle(self):
        self.seed()
        client = CommandClient()
        original = client.get
        def reordered(path):
            response = original(path)
            if path == "/api/1/vehicles":
                response["response"].insert(0, {"vin": "OTHER_VIN", "state": "online"})
            return response
        with patch.object(client, "get", side_effect=reordered):
            cache = app.fetch_state(self.config, client=client)
            app.run_vehicle_command(self.config, "charge-start", client=client)
        self.assertEqual(cache["vin"], "EXAMPLEVIN")
        self.assertEqual(client.commands, [("EXAMPLEVIN", "charge-start")])

    def test_removed_vehicle_does_not_switch_on_later_refresh_or_command(self):
        self.seed()
        client = CommandClient()
        client.vin = "NEW_VIN"
        for _ in range(2):
            cache = app.fetch_state(self.config, client=client)
            self.assertNotIn("vin", cache)
            self.assertNotIn("charge", cache)
        app.run_vehicle_command(self.config, "charge-start", client=client)
        self.assertEqual(client.commands, [])
        self.assertEqual(client.wakes, [])

    def test_multiple_cars_on_first_run_require_selection(self):
        client = FakeClient()
        with patch.object(client, "get", return_value={"response": [{"vin": "A"}, {"vin": "B"}]}):
            cache = app.fetch_state(self.config, client=client)
        self.assertNotIn("vin", cache)
        self.assertIn("Select a vehicle", cache["error"])
        self.assertIn("Select vehicle", app.render(cache, self.config))


if __name__ == "__main__":
    unittest.main()
