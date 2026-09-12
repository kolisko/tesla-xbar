import io
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from src import tesla_xbar as app
from src.tesla_bar import api, cli, runtime, transport
from tests.test_commands import CommandClient
from tests.test_tesla_xbar import Vault


class AccessClient(CommandClient):
    def __init__(self, **options):
        super().__init__(**options)
        self.locked, self.front, self.rear = True, 0, 0
        self.apply_changes = True
        self.status_time = None
        self.omit_fields = False
        self.signed = True

    def command_capabilities(self, vin):
        return super().command_capabilities(vin) | {"signing_required": self.signed}

    def vehicle_command(self, vin, command, capabilities):
        super().vehicle_command(vin, command, capabilities)
        if not self.apply_changes:
            return
        if command.startswith("door-"):
            self.locked = command == "door-lock"
        elif command == "frunk-open":
            self.front = 255
        elif command == "trunk-move":
            self.rear = 0 if self.rear else 255

    def get(self, path):
        result = super().get(path)
        if "vehicle_data?" in path:
            status = {"timestamp": (time.time() if self.status_time is None else self.status_time) * 1000,
                      "odometer": 1234, "vehicle_name": "Private"}
            if not self.omit_fields:
                status.update(locked=self.locked, ft=self.front, rt=self.rear)
            result["response"]["vehicle_state"] = status
        return result


class LocksTrunksTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name in ("APP_DIR", "HERE"):
            mocked = patch.object(runtime, name, self.root)
            mocked.start()
            self.addCleanup(mocked.stop)
        network = patch.object(transport, "request_json", side_effect=AssertionError("No real Tesla requests"))
        network.start()
        self.addCleanup(network.stop)
        self.config = app.DEFAULTS | {"client_id": "example", "vin": "EXAMPLEVIN"}

    def test_actions_read_back_lock_and_trunk_changes(self):
        client = AccessClient()
        for command, expected in (("door-unlock", "Vehicle unlocked"), ("door-lock", "Vehicle locked"),
                                  ("frunk-open", "Front trunk open"), ("trunk-move", "Rear trunk open"),
                                  ("trunk-move", "Rear trunk closed")):
            with self.subTest(command=command):
                app.run_vehicle_command(self.config, command, client)
                report = app.read_json("command-result.json")
                self.assertEqual(report["message"], expected + " • confirmed by the vehicle.")
        self.assertEqual(len(client.commands), 5)
        self.assertEqual(client.wakes, [])

    def test_missing_scope_key_or_revoked_vehicle_blocks_before_wake(self):
        for command in app.LOCK_TRUNK_COMMANDS:
            for options in ({"authorized": False}, {"paired": False}):
                client = AccessClient(state="asleep", **options)
                app.run_vehicle_command(self.config, command, client)
                self.assertEqual(client.commands, [])
                self.assertEqual(client.wakes, [])
                self.assertEqual(app.read_json("command-result.json")["status"], "error")
            client = AccessClient()
            app.run_vehicle_command(self.config | {"vin": "REVOKED"}, command, client)
            self.assertEqual(client.commands, [])

    def test_manual_action_can_wake_once_but_menu_and_refresh_never_actuate(self):
        client = AccessClient(state="asleep")
        with patch.object(time, "sleep"):
            app.run_vehicle_command(self.config, "door-lock", client)
        self.assertEqual(client.wakes, ["EXAMPLEVIN"])
        self.assertEqual(client.commands, [("EXAMPLEVIN", "door-lock")])
        app.save_json("config.json", self.config)
        client = AccessClient(state="asleep")
        for command in ("menu", "refresh"):
            with patch.object(api, "Client", return_value=client), patch("sys.argv", ["plugin", command]), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(app.main(), 0)
        self.assertEqual(client.commands, [])
        self.assertEqual(client.wakes, [])

    def test_old_missing_or_unchanged_data_does_not_confirm_a_transition(self):
        for command in app.LOCK_TRUNK_COMMANDS:
            for kind in ("old", "missing", "unchanged"):
                client = AccessClient()
                client.locked = command != "door-lock"
                if kind == "old":
                    client.status_time = time.time() - 60
                elif kind == "missing":
                    client.omit_fields = True
                else:
                    client.apply_changes = False
                app.run_vehicle_command(self.config, command, client)
                self.assertEqual(app.read_json("command-result.json")["message"],
                                 "Command accepted: " + app.VEHICLE_COMMANDS[command][1])
                self.assertEqual(len(client.commands), 1)

    def test_uncertain_toggle_is_not_retried_and_denied_scope_is_actionable(self):
        for command in app.LOCK_TRUNK_COMMANDS:
            client = AccessClient(error=app.AppError("The result is unconfirmed."))
            app.run_vehicle_command(self.config, command, client)
            app.fetch_state(self.config, client)
            self.assertEqual(len(client.commands), 1)
            self.assertIn("unconfirmed", app.read_json("command-result.json")["message"])
            client = AccessClient(error=app.APIError(403))
            app.run_vehicle_command(self.config, command, client)
            self.assertIn("Vehicle Commands", app.read_json("command-result.json")["message"])
            self.assertIn("Vehicle Commands", app.command_error("403 forbidden", command))

    def test_signed_and_legacy_transport_use_correct_commands_and_payloads(self):
        for name in ("tesla-control", "command-key.pem"):
            (self.root / name).touch()
        client = app.Client(self.config, Vault({"access_token": "private-token", "expires_at": time.time() + 3600}))
        cases = (("door-lock", "lock", "door_lock", {}), ("door-unlock", "unlock", "door_unlock", {}),
                 ("frunk-open", "frunk-open", "actuate_trunk", {"which_trunk": "front"}),
                 ("trunk-move", "trunk-move", "actuate_trunk", {"which_trunk": "rear"}))
        for command, cli, endpoint, body in cases:
            with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                client.vehicle_command("EXAMPLEVIN", command, {"signing_required": True, "key_paired": True})
            self.assertEqual(run.call_args.args[0][-1], cli)
            self.assertEqual(run.call_args.kwargs["input"], "private-token")
            self.assertNotIn("private-token", str(run.call_args.args))
            with patch.object(client, "request", return_value={"response": {"result": True}}) as request:
                client.vehicle_command("EXAMPLEVIN", command, {"signing_required": False})
            self.assertEqual(request.call_args.args, ("/api/1/vehicles/EXAMPLEVIN/command/" + endpoint,))
            self.assertEqual(request.call_args.kwargs, {"body": body})

    def test_new_fields_share_existing_read_and_saved_status_is_explicit(self):
        client = AccessClient()
        client.front, client.rear = 255, 0
        cache = app.fetch_state(self.config, client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(set(cache["vehicle_status"]), {"locked", "ft", "rt", "updated_at"})
        self.assertIn("--Front trunk: open", app.render(cache, self.config))
        for state in ("asleep", "offline"):
            client.state = state
            saved = app.fetch_state(self.config, client)
            self.assertEqual(saved["vehicle_status"], cache["vehicle_status"])
            menu = app.render(saved, self.config)
            self.assertIn("--Last known vehicle lock: locked", menu)
            self.assertIn("--Last known front trunk: open", menu)
            self.assertIn("--Last known rear trunk: closed", menu)
        client.state, client.omit_fields = "online", True
        cache = app.fetch_state(self.config, client)
        self.assertEqual(cache["vehicle_status"], {})
        self.assertIn("front trunk: unavailable", app.render(cache, self.config))

    def test_malformed_closure_readings_are_not_treated_as_open_or_closed(self):
        for value in (None, True, False, -1, 256, "0", "255", 1.5, float("nan")):
            self.assertIsNone(app.trunk_open_state({"ft": value}, "ft"))
        self.assertFalse(app.trunk_open_state({"ft": 0}, "ft"))
        for value in (1, 255):
            self.assertTrue(app.trunk_open_state({"ft": value}, "ft"))

    def test_one_submenu_routes_all_actions_and_binds_to_displayed_vehicle(self):
        client = AccessClient()
        cache = app.fetch_state(self.config, client)
        app.save_json("config.json", self.config)
        menu = app.render(cache, self.config)
        submenu = menu.split("\nLocks and trunks\n")[1].split("\nClima\n")[0]
        self.assertNotIn("Close front trunk", submenu)
        self.assertIn("Rear trunk closing depends on vehicle support.", submenu)
        for command in app.LOCK_TRUNK_COMMANDS:
            label = app.VEHICLE_COMMANDS[command][1]
            line = next(line for line in submenu.splitlines() if line.startswith("--" + label + " |"))
            self.assertEqual(menu.count(line), 1)
            parameters = dict(part.split("=", 1) for part in shlex.split(line.split(" | ")[1]))
            arguments = [parameters[f"param{i}"] for i in range(1, 5)]
            self.assertEqual(arguments, ["command", command, "--vin", "EXAMPLEVIN"])
            with patch.object(api, "Client", return_value=client), patch("sys.argv", ["plugin"] + arguments), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(app.main(), 0)
            self.assertEqual(client.commands[-1], ("EXAMPLEVIN", command))
        app.save_json("config.json", self.config | {"vin": "OTHER"})
        with patch.object(api, "Client", return_value=client), patch("sys.argv", ["plugin"] + arguments), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(), 0)
        self.assertEqual(len(client.commands), 4)
        self.assertIn("selected vehicle has changed", app.read_json("command-result.json")["message"])
        no_vehicle = app.render({}, self.config)
        for command in app.LOCK_TRUNK_COMMANDS:
            self.assertIn("--" + app.VEHICLE_COMMANDS[command][1] + " | color=gray", no_vehicle)


if __name__ == "__main__":
    unittest.main()
