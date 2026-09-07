import base64
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import tesla_xbar as app
from test_tesla_xbar import Vault, WakeClient


class CommandClient(WakeClient):
    def __init__(self, state="online", charging="Stopped", paired=True, authorized=True, error=None):
        super().__init__()
        self.state, self.charging = state, charging
        self.paired, self.authorized, self.command_error = paired, authorized, error
        self.commands = []

    def command_capabilities(self, vin):
        return {"vin": vin, "key_paired": self.paired, "signing_required": True,
                "charging_authorized": self.authorized}

    def vehicle_command(self, vin, command, capabilities):
        self.commands.append((vin, command))
        if self.command_error:
            raise self.command_error
        if command == "charge-start":
            self.charging = "Charging"
        elif command == "charge-stop":
            self.charging = "Stopped"

    def get(self, path):
        result = super().get(path)
        if "vehicle_data?" in path:
            result["response"]["charge_state"]["charging_state"] = self.charging
        return result


class CommandsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = patch.object(app, "APP_DIR", self.root)
        self.here = patch.object(app, "HERE", self.root)
        self.home.start(); self.here.start()
        self.config = app.DEFAULTS | {"client_id": "example", "domain": "example.com", "vin": "EXAMPLEVIN"}

    def tearDown(self):
        self.home.stop(); self.here.stop(); self.temp.cleanup()

    def test_start_and_stop_read_actual_result(self):
        client = CommandClient()
        app.run_vehicle_command(self.config, "charge-start", client)
        self.assertEqual(app.read_json("cache.json")["charge"]["charging_state"], "Charging")
        self.assertIn("confirmed by the vehicle", app.read_json("command-result.json")["message"])
        app.run_vehicle_command(self.config, "charge-stop", client)
        self.assertEqual(app.read_json("cache.json")["charge"]["charging_state"], "Stopped")
        self.assertEqual(client.commands, [("EXAMPLEVIN", "charge-start"), ("EXAMPLEVIN", "charge-stop")])
        self.assertEqual(client.wakes, [])

    def test_missing_key_or_consent_never_wakes_or_sends_command(self):
        for options in ({"paired": False}, {"authorized": False}):
            client = CommandClient(state="asleep", **options)
            app.run_vehicle_command(self.config, "charge-start", client)
            self.assertEqual(client.commands, [])
            self.assertEqual(client.wakes, [])
            self.assertEqual(app.read_json("command-result.json")["status"], "error")

    def test_explicit_command_can_wake_then_start(self):
        client = CommandClient(state="asleep")
        with patch.object(app.time, "sleep"):
            app.run_vehicle_command(self.config, "charge-start", client)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])
        self.assertEqual(client.commands, [("EXAMPLEVIN", "charge-start")])

    def test_menu_and_refresh_never_send_charging_commands(self):
        app.save_json("config.json", self.config)
        client = CommandClient()
        for command in ("menu", "refresh"):
            with patch.object(app, "Client", return_value=client), patch("sys.argv", ["plugin", command]), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(app.main(), 0)
        self.assertEqual(client.commands, [])
        self.assertEqual(client.wakes, [])

    def test_revoked_vehicle_never_receives_command(self):
        client = CommandClient()
        app.run_vehicle_command(self.config | {"vin": "revoked"}, "charge-start", client)
        self.assertEqual(client.commands, [])
        self.assertEqual(client.wakes, [])

    def test_connected_cable_blocks_port_close_and_disconnected_blocks_start(self):
        for command, charging in (("port-close", "Stopped"), ("charge-start", "Disconnected")):
            client = CommandClient(charging=charging)
            app.run_vehicle_command(self.config, command, client)
            self.assertEqual(client.commands, [])
            self.assertEqual(app.read_json("command-result.json")["status"], "error")

    def test_port_commands_and_repeated_stop(self):
        client = CommandClient(charging="Disconnected")
        for command in ("port-open", "port-close", "charge-stop"):
            app.run_vehicle_command(self.config, command, client)
        self.assertEqual([c for _, c in client.commands], ["port-open", "port-close"])

    def test_uncertain_result_is_not_retried_or_erased_by_refresh(self):
        client = CommandClient(error=app.AppError("The result is unconfirmed."))
        app.run_vehicle_command(self.config, "charge-start", client)
        app.fetch_state(self.config, client=client)
        self.assertEqual(len(client.commands), 1)
        self.assertIn("The result is unconfirmed", app.render(app.read_json("cache.json"), self.config))

    def test_only_allowlisted_commands(self):
        client = CommandClient()
        with self.assertRaises(app.AppError):
            app.run_vehicle_command(self.config, "door-unlock", client)
        self.assertEqual(client.calls, [])

    def test_signed_command_token_uses_stdin_and_errors_are_redacted(self):
        (self.root / "tesla-control").touch()
        (self.root / "command-key.pem").touch()
        token = "private-access-token"
        client = app.Client(self.config, Vault({"access_token": token, "expires_at": time.time() + 3600}))
        ready = {"signing_required": True, "key_paired": True}
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="Failure with " + token)
        with patch.object(app.subprocess, "run", return_value=result) as run:
            with self.assertRaises(app.AppError) as error:
                client.vehicle_command("EXAMPLEVIN", "charge-start", ready)
        self.assertNotIn(token, str(error.exception))
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(kwargs["input"], token)
        self.assertNotIn(token, " ".join(args[0]))
        self.assertNotIn(token, str(kwargs["env"]))
        self.assertEqual(args[0][-1], "charging-start")
        self.assertEqual(kwargs["umask"], 0o077)

    def test_sdk_timeout_is_not_retried(self):
        (self.root / "tesla-control").touch(); (self.root / "command-key.pem").touch()
        client = app.Client(self.config, Vault({"access_token": "secret", "expires_at": time.time() + 3600}))
        with patch.object(app.subprocess, "run", side_effect=subprocess.TimeoutExpired("tool", 45)) as run:
            with self.assertRaisesRegex(app.AppError, "not be retried"):
                client.vehicle_command("EXAMPLEVIN", "charge-start", {"signing_required": True, "key_paired": True})
        run.assert_called_once()

    def test_fleet_status_and_scope_parsing(self):
        payload = base64.urlsafe_b64encode(json.dumps({"scp": ["vehicle_charging_cmds"]}).encode()).decode().rstrip("=")
        client = app.Client(self.config, Vault({"access_token": "header." + payload + ".sig", "expires_at": time.time() + 3600}))
        response = {"response": {"key_paired_vins": ["EXAMPLEVIN"], "vehicle_info": {"EXAMPLEVIN": {"vehicle_command_protocol_required": True}}}}
        with patch.object(client, "request", return_value=response):
            self.assertEqual(client.command_capabilities("EXAMPLEVIN"), {"vin": "EXAMPLEVIN", "signing_required": True, "key_paired": True, "charging_authorized": True})


if __name__ == "__main__":
    unittest.main()
