"""Integration boundaries: settings, regional routing and bounded shared transport."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from src.tesla_bar import api, auth, cli, config, menu, runtime, settings_ui, transport
from src.tesla_bar.errors import AppError, APIError
from scripts import install
from tests.test_tesla_xbar import Vault


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        mocked = patch.object(runtime, "APP_DIR", Path(directory.name))
        mocked.start()
        self.addCleanup(mocked.stop)
        self.config = config.DEFAULTS | {"client_id": "example", "domain": "example.com"}

    def test_all_known_settings_are_validated_from_one_schema(self):
        for change in ({"region": "bad"}, {"display_mode": "other"}, {"location_enabled": "true"},
                       {"location_map_enabled": 1}, {"client_id": "x" * 257}, {"vin": False},
                       {"domain": "https://example.com/redirect"}, {"domain": "bad@example.com"},
                       {"redirect_uri": "http://localhost:bad/callback"},
                       {"redirect_uri": "http://user@localhost:8765/callback"},
                       {"redirect_uri": "http://localhost:8765/callback?other=1"}):
            with self.subTest(change=change), self.assertRaises(AppError):
                config.validate_configuration(self.config | change)
        clean = config.validate_configuration(self.config | {"poll_minutes": 20, "registered": True,
                                                              "domain": "https://EXAMPLE.com/"})
        self.assertNotIn("poll_minutes", clean)
        self.assertTrue(clean["registered"])
        self.assertEqual(clean["domain"], "example.com")

    def test_corrupt_profile_is_reported_and_never_replaced_with_defaults(self):
        for raw in ("not JSON", "[]"):
            (runtime.APP_DIR / "config.json").write_text(raw)
            with self.assertRaises(AppError):
                config.configuration()
            self.assertEqual((runtime.APP_DIR / "config.json").read_text(), raw)

    def test_form_and_menu_choices_use_schema(self):
        fields = settings_ui.settings_fields_html(self.config)
        for name in config.CONNECTION_FIELDS + ("display_mode",):
            self.assertIn('name="' + name + '"', fields)
        with patch.dict(config.SETTINGS, {"display_mode": config.Setting("Display", "range", (("range", "Distance"),))}):
            self.assertIn("Distance</option>", settings_ui.settings_fields_html(self.config))
            self.assertIn("--✓ Distance |", menu.render({}, self.config))
        escaped = settings_ui.settings_fields_html(self.config | {"client_id": '"><script>'})
        self.assertNotIn('<script>', escaped)

    def test_invalid_change_cannot_write_secrets_or_profile(self):
        vault = Mock()
        with self.assertRaises(AppError):
            settings_ui.apply_settings(self.config, {"region": "invalid"}, "secret", vault=vault)
        vault.set.assert_not_called()
        self.assertFalse((runtime.APP_DIR / "config.json").exists())

    def test_same_application_settings_preserve_saved_readings(self):
        cache = {"vin": "EXAMPLE", "charge": {"battery_level": 72}, "updated_at": 123}
        runtime.save_json("cache.json", cache)
        vault = Mock()
        vault.get.return_value = "saved-secret"
        saved = settings_ui.apply_settings(self.config, {"display_mode": "percent"}, vault=vault)
        self.assertEqual(saved["display_mode"], "percent")
        self.assertEqual(runtime.read_json("cache.json"), cache)
        vault.set.assert_not_called()
        vault.request.assert_not_called()

    def test_new_application_requires_its_secret_and_clears_old_vehicle(self):
        vault = Mock()
        with self.assertRaises(AppError):
            settings_ui.apply_settings(self.config, {"client_id": "new-app"}, vault=vault)
        saved = settings_ui.apply_settings(self.config | {"vin": "EXAMPLE", "registered": True},
                                          {"client_id": "new-app"}, "new-secret", vault=vault)
        self.assertFalse(saved["vin"])
        self.assertNotIn("registered", saved)
        vault.request.assert_called_once_with("delete", "oauth")
        self.assertEqual(runtime.read_json("cache.json"), {})

    def test_terminal_settings_use_same_validation_and_storage(self):
        runtime.save_json("config.json", self.config)
        with patch("builtins.input", side_effect=["", "", "na", ""]), \
             patch.object(settings_ui.getpass, "getpass", return_value=""), \
             patch.object(settings_ui, "Keychain") as factory, patch("builtins.print"):
            settings_ui.configure()
        self.assertEqual(config.configuration()["region"], "na")
        factory.return_value.set.assert_not_called()

    def test_installer_bundle_is_deterministic_and_contains_only_code(self):
        import zipfile
        import io
        source = Path(__file__).resolve().parents[1]
        data = install.runtime_bundle(source)
        self.assertEqual(data, install.runtime_bundle(source))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertIn("tesla_bar/cli.py", archive.namelist())
            self.assertTrue(all(name.endswith(".py") for name in archive.namelist()))


class RegionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        mocked = patch.object(runtime, "APP_DIR", Path(directory.name))
        mocked.start()
        self.addCleanup(mocked.stop)
        self.config = config.DEFAULTS | {"client_id": "example"}
        self.vault = Vault({"access_token": "example-token", "expires_at": time.time() + 3600})
        self.auth = auth.Authenticator(self.config, self.vault)

    def test_authoritative_allowed_region_is_saved_and_used(self):
        with patch.object(transport, "request_json", return_value={"response": {"fleet_api_base_url": config.REGIONS["na"]}}) as request:
            self.assertTrue(self.auth.detect_region())
            self.assertTrue(request.call_args.args[0].endswith("/users/region"))
            api.Client(self.config, self.vault).get("/api/1/vehicles")
            self.assertEqual(request.call_args.args[0], config.REGIONS["na"] + "/api/1/vehicles")
        self.assertEqual(config.configuration()["region"], "na")

    def test_bad_or_unavailable_region_keeps_manual_fallback(self):
        for base in (None, "https://example.com", config.REGIONS["na"] + ".example.com", config.REGIONS["na"] + "/path", "http://" + config.REGIONS["na"][8:]):
            with self.subTest(base=base), patch.object(transport, "request_json", return_value={"response": {"fleet_api_base_url": base}}):
                self.assertFalse(self.auth.detect_region())
                self.assertEqual(self.config["region"], "eu")
        with patch.object(transport, "request_json", side_effect=APIError(421)):
            self.assertFalse(self.auth.detect_region())
        self.assertFalse((runtime.APP_DIR / "config.json").exists())

    def test_regular_reads_and_token_refresh_do_not_probe_region(self):
        with patch.object(transport, "request_json", return_value={"response": []}) as request:
            api.Client(self.config, self.vault).get("/api/1/vehicles")
        self.assertEqual(request.call_count, 1)
        self.assertNotIn("/users/region", request.call_args.args[0])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.proxy = patch.object(transport.urllib.request, "getproxies", return_value={})
        self.proxy.start()
        self.addCleanup(self.proxy.stop)
        self.factory = Mock()
        self.connection = self.factory.return_value
        response = self.connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"response": {}}'
        self.session = transport.HTTPSession(self.factory)
        self.addCleanup(self.session.close)

    def test_connections_reused_per_origin_and_headers_never_leak(self):
        self.session.request("https://example.com/one", token="secret")
        self.session.request("https://example.com/two")
        self.assertEqual(self.factory.call_count, 1)
        headers = self.connection.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.session.request("https://another.example/three")
        self.assertEqual(self.factory.call_count, 2)

    def test_failed_physical_command_is_not_retried(self):
        self.connection.getresponse.side_effect = http.client.RemoteDisconnected()
        with self.assertRaises(AppError):
            self.session.request("https://example.com/command", body={})
        self.assertEqual(self.connection.request.call_count, 1)
        self.assertFalse(self.session.connections)

    def test_redirect_is_not_followed_and_rate_limit_is_preserved(self):
        for status in (302, 429):
            response = self.connection.getresponse.return_value
            response.status = status
            response.getheader.return_value = "12"
            with self.assertRaises(APIError) as error:
                self.session.request("https://example.com/command", token="private", body={})
            self.assertEqual(error.exception.status, status)
            self.assertEqual(error.exception.retry_after, 12)
        self.assertEqual(self.connection.request.call_count, 2)

    def test_proxy_keeps_no_redirect_handler_and_timeout(self):
        with patch.object(transport.urllib.request, "getproxies", return_value={"https": "http://proxy.example"}), \
             patch.object(transport.urllib.request, "proxy_bypass", return_value=False), \
             patch.object(transport.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{}'
            self.session.request("https://example.com/test")
            self.assertIs(opener.call_args.args[0], transport.NoRedirect)
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 18)
        self.factory.assert_not_called()

    def test_cli_closes_session_even_when_action_fails(self):
        with patch.object(transport, "_session", self.session), patch.object(cli, "run", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                cli.main()
            self.assertIsNone(transport._session)

    def test_real_local_requests_reuse_one_tcp_connection(self):
        # Real HTTP transport, local fixture only. Production still requires HTTPS.
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def setup(self):
                super().setup()
                self.server.connections += 1
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            def log_message(self, *args):
                pass
            def do_GET(self):
                body = b'{"response": "fixture"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.connections = 0
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        session = transport.HTTPSession(lambda *args, **kwargs: http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=2))
        try:
            for _ in range(3):
                self.assertEqual(session.request("https://fixture.example/read"), {"response": "fixture"})
            self.assertEqual(server.connections, 1)
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

class CallbackIntegrationTests(unittest.TestCase):
    """Exercise the real HTTP handlers in memory, without a Tesla account."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        mock = patch.object(runtime, "APP_DIR", Path(directory.name))
        mock.start()
        self.addCleanup(mock.stop)
        self.config = config.DEFAULTS | {"client_id": "example", "domain": "example.com"}
        runtime.save_json("config.json", self.config)
        runtime.save_json("cache.json", {"charge": {"battery_level": 72}, "updated_at": 123})
        self.vault = Vault({})
        self.vault.values["client-secret"] = "example-secret"

    @staticmethod
    def socket_for(request):
        import io
        class Socket:
            def __init__(self):
                self.output = b""
            def makefile(self, mode, *args):
                return io.BytesIO(request.encode())
            def sendall(self, value):
                self.output += value
        return Socket()

    def test_authorization_exchanges_then_detects_region_without_losing_reading(self):
        import urllib.parse
        owner = self
        class Server:
            def __init__(self, address, handler):
                self.handler = handler
            def handle_request(self):
                url = runtime.read_json("authorization.json")["url"]
                state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
                socket = owner.socket_for(f"GET /callback?code=example&state={state} HTTP/1.0\r\nHost: localhost:8765\r\n\r\n")
                self.handler(socket, ("127.0.0.1", 1234), self)
                owner.assertIn(b"Tesla account connected", socket.output)
            def server_close(self):
                pass
        responses = [{"access_token": "example-access", "refresh_token": "example-refresh", "expires_in": 3600},
                     {"response": {"fleet_api_base_url": config.REGIONS["na"]}}]
        with patch.object(auth.http.server, "HTTPServer", Server), patch.object(auth, "Keychain", return_value=self.vault), \
             patch.object(transport, "request_json", side_effect=responses) as request, patch("builtins.print"):
            auth.authorize(self.config, launch=False)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(config.configuration()["region"], "na")
        self.assertEqual(runtime.read_json("cache.json")["updated_at"], 123)
        self.assertFalse((runtime.APP_DIR / "authorization.json").exists())
        self.assertEqual(json.loads(self.vault.values["oauth"])["access_token"], "example-access")

    def test_browser_form_saves_shared_settings_and_preserves_same_app_cache(self):
        import re
        import urllib.parse
        owner = self
        class Server:
            def __init__(self, address, handler):
                self.handler = handler
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def handle_request(self):
                url = runtime.read_json("setup-session.json")["url"]
                path = urllib.parse.urlsplit(url).path
                socket = owner.socket_for(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1:8766\r\n\r\n")
                self.handler(socket, ("127.0.0.1", 1234), self)
                csrf = re.search(b"name='csrf' value='([^']+)'", socket.output)[1].decode()
                body = urllib.parse.urlencode({"csrf": csrf, "client_id": "example", "domain": "example.com",
                                              "region": "na", "display_mode": "percent", "client_secret": ""})
                socket = owner.socket_for(f"POST {path} HTTP/1.0\r\nHost: 127.0.0.1:8766\r\n"
                    f"Content-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(body)}\r\n\r\n{body}")
                self.handler(socket, ("127.0.0.1", 1234), self)
                owner.assertIn(b"200 OK", socket.output)
        with patch.object(settings_ui.http.server, "HTTPServer", Server), \
             patch.object(settings_ui, "Keychain", return_value=self.vault), patch("builtins.print"):
            settings_ui.provision(self.config, launch=False)
        self.assertEqual(config.configuration()["display_mode"], "percent")
        self.assertEqual(config.configuration()["region"], "na")
        self.assertEqual(runtime.read_json("cache.json")["updated_at"], 123)
        self.assertFalse((runtime.APP_DIR / "setup-session.json").exists())


if __name__ == "__main__":
    unittest.main()
