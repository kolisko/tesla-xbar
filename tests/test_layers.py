"""Enforce architectural boundaries and exercise services without external IO."""
import ast
import copy
import importlib.util
from contextlib import contextmanager, ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar.application.accounts import AccountService
from src.tesla_bar.application.commands import CommandService
from src.tesla_bar.application.location import LocationService
from src.tesla_bar.application.plugin import PluginService
from src.tesla_bar.application.ports import MenuContext, Record, Request
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.domain.commands import VehicleCommand
from src.tesla_bar.domain.errors import AppError, Failure, RemoteError
from src.tesla_bar.domain.settings import DEFAULTS
from src.tesla_bar.infrastructure.gateway import TeslaGateway
from src.tesla_bar.presentation.menu import MenuRenderer

ROOT = Path(__file__).resolve().parents[1] / "src" / "tesla_bar"


def imports(path):
    module = "tesla_bar." + ".".join(path.relative_to(ROOT).with_suffix("").parts)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
            yield base
            yield from (base + "." + alias.name for alias in node.names)


class DependencyTests(unittest.TestCase):
    def test_import_direction_and_external_effects_are_enforced(self):
        allowed = {
            "domain": {"domain"},
            "application": {"domain", "application"},
            "presentation": {"domain", "presentation", "application.ports"},
            "infrastructure": {"domain", "infrastructure", "application.ports"},
        }
        pure_stdlib = {
            "domain": {"dataclasses", "enum", "math", "re", "urllib.parse"},
            "application": {"dataclasses", "enum", "typing"},
            "presentation": {"argparse", "sys", "base64", "datetime", "json", "math", "urllib.parse", "html"},
        }
        for path in ROOT.rglob("*.py"):
            relative = path.relative_to(ROOT)
            if len(relative.parts) == 1:
                self.assertIn(path.name, {"__init__.py", "bootstrap.py"})
                continue
            layer = relative.parts[0]
            for dependency in imports(path):
                with self.subTest(file=str(relative), dependency=dependency):
                    if dependency.startswith("tesla_bar."):
                        local = dependency.removeprefix("tesla_bar.")
                        self.assertTrue(any(local == prefix or local.startswith(prefix + ".") for prefix in allowed[layer]), local)
                    elif layer in pure_stdlib:
                        self.assertTrue(any(dependency == prefix or dependency.startswith(prefix + ".") for prefix in pure_stdlib[layer]), dependency)
            if layer in {"domain", "application", "presentation"}:
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"open", "exec", "eval", "__import__"}, str(relative))
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        self.assertNotIn("/api/1/", node.value, str(relative))
                        self.assertNotIn("tesla-control", node.value, str(relative))
                        self.assertNotIn("fleet-api.prd", node.value, str(relative))

    def test_module_graph_has_no_cycles_including_local_imports(self):
        paths = {"tesla_bar." + ".".join(p.relative_to(ROOT).with_suffix("").parts): p for p in ROOT.rglob("*.py")}
        edges = {name: set(imports(path)) & paths.keys() for name, path in paths.items()}
        visited, active = set(), []
        def visit(name):
            self.assertNotIn(name, active, " -> ".join(active + [name]))
            if name in visited:
                return
            active.append(name)
            for dependency in edges[name]:
                visit(dependency)
            active.pop()
            visited.add(name)
        for name in paths:
            visit(name)


class MemoryProfile:
    def __init__(self):
        self.config = DEFAULTS | {"client_id": "example", "domain": "example.com", "vin": "EXAMPLE"}
        self.records = {}
        self.busy = False

    def read(self, record):
        return copy.deepcopy(self.records.get(record, {}))

    def write(self, record, value):
        self.records[record] = copy.deepcopy(value)

    def delete(self, record):
        self.records.pop(record, None)

    def configuration(self):
        return dict(self.config)

    def save_configuration(self, config, changes=None):
        self.config = config | (changes or {})
        return dict(self.config)

    @contextmanager
    def locked(self, blocking=True):
        if self.busy:
            raise BlockingIOError()
        yield


