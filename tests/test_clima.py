import io
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app
from tests.test_commands import CommandClient
from tests.test_tesla_xbar import Vault


class ClimateClient(CommandClient):
    def __init__(self, mode="off", power=False, **options):
        super().__init__(**options)
        self.mode, self.power = mode, power
        self.temperature, self.limits = 21.0, (15.0, 28.0)
        self.apply_changes = True
        self.fail_command = None
        self.timestamp = None

    def vehicle_command(self, vin, command, capabilities, temperature=None):
        self.commands.append((vin, command, temperature))
        if command == self.fail_command:
            raise app.AppError("The command result is unconfirmed; it will not be retried.")
        if not self.apply_changes:
            return
        if command in app.CLIMATE_MODES:
            self.mode = app.CLIMATE_MODES[command][0]
            if self.mode != "off":
                self.power = True
        elif command in ("climate-on", "climate-off"):
            self.power = command == "climate-on"
        elif command == "climate-set-temp":
            self.temperature = temperature

    def get(self, path):
        result = super().get(path)
        if "vehicle_data?" in path:
            climate = {"climate_keeper_mode": self.mode, "is_climate_on": self.power,
                       "driver_temp_setting": self.temperature, "passenger_temp_setting": self.temperature,
                       "inside_temp": 20.5, "outside_temp": -3.5,
                       "timestamp": (self.timestamp if self.timestamp is not None else time.time()) * 1000}
            if self.limits is not None:
                climate.update(min_avail_temp=self.limits[0], max_avail_temp=self.limits[1])
            result["response"]["climate_state"] = climate
        return result


class ClimaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (("APP_DIR", self.root), ("HERE", self.root)):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        network = patch.object(app, "request_json", side_effect=AssertionError("Real API access is forbidden in tests"))
        network.start()
        self.addCleanup(network.stop)
        self.config = app.DEFAULTS | {"client_id": "example", "vin": "EXAMPLEVIN"}

    def test_modes_are_explicit_and_confirmed_by_new_reading(self):
        for command, (mode, _) in app.CLIMATE_MODES.items():
            with self.subTest(command=command):
                client = ClimateClient(mode="camp", power=True)
                app.run_vehicle_command(self.config, command, client)
                self.assertEqual(client.commands, [("EXAMPLEVIN", command, None)])
                self.assertEqual(app.climate_mode(app.read_json("cache.json")), mode)
                self.assertIn("confirmed by the vehicle", app.read_json("command-result.json")["message"])

    def test_normal_climate_and_full_shutdown_exit_mode_before_power_command(self):
        for command, power in (("climate-on", True), ("climate-off", False)):
            client = ClimateClient(mode="camp", power=True)
            app.run_vehicle_command(self.config, command, client)
            self.assertEqual([item[1] for item in client.commands], ["climate-mode-off", command])
            self.assertEqual((client.mode, client.power), ("off", power))
            self.assertIn("confirmed by the vehicle", app.read_json("command-result.json")["message"])
        client = ClimateClient()
        app.run_vehicle_command(self.config, "climate-on", client)
        self.assertEqual([item[1] for item in client.commands], ["climate-on"])

    def test_temperature_sets_both_zones_without_enabling_climate(self):
        client = ClimateClient()
        app.run_vehicle_command(self.config, "climate-set-temp", client, temperature="22.5")
        self.assertEqual(client.commands, [("EXAMPLEVIN", "climate-set-temp", 22.5)])
        climate = app.read_json("cache.json")["climate"]
        self.assertEqual((climate["driver_temp_setting"], climate["passenger_temp_setting"]), (22.5, 22.5))
        self.assertFalse(client.power)
        self.assertIn("22.5 °C • confirmed", app.read_json("command-result.json")["message"])

    def test_inside_outside_and_target_readings_are_distinct_and_keep_stale_labels(self):
        client = ClimateClient()
        cache = app.fetch_state(self.config, client)
        self.assertEqual(cache["climate"]["inside_temp"], 20.5)
        self.assertEqual(cache["climate"]["outside_temp"], -3.5)
        menu = app.render(cache, self.config)
        for line in ("--Inside temperature: 20.5 °C", "--Outside temperature: -3.5 °C", "--Target temperature: 21 °C"):
            self.assertIn(line, menu)
        for changes in ({"state": "offline"}, {"state": "asleep"}, {"error": "Network unavailable"}):
            menu = app.render(cache | changes, self.config)
            self.assertIn("--Last known inside temperature: 20.5 °C", menu)
            self.assertIn("--Last known outside temperature: -3.5 °C", menu)
        cache["climate"].update(inside_temp=0, outside_temp=None)
        menu = app.render(cache, self.config)
        self.assertIn("--Inside temperature: 0 °C", menu)
        self.assertIn("--Outside temperature: unavailable", menu)

    def test_invalid_temperatures_are_rejected_before_any_vehicle_access(self):
        for value in (None, True, "nan", "inf", "-inf", "1e308", "22;anything", "22.25"):
            client = ClimateClient()
            with self.subTest(value=value), self.assertRaises(app.AppError):
                app.run_vehicle_command(self.config, "climate-set-temp", client, temperature=value)
            self.assertEqual(client.calls, [])
            self.assertEqual(client.commands, [])
        with self.assertRaises(app.AppError):
            app.run_vehicle_command(self.config, "climate-camp", ClimateClient(), temperature=22)

    def test_temperature_requires_current_vehicle_limits(self):
        for limits, value in (((18, 25), 17.5), ((18, 25), 25.5), (None, 22), ((30, 15), 22)):
            client = ClimateClient()
            client.limits = limits
            app.run_vehicle_command(self.config, "climate-set-temp", client, temperature=value)
            self.assertEqual(client.commands, [])
            self.assertEqual(app.read_json("command-result.json")["status"], "error")

    def test_missing_vehicle_scope_or_key_blocks_before_wake(self):
        for options in ({"authorized": False}, {"paired": False}):
            client = ClimateClient(state="asleep", **options)
            app.run_vehicle_command(self.config, "climate-pet", client)
            self.assertEqual(client.wakes, [])
            self.assertEqual(client.commands, [])
        self.assertIn("key", app.read_json("command-result.json")["message"])

    def test_explicit_mode_can_wake_once_but_refresh_never_changes_climate(self):
        client = ClimateClient(state="asleep")
        with patch.object(app.time, "sleep"):
            app.run_vehicle_command(self.config, "climate-camp", client)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])
        self.assertEqual([item[1] for item in client.commands], ["climate-camp"])
        for _ in range(2):
            app.fetch_state(self.config, client)
        self.assertEqual(len(client.commands), 1)

    def test_partial_shutdown_and_uncertain_result_are_not_retried(self):
        client = ClimateClient(mode="camp", power=True)
        client.fail_command = "climate-off"
        app.run_vehicle_command(self.config, "climate-off", client)
        self.assertEqual([item[1] for item in client.commands], ["climate-mode-off", "climate-off"])
        self.assertEqual(app.read_json("command-result.json")["status"], "error")
        self.assertIn("Some commands were accepted", app.read_json("command-result.json")["message"])
        client = ClimateClient(mode="camp", power=True)
        client.fail_command = "climate-mode-off"
        app.run_vehicle_command(self.config, "climate-off", client)
        self.assertEqual([item[1] for item in client.commands], ["climate-mode-off"])

    def test_acknowledgement_and_old_matching_data_do_not_claim_confirmation(self):
        client = ClimateClient()
        client.apply_changes = False
        app.run_vehicle_command(self.config, "climate-camp", client)
        self.assertEqual(app.read_json("command-result.json")["message"], "Command accepted: Camp Mode")
        client = ClimateClient(mode="camp", power=True)
        client.timestamp = time.time() - 60
        app.run_vehicle_command(self.config, "climate-camp", client)
        self.assertEqual(app.read_json("command-result.json")["message"], "Command accepted: Camp Mode")

    def test_signed_and_unsigned_parameter_mapping(self):
        (self.root / "tesla-control").touch()
        (self.root / "command-key.pem").touch()
        client = app.Client(self.config, Vault({"access_token": "private-token", "expires_at": time.time() + 3600}))
        cases = [(command, ["climate-keeper", mode], {"climate_keeper_mode": code, "manual_override": False}, None)
                 for command, (mode, code) in app.CLIMATE_MODES.items()]
        cases += [("climate-on", ["climate-on"], {}, None), ("climate-off", ["climate-off"], {}, None),
                  ("climate-set-temp", ["climate-set-temp", "22.5C"], {"driver_temp": 22.5, "passenger_temp": 22.5}, 22.5)]
        for command, arguments, body, temperature in cases:
            with self.subTest(command=command):
                with patch.object(app.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                    client.vehicle_command("EXAMPLEVIN", command, {"signing_required": True, "key_paired": True}, temperature)
                args, kwargs = run.call_args
                self.assertEqual(args[0][-len(arguments):], arguments)
                self.assertEqual(kwargs["input"], "private-token")
                self.assertNotIn("private-token", str(args))
                with patch.object(client, "request", return_value={"response": {"result": True}}) as request:
                    client.vehicle_command("EXAMPLEVIN", command, {"signing_required": False}, temperature)
                self.assertEqual(request.call_args.kwargs, {"body": body})
                self.assertTrue(request.call_args.args[0].endswith(app.VEHICLE_COMMANDS[command][2]))

    def test_temperature_menu_executes_cli_with_exact_value_and_bound_vehicle(self):
        client = ClimateClient()
        client.limits = (20, 23)
        cache = app.fetch_state(self.config, client)
        app.save_json("config.json", self.config)
        menu = app.render(cache, self.config)
        self.assertIn("\nClima\n", menu)
        self.assertNotIn("----19.5 °C", menu)
        self.assertNotIn("----23.5 °C", menu)
        self.assertIn("----✓ 21 °C", menu)
        line = next(line for line in menu.splitlines() if line.startswith("----22.5 °C"))
        parameters = dict(part.split("=", 1) for part in shlex.split(line.split(" | ")[1]))
        arguments = [parameters[f"param{i}"] for i in range(1, 7)]
        self.assertEqual(arguments, ["command", "climate-set-temp", "--temperature", "22.5", "--vin", "EXAMPLEVIN"])
        with patch.object(app, "Client", return_value=client), patch("sys.argv", ["plugin"] + arguments), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertEqual(client.commands, [("EXAMPLEVIN", "climate-set-temp", 22.5)])
        # The same open menu must not control a newly selected vehicle.
        app.save_json("config.json", self.config | {"vin": "OTHER"})
        with patch.object(app, "Client", return_value=client), patch("sys.argv", ["plugin"] + arguments), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertEqual(len(client.commands), 1)
        self.assertIn("selected vehicle has changed", app.read_json("command-result.json")["message"])


if __name__ == "__main__":
    unittest.main()
