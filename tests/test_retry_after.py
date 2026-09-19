"""Show actual Tesla retry advice and honor its receipt-based deadline."""
import urllib.error
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar.application.ports import MenuContext, Record
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.domain.polling import retry_not_before, tesla_retry_until
from src.tesla_bar.infrastructure import api, transport
from src.tesla_bar.infrastructure.errors import APIError
from src.tesla_bar.presentation.menu import MenuRenderer, local_timestamp
from tests.test_layers import MemoryProfile, TestClock, MemoryGateway


class RetryAfterTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.clock, self.gateway = MemoryProfile(), TestClock(), MemoryGateway()
        self.factory = Mock(return_value=self.gateway)
        self.service = VehicleService(self.profile, self.clock, self.factory, Mock())
        self.config = self.profile.config
        self.baseline = self.service.fetch_state(self.config)

    def error(self, status, value):
        with patch.object(transport.time, "time", return_value=self.clock.now()):
            return transport.response_error(status, value)

    def test_direct_http_error_preserves_only_retry_header_and_receipt_time(self):
        response = Mock(status=503)
        response.read.return_value = b'{"private": "discard"}'
        response.getheader.return_value = "120"
        connection = Mock()
        connection.getresponse.return_value = response
        session = transport.HTTPSession(lambda *args, **kwargs: connection)
        self.addCleanup(session.close)
        with patch.object(transport.urllib.request, "getproxies", return_value={}), \
             patch.object(transport, "request_sent"), \
             patch.object(transport.time, "time", return_value=2000):
            with self.assertRaises(APIError) as raised:
                session.request("https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1/vehicles")
        advice = raised.exception.retry_advice
        self.assertEqual((advice.value, advice.received_at, advice.delay), ("120", 2000, 120))
        self.assertNotIn("private", str(raised.exception))
        response.getheader.assert_called_once_with("Retry-After")

    def test_proxy_http_date_uses_the_same_receipt_timestamp(self):
        value = "Thu, 01 Jan 1970 00:36:00 GMT"
        error = urllib.error.HTTPError("https://example.com", 429, "rate limited", {"Retry-After": value}, None)
        opener = Mock()
        opener.open.side_effect = error
        session = transport.HTTPSession()
        self.addCleanup(session.close)
        with patch.object(transport.urllib.request, "getproxies", return_value={"https": "proxy"}), \
             patch.object(transport.urllib.request, "proxy_bypass", return_value=False), \
             patch.object(transport.urllib.request, "build_opener", return_value=opener), \
             patch.object(transport, "request_sent"), \
             patch.object(transport.time, "time", return_value=2000):
            with self.assertRaises(APIError) as raised:
                session.request("https://fleet-api.prd.eu.vn.cloud.tesla.com/api/1/vehicles")
        advice = raised.exception.retry_advice
        self.assertEqual((advice.value, advice.received_at, advice.delay), (value, 2000, 160))

    def test_actual_advice_controls_next_attempt_for_any_error_status_and_manual_retry(self):
        for status in (401, 403, 429, 503):
            self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 2})
            self.gateway.failure = self.error(status, "7200")
            received = self.clock.now()
            # Application handling must not move the server deadline forward.
            self.clock.value += 10
            cache = self.service.fetch_state(self.config)
            self.assertEqual(cache["tesla_retry_after"], {"value": "7200", "received_at": received, "delay": 7200})
            self.assertEqual(retry_not_before(cache), received + 7200)
            self.assertEqual(retry_not_before(cache, manual=True), received + 7200)
            self.clock.value = received + 7199
            self.factory.reset_mock()
            self.service.fetch_state(self.config, manual=True)
            self.factory.assert_not_called()
            self.clock.value += 1
            self.gateway.failure = None
            recovered = self.service.fetch_state(self.config)
            self.factory.assert_called_once()
            self.assertNotIn("read_retry_at", recovered)
            self.assertEqual(recovered["tesla_retry_after"], cache["tesla_retry_after"])

    def test_debug_shows_advice_receipt_expiry_and_reason_for_later_local_deadline(self):
        self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 2})
        self.gateway.failure = self.error(503, "120")
        cache = self.service.fetch_state(self.config)
        menu = MenuRenderer(MenuContext(self.clock.now(), "/example/action")).render(cache, self.config)
        self.assertIn("Latest Tesla Retry-After: 120", menu)
        self.assertIn("Retry-After received: " + local_timestamp(self.clock.now()), menu)
        self.assertIn("Tesla retry not before: " + local_timestamp(self.clock.now() + 120) + " (waiting)", menu)
        self.assertIn("Next automatic API attempt: " + local_timestamp(self.clock.now() + 900), menu)
        self.assertIn("Waiting for: local error backoff", menu)
        cache["read_retry_at"] = self.clock.now() + 60
        menu = MenuRenderer(MenuContext(self.clock.now(), "/example/action")).render(cache, self.config)
        self.assertIn("Waiting for: Tesla Retry-After", menu)
        self.assertIn("Next automatic API attempt: " + local_timestamp(self.clock.now() + 120), menu)
        menu = MenuRenderer(MenuContext(self.clock.now() + 900, "/example/action")).render(cache, self.config)
        self.assertIn("(elapsed)", menu)

    def test_absent_and_invalid_headers_are_not_invented_as_a_server_deadline(self):
        self.assertIsNone(self.error(403, None).retry_advice)
        self.gateway.failure = self.error(403, None)
        cache = self.service.fetch_state(self.config)
        self.assertNotIn("tesla_retry_after", cache)
        menu = MenuRenderer(MenuContext(self.clock.now(), "/example/action")).render(cache, self.config)
        self.assertIn("Tesla Retry-After: not recorded yet", menu)
        self.gateway.failure = self.error(503, "not-a-time | shell=bad\ntext")
        cache = self.service.fetch_state(self.config)
        self.assertIsNone(cache["tesla_retry_after"]["delay"])
        self.assertEqual(tesla_retry_until(cache), 0)
        menu = MenuRenderer(MenuContext(self.clock.now(), "/example/action")).render(cache, self.config)
        row = next(row for row in menu.splitlines() if "Latest Tesla Retry-After:" in row)
        self.assertNotIn("| shell=", row)
        self.assertIn("could not be parsed", menu)

    def test_401_retry_after_prevents_an_immediate_authentication_retry(self):
        client = api.Client(self.config, Mock())
        error = self.error(401, "60")
        with patch.object(client, "access_token", return_value="example") as token, \
             patch.object(transport, "request_json", side_effect=error) as request:
            with self.assertRaises(APIError):
                client.get("/api/1/vehicles")
        request.assert_called_once()
        token.assert_called_once_with(force=False)

    def test_location_fallback_cannot_ignore_teslas_requested_delay(self):
        self.config["location_enabled"] = True
        self.gateway.reading = Mock(side_effect=self.error(403, "60"))
        cache = self.service.fetch_state(self.config)
        self.gateway.reading.assert_called_once()
        self.assertEqual(retry_not_before(cache), self.clock.now() + 60)
        self.assertEqual(cache["tesla_retry_after"]["value"], "60")