class TestClock:
    def __init__(self):
        self.value = 2000.0

    def now(self):
        return self.value

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class MemoryGateway:
    def __init__(self):
        self.state = "online"
        self.calls, self.commands = [], []
        self.mode, self.locked = "camp", True
        self.failure = None

    def vehicles(self):
        self.calls.append("vehicles")
        if self.failure:
            raise self.failure
        return [{"vin": "EXAMPLE", "name": "Example", "state": self.state}]

    def granted_scopes(self):
        return {"vehicle_location"}

    def reading(self, vin, include_location, now):
        self.calls.append("reading")
        return {"charge": {"battery_level": 70, "charging_state": "Stopped", "battery_range": 220},
                "gui_settings": {"gui_range_display": "Rated", "gui_distance_units": "km/hr"},
                "climate": {"climate_keeper_mode": self.mode, "is_climate_on": self.mode != "off", "updated_at": now},
                "vehicle_status": {"locked": self.locked, "updated_at": now}, "updated_at": now}

    def connection_state(self, vin):
        return self.state

    def capabilities(self, vin):
        return {"vin": vin, "vehicle_authorized": True, "charging_authorized": True, "pairing_required": False}

    def execute(self, command):
        self.commands.append(command)
        if command.name == "wake":
            self.state = "online"
            return self.state
        if command.name == "climate-mode-off":
            self.mode = "off"
        if command.name == "door-unlock":
            self.locked = False


class IsolatedServiceTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.clock, self.gateway = MemoryProfile(), TestClock(), MemoryGateway()
        self.maps, self.geocoder, self.accounts = Mock(), Mock(), Mock()
        self.location = LocationService(self.clock, self.maps, self.geocoder)
        self.vehicles = VehicleService(self.profile, self.clock, lambda config: self.gateway, self.location)
        self.commands = CommandService(self.profile, self.clock, self.vehicles, lambda config: self.gateway)
        self.app = PluginService(self.profile, self.clock, self.accounts, self.vehicles, self.commands, self.location)

    def test_refresh_and_renderer_work_with_all_external_io_forbidden(self):
        with ExitStack() as stack:
            for target in ("builtins.open", "socket.socket", "subprocess.run", "time.time", "time.sleep"):
                stack.enter_context(patch(target, side_effect=AssertionError("External IO in core")))
            result = self.app.handle(Request())
            context = MenuContext(self.clock.now(), "/example/tesla-action.sh", icon_image=b"example-icon")
            renderer = MenuRenderer(context)
            text = renderer.render(result.cache, result.config)
            self.assertEqual(text, renderer.render(result.cache, result.config))
            self.assertTrue(text.startswith("354 km | color=#32CD66"))
            self.assertIn("Camp Mode", text)
        self.assertEqual(self.gateway.calls, ["vehicles", "reading"])
        self.assertEqual(self.gateway.commands, [])

    def test_same_gateway_handles_explicit_wake_and_unlock(self):
        self.gateway.state = "asleep"
        result = self.app.handle(Request("command", "door-unlock", "EXAMPLE"))
        self.assertEqual([c.name for c in self.gateway.commands], ["wake", "door-unlock"])
        self.assertTrue(all(isinstance(c, VehicleCommand) and c.vin == "EXAMPLE" for c in self.gateway.commands))
        self.assertFalse(result.cache["vehicle_status"]["locked"])
        self.assertIn("confirmed", self.profile.read(Record.COMMAND_RESULT)["message"])

    def test_climate_off_exits_keeper_through_same_command_port(self):
        self.app.handle(Request("command", "climate-off", "EXAMPLE"))
        self.assertEqual([c.name for c in self.gateway.commands], ["climate-mode-off", "climate-off"])

    def test_sleep_keeps_reading_without_any_physical_command(self):
        first = self.app.handle(Request()).cache
        self.gateway.state = "asleep"
        second = self.app.handle(Request()).cache
        self.assertEqual(second["charge"], first["charge"])
        self.assertEqual(self.gateway.calls, ["vehicles", "reading", "vehicles"])
        self.assertEqual(self.gateway.commands, [])

    def test_rate_limit_uses_domain_failure_and_injected_clock(self):
        self.gateway.failure = RemoteError(Failure.RATE_LIMITED, "Wait", 60)
        self.app.handle(Request())
        self.app.handle(Request())
        self.assertEqual(self.gateway.calls, ["vehicles"])
        self.clock.sleep(60)
        self.app.handle(Request())
        self.assertEqual(self.gateway.calls, ["vehicles", "vehicles"])

    def test_busy_and_changed_vehicle_never_execute_commands(self):
        self.profile.busy = True
        self.app.handle(Request("command", "door-unlock", "EXAMPLE"))
        self.profile.busy = False
        self.app.handle(Request("command", "door-unlock", "OTHER"))
        self.assertEqual(self.gateway.calls, [])
        self.assertEqual(self.gateway.commands, [])

    def test_account_renewal_preserves_reading_and_persists_discovered_region(self):
        reading = self.app.handle(Request()).cache
        identity = Mock()
        identity.exchange_code.return_value = "na"
        identity.authorize.side_effect = lambda config, complete, launch: complete("fixture-code")
        service = AccountService(self.profile, identity, Mock())
        service.authorize(self.profile.configuration(), launch=False)
        state = self.profile.read(Record.STATE)
        self.assertEqual(state["charge"], reading["charge"])
        self.assertEqual(state["state"], "unknown")
        self.assertEqual(self.profile.configuration()["region"], "na")

    def test_changed_client_during_authorization_cannot_replace_credentials(self):
        identity = Mock()
        def connect(config, complete, launch):
            self.profile.config["client_id"] = "changed"
            complete("fixture-code")
        identity.authorize.side_effect = connect
        with self.assertRaises(AppError):
            AccountService(self.profile, identity, Mock()).authorize(self.profile.configuration())
        identity.exchange_code.assert_not_called()

    def test_gateway_keeps_signing_details_out_of_public_capabilities(self):
        client = Mock()
        client.command_capabilities.return_value = {"vin": "EXAMPLE", "signing_required": True, "key_paired": True,
                                                    "vehicle_authorized": True, "charging_authorized": True}
        gateway = TeslaGateway({}, client)
        access = gateway.capabilities("EXAMPLE")
        self.assertEqual(set(access), {"vin", "pairing_required", "vehicle_authorized", "charging_authorized"})
        gateway.execute(VehicleCommand("EXAMPLE", "door-lock"))
        client.vehicle_command.assert_called_once_with("EXAMPLE", "door-lock", client.command_capabilities.return_value)
        self.assertEqual(client.command_capabilities.call_count, 1)


class BundleEntrypointTests(unittest.TestCase):
    def test_nested_bundle_starts_from_private_profile_without_checkout_imports(self):
        import os
        import subprocess
        import sys
        import tempfile
        from scripts.install import runtime_bundle
        source = ROOT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "tesla-runtime.zip").write_bytes(runtime_bundle(source))
            (target / "tesla_xbar.py").write_bytes((source / "src" / "tesla_xbar.py").read_bytes())
            env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "TESLA_XBAR_HOME"}}
            env["TESLA_XBAR_HOME"] = directory
            output = subprocess.run([sys.executable, "-B", str(target / "tesla_xbar.py"), "menu"],
                                    cwd=directory, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(output.returncode, 0, output.stderr)
            self.assertIn("Complete setup", output.stdout)
            self.assertIn(str(target / "tesla-action.sh"), output.stdout)
            self.assertTrue((target / "display.txt").read_text().startswith("TESLA_XBAR_DISPLAY_V1"))
