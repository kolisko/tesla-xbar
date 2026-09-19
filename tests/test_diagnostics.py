import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar import bootstrap
from src.tesla_bar.application.ports import MenuContext, Visibility
from src.tesla_bar.domain.settings import DEFAULTS
from src.tesla_bar.infrastructure import diagnostics, runtime, transport
from src.tesla_bar.infrastructure.errors import APIError
from src.tesla_bar.presentation.menu import MenuRenderer


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.patch = patch.object(runtime, "APP_DIR", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_only_two_times_persist_per_event_even_with_concurrent_writers(self):
        def write(event, offset):
            for i in range(1, 6):
                diagnostics.record(event, offset + i)
        threads = [threading.Thread(target=write, args=(event, offset)) for event, offset in
                   (("plugin_runs", 10), ("tesla_api_calls", 20))]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(diagnostics.snapshot(), {"plugin_runs": [15, 14], "tesla_api_calls": [25, 24]})
        data = json.loads((self.home / "diagnostics.json").read_text())
        self.assertEqual(set(data), set(diagnostics.EVENTS))
        self.assertEqual((self.home / "diagnostics.json").stat().st_mode & 0o777, 0o600)

    def test_cache_only_invocations_update_plugin_times_not_api_times(self):
        runtime.save_json("config.json", DEFAULTS | {"client_id": "example"})
        with patch.object(bootstrap.DesktopVisibility, "state", return_value=Visibility.LOCKED), \
             patch.object(bootstrap, "TeslaGateway", side_effect=AssertionError("Unexpected API access")), \
             patch.object(bootstrap, "present", return_value="cached"), contextlib.redirect_stdout(io.StringIO()):
            for stamp in (100, 200):
                with patch.object(diagnostics.time, "time", return_value=stamp):
                    self.assertEqual(bootstrap.main(["menu"]), 0)
        self.assertEqual(diagnostics.snapshot(), {"plugin_runs": [200, 100], "tesla_api_calls": []})

    def test_only_dispatched_tesla_requests_advance_api_times_including_403(self):
        response = Mock(status=403)
        response.read.return_value = b'{}'
        response.getheader.return_value = ""
        connection = Mock()
        connection.getresponse.return_value = response
        session = transport.HTTPSession(lambda *args, **kwargs: connection)
        self.addCleanup(session.close)
        with patch.object(transport.urllib.request, "getproxies", return_value={}), \
             patch.object(diagnostics.time, "time", return_value=300):
            with self.assertRaises(APIError):
                session.request("https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1/vehicles", token="not-saved")
            self.assertEqual(diagnostics.snapshot()["tesla_api_calls"], [300])
            connection.request.side_effect = OSError("no connection")
            with self.assertRaises(Exception):
                session.request("https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1/vehicles")
            diagnostics.request_sent("mapmap.ai")
            diagnostics.request_sent("fleet-api.prd.eu.vn.cloud.tesla.com.example.org")
        self.assertEqual(diagnostics.snapshot()["tesla_api_calls"], [300])
        self.assertNotIn("not-saved", (self.home / "diagnostics.json").read_text())

    def test_proxy_error_response_and_oauth_requests_are_recorded(self):
        error = transport.urllib.error.HTTPError("https://fleet-auth.prd.vn.cloud.tesla.com", 401, "no", {}, None)
        opener = Mock()
        opener.open.side_effect = error
        session = transport.HTTPSession()
        self.addCleanup(session.close)
        with patch.object(transport.urllib.request, "getproxies", return_value={"https": "example"}), \
             patch.object(transport.urllib.request, "proxy_bypass", return_value=False), \
             patch.object(transport.urllib.request, "build_opener", return_value=opener), \
             patch.object(diagnostics.time, "time", return_value=400):
            with self.assertRaises(APIError):
                session.request("https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token", form={"example": "value"})
        self.assertEqual(diagnostics.snapshot()["tesla_api_calls"], [400])

    def test_debug_menu_renders_four_times_without_io_and_handles_empty_history(self):
        context = MenuContext(2000, "/example/action", diagnostics={"plugin_runs": [1234.125, 1200.5], "tesla_api_calls": [1220]})
        with patch("builtins.open", side_effect=AssertionError("IO from renderer")):
            menu = MenuRenderer(context).render({}, DEFAULTS)
        self.assertIn("Debug info\n", menu)
        self.assertIn("--Plugin run — Latest:", menu)
        self.assertIn("--Plugin run — Previous:", menu)
        self.assertIn("--Tesla API request — Latest:", menu)
        self.assertIn("--Tesla API request — Previous: Not recorded yet", menu)
        self.assertIn(".125", menu)

    def test_corrupt_history_does_not_break_a_refresh(self):
        (self.home / "diagnostics.json").write_text('not json')
        diagnostics.record("plugin_runs", 100)
        self.assertEqual(diagnostics.snapshot()["plugin_runs"], [100])
        with patch.object(runtime, "save_json", side_effect=OSError("disk unavailable")):
            diagnostics.record("tesla_api_calls", 200)


if __name__ == "__main__":
    unittest.main()
