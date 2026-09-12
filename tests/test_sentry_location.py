import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app
from src.tesla_bar import api, cli, location, runtime, transport
from tests.test_commands import CommandClient
from tests.test_tesla_xbar import Vault


class FeatureClient(CommandClient):
    def __init__(self, **options):
        super().__init__(**options)
        self.sentry = False
        self.location_allowed = True
        self.location_denied = False
        self.position = {"latitude": 40.7580, "longitude": -73.9855,
                         "timestamp": time.time() * 1000, "active_route_destination": "private"}
        self.status_time = None
        self.apply_changes = True

    def granted_scopes(self):
        return {"vehicle_location"} if self.location_allowed else set()

    def vehicle_command(self, vin, command, capabilities):
        super().vehicle_command(vin, command, capabilities)
        if command.startswith("sentry-") and self.apply_changes:
            self.sentry = command == "sentry-on"

    def get(self, path):
        result = super().get(path)
        if "vehicle_data?" in path:
            if "location_data" in path and self.location_denied:
                raise app.APIError(403)
            result["response"]["vehicle_state"] = {"sentry_mode": self.sentry, "locked": True,
                "timestamp": (time.time() if self.status_time is None else self.status_time) * 1000}
            result["response"]["drive_state"] = self.position
        return result


class FeatureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (("APP_DIR", self.root),):
            mocked = patch.object(runtime, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        for name, options in (("request_json", {"side_effect": AssertionError("No real Tesla requests")}),
                              ("reverse_geocode", {"return_value": "Example Street 1\nExample City"})):
            mocked = patch.object(transport if name == "request_json" else location, name, **options)
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)
        self.config = app.DEFAULTS | {"client_id": "example", "vin": "EXAMPLEVIN"}

    def test_sentry_is_explicit_scoped_and_confirmed(self):
        client = FeatureClient()
        for command in ("sentry-on", "sentry-off"):
            app.run_vehicle_command(self.config, command, client)
            self.assertIn("confirmed by the vehicle", app.read_json("command-result.json")["message"])
        self.assertEqual(client.commands, [("EXAMPLEVIN", "sentry-on"), ("EXAMPLEVIN", "sentry-off")])
        app.fetch_state(self.config, client)
        self.assertEqual(len(client.commands), 2)
        for options in ({"authorized": False}, {"paired": False}):
            client = FeatureClient(state="asleep", **options)
            app.run_vehicle_command(self.config, "sentry-on", client)
            self.assertEqual(client.commands, [])
            self.assertEqual(client.wakes, [])

    def test_sentry_unconfirmed_and_failures_do_not_retry(self):
        for setup in ({"apply_changes": False}, {"sentry": True, "status_time": time.time() - 100}):
            client = FeatureClient()
            for field, value in setup.items():
                setattr(client, field, value)
            app.run_vehicle_command(self.config, "sentry-on", client)
            self.assertEqual(app.read_json("command-result.json")["message"], "Command accepted: Turn Sentry on")
        client = FeatureClient(error=app.AppError("Unconfirmed"))
        app.run_vehicle_command(self.config, "sentry-on", client)
        self.assertEqual(len(client.commands), 1)
        self.assertEqual(app.read_json("command-result.json")["status"], "error")

    def test_sentry_command_mapping_for_signed_and_legacy_vehicles(self):
        for name in ("tesla-control", "command-key.pem"):
            (self.root / name).touch()
        client = app.Client(self.config, Vault({"access_token": "private-token", "expires_at": time.time() + 3600}))
        for command, enabled in (("sentry-on", True), ("sentry-off", False)):
            with patch.object(runtime, "HERE", self.root), patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                client.vehicle_command("EXAMPLEVIN", command, {"signing_required": True, "key_paired": True})
            self.assertEqual(run.call_args.args[0][-2:], ["sentry-mode", "on" if enabled else "off"])
            self.assertNotIn("private-token", str(run.call_args.args))
            with patch.object(client, "request", return_value={"response": {"result": True}}) as request:
                client.vehicle_command("EXAMPLEVIN", command, {"signing_required": False})
            self.assertTrue(request.call_args.args[0].endswith("/set_sentry_mode"))
            self.assertEqual(request.call_args.kwargs, {"body": {"on": enabled}})
        self.assertIn("Vehicle Commands", app.command_error("403", "sentry-on"))

    def test_sentry_icon_and_submenu_cli_use_fresh_boolean_and_pinned_vin(self):
        client = FeatureClient()
        client.sentry = True
        cache = app.fetch_state(self.config, client)
        self.assertIn("sentry", app.active_status_icons(cache))
        menu = app.render(cache, self.config)
        self.assertNotIn("Turn Sentry", menu.split("\nClima\n")[0])
        line = next(line for line in menu.splitlines() if line.startswith("--Turn Sentry off |"))
        params = dict(part.split("=", 1) for part in shlex.split(line.split(" | ")[1]))
        args = [params[f"param{i}"] for i in range(1, 5)]
        self.assertEqual(args, ["command", "sentry-off", "--vin", "EXAMPLEVIN"])
        app.save_json("config.json", self.config)
        with patch.object(api, "Client", return_value=client), patch("sys.argv", ["plugin"] + args), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertFalse(client.sentry)
        for value in (False, None, "true", 1):
            cache["vehicle_status"]["sentry_mode"] = value
            self.assertNotIn("sentry", app.active_status_icons(cache))
        cache["vehicle_status"]["sentry_mode"] = True
        cache["state"] = "asleep"
        self.assertNotIn("sentry", app.active_status_icons(cache))
        self.assertIn("Last known Sentry: on", app.render(cache, self.config))

    def test_location_opt_in_and_scope_are_both_required(self):
        client = FeatureClient()
        cache = app.fetch_state(self.config, client)
        self.assertNotIn("location", cache)
        self.assertNotIn("location_data", " ".join(client.calls))
        self.reverse_geocode.assert_not_called()
        client.location_allowed = False
        cache = app.fetch_state(self.config | {"location_enabled": True}, client)
        self.assertNotIn("location", cache)
        self.assertIn("Vehicle Location", cache["location_error"])
        self.assertIn("charge", cache)
        self.reverse_geocode.assert_not_called()

    def test_location_uses_shared_request_and_caches_only_coordinates_address_time(self):
        client = FeatureClient()
        config = self.config | {"location_enabled": True}
        cache = app.fetch_state(config, client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("location_data", client.calls[-1])
        self.assertNotIn("active_route_destination", json.dumps(cache))
        self.assertEqual(cache["location"]["address"], "Example Street 1\nExample City")
        menu = app.render(cache, config)
        self.assertIn("\nLocation\n", menu)
        self.assertIn("--Example Street 1 | color=gray", menu)
        self.assertIn("ll=40.758000%2C-73.985500", menu)
        app.fetch_state(config, client)
        self.reverse_geocode.assert_called_once()
        client.state = "asleep"
        cache = app.fetch_state(config, client)
        self.assertIn("Open last known position", app.render(cache, config))
        self.assertEqual(client.wakes, [])

    def test_new_consent_clears_old_error_while_vehicle_is_offline(self):
        config = self.config | {"location_enabled": True}
        client = FeatureClient(state="offline")
        client.location_allowed = False
        cache = app.fetch_state(config, client)
        self.assertIn("Vehicle Location", cache["location_error"])
        client.location_allowed = True
        cache = app.fetch_state(config, client)
        self.assertNotIn("location_error", cache)
        self.assertNotIn("location", cache)
        self.assertIn("Location is not available yet", app.render(cache, config))
        self.assertEqual(client.wakes, [])

    def test_moved_missing_or_old_location_never_shows_wrong_address(self):
        now = time.time()
        cache = {}
        response = {"drive_state": {"latitude": 40.0, "longitude": -73.0, "timestamp": now * 1000}}
        app.update_location(cache, response, now)
        response["drive_state"]["latitude"] = 41.0
        response["drive_state"]["timestamp"] += 1000
        app.update_location(cache, response, now + 1)
        self.assertNotIn("address", cache["location"])
        self.reverse_geocode.assert_called_once()
        previous = cache["location"].copy()
        for fields in ({}, {"latitude": 999, "longitude": 0}, {"latitude": 42, "longitude": 0},
                       {"latitude": 42, "longitude": 0, "timestamp": (now - 20) * 1000}):
            app.update_location(cache, {"drive_state": fields}, now + 2)
            self.assertEqual(cache["location"], previous)
            self.assertIn("location_error", cache)

    def test_revoked_location_retries_only_read_without_location_and_keeps_battery(self):
        client = FeatureClient()
        config = self.config | {"location_enabled": True}
        app.fetch_state(config, client)
        client.location_denied = True
        client.calls = []
        cache = app.fetch_state(config, client)
        self.assertEqual(len(client.calls), 3)
        self.assertNotIn("location_data", client.calls[-1])
        self.assertNotIn("location", cache)
        self.assertNotIn("error", cache)
        self.assertIn("charge", cache)

    def test_geocoder_errors_are_contained_and_input_never_goes_in_argv(self):
        # Call the real wrapper with a mocked subprocess, not Apple's service.
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"address":"Example"}')) as run:
            module = app  # Original callable; the location module dependency is mocked separately.
            self.assertEqual(module.reverse_geocode((40, -73)), "Example")
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"latitude": 40, "longitude": -73})
            self.assertNotIn("40", str(run.call_args.args))
            run.return_value = subprocess.CompletedProcess([], 0, "not-json")
            self.assertIsNone(module.reverse_geocode((40, -73)))
            run.side_effect = subprocess.TimeoutExpired("helper", 9)
            self.assertIsNone(module.reverse_geocode((40, -73)))

    def test_location_enable_persists_opt_in_before_authorization(self):
        app.save_json("config.json", self.config)
        with patch.object(cli, "authorize") as authorize, patch("sys.argv", ["plugin", "location-enable", "--no-browser"]), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertTrue(authorize.call_args.args[0]["location_enabled"])
        self.assertEqual(authorize.call_args.kwargs, {"launch": False})
        self.assertTrue(app.configuration()["location_enabled"])

    def test_vehicle_change_removes_old_location_even_if_new_vehicle_is_asleep(self):
        config = self.config | {"location_enabled": True}
        app.fetch_state(config, FeatureClient())
        old = app.read_json("cache.json")
        old["vin"] = "OLDVIN"
        app.save_json("cache.json", old)
        cache = app.fetch_state(config, FeatureClient(state="asleep"))
        self.assertNotIn("location", cache)

    def test_disabling_location_removes_private_snapshot_and_display(self):
        config = self.config | {"location_enabled": True}
        app.save_json("config.json", config)
        app.fetch_state(config, FeatureClient())
        with patch("sys.argv", ["plugin", "location-disable"]):
            self.assertEqual(app.main(), 0)
        self.assertNotIn("location", app.read_json("cache.json"))
        self.assertNotIn("Example Street", (self.root / "display.txt").read_text())
        self.assertFalse(app.configuration()["location_enabled"])


if __name__ == "__main__":
    unittest.main()
