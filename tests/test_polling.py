"""Error backoff uses xBar invocations, with no extra timers or network work."""
import copy
import unittest
from unittest.mock import Mock

from src.tesla_bar.application.accounts import reset_authorized_state
from src.tesla_bar.application.plugin import PluginService
from src.tesla_bar.application.ports import MenuContext, Record, Request, Visibility
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.domain.errors import AppError, Failure, RemoteError
from src.tesla_bar.domain.polling import read_retry_delay, retry_not_before
from src.tesla_bar.presentation.menu import MenuRenderer, local_timestamp
from tests.test_layers import MemoryProfile, TestClock, MemoryGateway


class PollingTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.clock, self.gateway = MemoryProfile(), TestClock(), MemoryGateway()
        self.factory, self.location = Mock(return_value=self.gateway), Mock()
        self.service = VehicleService(self.profile, self.clock, self.factory, self.location)
        self.config = self.profile.config
        self.baseline = self.service.fetch_state(self.config)

    def fail(self):
        self.gateway.failure = RemoteError(Failure.FORBIDDEN, "Tesla denied access.")
        return self.service.fetch_state(self.config)

    def test_real_attempts_follow_15_30_60_minutes_and_remain_capped(self):
        for count, delay in ((1, 0), (2, 0), (3, 900), (4, 1800), (5, 3600), (6, 3600), (7, 3600)):
            self.factory.reset_mock()
            cache = self.fail()
            self.factory.assert_called_once()
            self.assertEqual(cache["consecutive_read_errors"], count)
            self.assertEqual(read_retry_delay(cache), delay)
            self.assertEqual(cache["charge"], self.baseline["charge"])
            self.assertEqual(cache["updated_at"], self.baseline["updated_at"])
            if not delay:
                self.assertNotIn("read_retry_at", cache)
                self.clock.value += 300
                continue
            deadline = self.clock.now() + delay
            self.assertEqual(cache["read_retry_at"], deadline)
            before = copy.deepcopy(cache)
            self.factory.reset_mock()
            self.location.reset_mock()
            # Repeated xBar/Refresh All invocations must not postpone the attempt.
            for offset in (1, 299, delay - 1):
                self.clock.value = deadline - delay + offset
                self.assertEqual(self.service.fetch_state(self.config), before)
                self.assertEqual(self.profile.read(Record.STATE), before)
            self.factory.assert_not_called()
            self.assertEqual(self.location.mock_calls, [])
            self.clock.value = deadline

    def test_deadline_survives_a_new_process_and_success_restores_normal_schedule(self):
        for _ in range(3):
            cache = self.fail()
        restarted = VehicleService(self.profile, self.clock, self.factory, self.location)
        self.factory.reset_mock()
        self.assertEqual(restarted.fetch_state(self.config), cache)
        self.factory.assert_not_called()
        self.clock.value = cache["read_retry_at"]
        self.gateway.failure = None
        recovered = restarted.fetch_state(self.config)
        self.assertEqual(recovered["consecutive_read_errors"], 0)
        self.assertNotIn("read_retry_at", recovered)
        self.assertNotIn("error", recovered)
        # No additional normal-operation timer: every following xBar run reads.
        self.factory.reset_mock()
        restarted.fetch_state(self.config)
        self.factory.assert_called_once()

    def test_server_retry_after_takes_precedence_when_longer(self):
        for server_delay, expected in ((60, 900), (7200, 7200)):
            self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 2})
            self.gateway.failure = RemoteError(Failure.RATE_LIMITED, "Rate limit", server_delay)
            cache = self.service.fetch_state(self.config)
            self.assertEqual(cache["read_retry_at"], self.clock.now() + 900)
            self.assertEqual(retry_not_before(cache), self.clock.now() + expected)
            self.clock.value += expected - 1
            self.factory.reset_mock()
            self.assertEqual(self.service.fetch_state(self.config), cache)
            self.factory.assert_not_called()
            self.clock.value += 1
            self.gateway.failure = None
            cache = self.service.fetch_state(self.config)
            self.assertNotIn("retry_at", cache)
            self.assertNotIn("read_retry_at", cache)

    def test_deadline_is_measured_after_failed_request_finishes(self):
        def slow_failure():
            self.clock.value += 20
            raise AppError("Network unavailable.")
        self.gateway.vehicles = slow_failure
        self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 2})
        started = self.clock.now()
        cache = self.service.fetch_state(self.config)
        self.assertEqual(cache["read_retry_at"], started + 20 + 900)

    def test_all_unavailable_vehicle_states_clear_error_backoff_when_due(self):
        for state in ("asleep", "offline", "408"):
            self.profile.write(Record.STATE, self.baseline | {
                "consecutive_read_errors": 5, "read_retry_at": self.clock.now()})
            self.gateway.state = state
            self.gateway.failure = RemoteError(Failure.UNAVAILABLE, "Unavailable") if state == "408" else None
            cache = self.service.fetch_state(self.config)
            self.assertEqual(cache["consecutive_read_errors"], 0)
            self.assertNotIn("read_retry_at", cache)
            self.assertEqual(cache["charge"], self.baseline["charge"])

    def test_hidden_desktop_and_xbar_refresh_cannot_bypass_deadline(self):
        for _ in range(3):
            cache = self.fail()
        desktop = Mock()
        app = PluginService(self.profile, self.clock, Mock(), self.service, Mock(), self.location, desktop)
        self.factory.reset_mock()
        self.location.reset_mock()
        for state in (Visibility.VISIBLE, Visibility.LOCKED):
            desktop.state.return_value = state
            result = app.handle(Request("menu"))
            self.assertEqual(result.cache["read_retry_at"], cache["read_retry_at"])
            self.assertEqual(self.profile.read(Record.STATE), cache)
        self.clock.value = cache["read_retry_at"] + 1
        app.handle(Request())  # Due, but the desktop is still locked.
        self.factory.assert_not_called()
        self.assertEqual(self.location.mock_calls, [])
        desktop.state.return_value = Visibility.VISIBLE
        app.handle(Request())
        self.factory.assert_called_once()

    def test_explicit_refresh_bypasses_local_wait_and_followup_redraw_reuses_result(self):
        for _ in range(3):
            cache = self.fail()
        desktop = Mock()
        desktop.state.return_value = Visibility.VISIBLE
        app = PluginService(self.profile, self.clock, Mock(), self.service, Mock(), self.location, desktop)
        self.factory.reset_mock()
        result = app.handle(Request("refresh"))
        self.factory.assert_called_once()
        self.assertEqual(result.cache["consecutive_read_errors"], 4)
        self.assertEqual(result.cache["read_retry_at"], self.clock.now() + 1800)
        self.assertEqual(app.handle(Request("menu")).cache, result.cache)
        self.factory.assert_called_once()
        # A second explicit click always attempts again, even during that redraw window.
        self.gateway.failure = None
        result = app.handle(Request("refresh"))
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(result.cache["consecutive_read_errors"], 0)
        self.assertNotIn("read_retry_at", result.cache)
        for seconds in (0, 1, 4.9):
            self.clock.value = result.cache["manual_refresh_completed_at"] + seconds
            self.assertEqual(app.handle(Request("menu")).cache, result.cache)
        self.assertEqual(self.factory.call_count, 2)
        self.clock.value = result.cache["manual_refresh_completed_at"] + 300
        app.handle(Request("menu"))
        self.assertEqual(self.factory.call_count, 3)

    def test_explicit_refresh_respects_tesla_retry_after_and_does_not_send_commands(self):
        self.profile.write(Record.STATE, self.baseline | {"consecutive_read_errors": 3,
            "read_retry_at": self.clock.now() + 900, "retry_at": self.clock.now() + 30,
            "retry_reason": Failure.RATE_LIMITED, "error": "Rate limit"})
        self.factory.reset_mock()
        self.service.fetch_state(self.config, manual=True)
        self.factory.assert_not_called()
        self.clock.value += 30
        self.service.fetch_state(self.config, manual=True)
        self.factory.assert_called_once()
        self.assertEqual(self.gateway.commands, [])

    def test_explicit_refresh_remains_explicit_if_desktop_hides_after_click(self):
        desktop = Mock()
        desktop.state.return_value = Visibility.LOCKED
        app = PluginService(self.profile, self.clock, Mock(), self.service, Mock(), self.location, desktop)
        self.factory.reset_mock()
        result = app.handle(Request("refresh"))
        self.factory.assert_called_once()
        self.assertNotIn("polling_paused", result.cache)
        self.assertEqual(self.gateway.commands, [])

    def test_menu_refresh_action_is_distinct_from_the_scheduled_entrypoint(self):
        menu = MenuRenderer(MenuContext(self.clock.now(), "/example/action")).render(self.baseline, self.config)
        row = next(line for line in menu.splitlines() if line.startswith("Refresh now |"))
        self.assertIn('param1="refresh"', row)
        self.assertIn('terminal=false refresh=true', row)

    def test_renewed_consent_allows_new_attempt_without_claiming_fresh_data(self):
        cache = self.baseline | {"consecutive_read_errors": 5, "read_retry_at": self.clock.now() + 3600}
        renewed = reset_authorized_state(cache)
        self.assertEqual(renewed["consecutive_read_errors"], 5)
        self.assertEqual(renewed["updated_at"], cache["updated_at"])
        self.assertNotIn("read_retry_at", renewed)
        self.profile.write(Record.STATE, renewed)
        self.factory.reset_mock()
        self.service.fetch_state(self.config)
        self.factory.assert_called_once()

    def test_debug_explains_retry_deadline_and_visibility_without_promising_exact_dispatch(self):
        deadline = self.clock.now() + 900
        cache = self.baseline | {"consecutive_read_errors": 3, "read_retry_at": deadline}
        renderer = MenuRenderer(MenuContext(self.clock.now(), "/example/action"))
        menu = renderer.render(cache, self.config)
        self.assertIn("--Next automatic API attempt: " + local_timestamp(deadline), menu)
        self.assertIn("At the first visible xBar run at or after this time.", menu)
        hidden = renderer.render(cache | {"polling_paused": "locked"}, self.config)
        self.assertIn("Desktop hidden: this attempt also waits for visibility.", hidden)
        renderer = MenuRenderer(MenuContext(deadline, "/example/action"))
        self.assertIn("Next automatic API attempt: next visible xBar run", renderer.render(cache, self.config))
        self.assertIn("Next automatic API attempt: when the desktop is visible again",
                      renderer.render(cache | {"polling_paused": "locked"}, self.config))

    def test_corrupt_or_obsolete_deadlines_cannot_suppress_healthy_polling(self):
        for value in (None, True, "5000", float("nan"), float("inf"), -1, [], {}):
            cache = {"consecutive_read_errors": 3, "read_retry_at": value,
                     "retry_reason": Failure.RATE_LIMITED, "retry_at": value}
            self.assertEqual(retry_not_before(cache), 0)
        self.assertEqual(retry_not_before({"consecutive_read_errors": 0, "read_retry_at": 9999}), 0)
        self.assertEqual(retry_not_before({"retry_reason": Failure.FORBIDDEN, "retry_at": 9999}), 0)
        self.assertEqual(retry_not_before({"consecutive_read_errors": 3, "read_retry_at": 9999}), 9999)


if __name__ == "__main__":
    unittest.main()
