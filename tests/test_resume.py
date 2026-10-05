"""Mac resume policy and real service flows, without waking a real vehicle."""
import copy
import subprocess
import unittest
from unittest.mock import Mock, patch

from src.tesla_bar.application.plugin import PluginService
from src.tesla_bar.application.ports import MenuContext, Record, Request, Visibility
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.domain.errors import AppError, Failure, RemoteError, RetryAdvice
from src.tesla_bar.domain.resume import SleepCycle, observe_sleep
from src.tesla_bar.infrastructure.visibility import DesktopVisibility, sleep_cycle_from_output
from src.tesla_bar.presentation.menu import MenuRenderer
from tests.test_layers import MemoryProfile, TestClock, MemoryGateway


class ResumeGateway(MemoryGateway):
    def execute(self, command):
        self.commands.append(command)
        if command.name == "wake":
            self.state = "online"
            return self.state


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.clock, self.gateway = MemoryProfile(), TestClock(), ResumeGateway()
        self.factory, self.location, self.desktop = Mock(return_value=self.gateway), Mock(), Mock()
        self.desktop.state.return_value = Visibility.VISIBLE
        self.desktop.sleep_cycle.return_value = SleepCycle(100, 0, 0)
        self.vehicles = VehicleService(self.profile, self.clock, self.factory, self.location)
        self.app = PluginService(self.profile, self.clock, Mock(), self.vehicles, Mock(), self.location, self.desktop)
        self.app.handle(Request())  # First run only arms detection.
        self.gateway.calls.clear()
        self.factory.reset_mock()

    def resume(self, seconds=3601):
        self.clock.value = 2100 + seconds + 10
        self.desktop.sleep_cycle.return_value = SleepCycle(100, 2100, 2100 + seconds)
        self.gateway.state = "asleep"

    def test_long_sleep_wakes_once_and_reads_once_under_same_lock(self):
        self.resume()
        original = self.gateway.execute
        def execute(command):
            # The claim must already be persisted, before a physical request.
            record = self.profile.read(Record.RESUME)
            self.assertNotIn("pending", record)
            self.assertEqual(record["outcome"], "refresh_attempted")
            return original(command)
        self.gateway.execute = execute
        result = self.app.handle(Request())
        self.assertEqual([c.name for c in self.gateway.commands], ["wake"])
        self.assertEqual(result.cache["state"], "online")
        self.assertEqual(result.cache["updated_at"], self.clock.now())
        self.assertEqual(self.gateway.calls.count("reading"), 1)
        # A later process/run must not replay the same wake, even if asleep again.
        self.gateway.state = "asleep"
        self.clock.value += 300
        restarted = PluginService(self.profile, self.clock, Mock(), self.vehicles, Mock(), self.location, self.desktop)
        restarted.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)

    def test_awake_vehicle_is_read_without_wake_or_duplicate_reading(self):
        self.resume()
        self.gateway.state = "online"
        self.app.handle(Request())
        self.assertEqual(self.gateway.calls, ["vehicles", "reading"])
        self.assertEqual(self.gateway.commands, [])

    def test_one_hour_or_less_no_sleep_restart_and_invalid_probe_do_not_wake(self):
        baseline = copy.deepcopy(self.profile.records)
        for cycle in (SleepCycle(100, 2100, 5699), SleepCycle(100, 2100, 5700),
                      SleepCycle(100, 0, 0), SleepCycle(4000, 0, 0),
                      SleepCycle(100, 2100, 999999), SleepCycle(100, 2200, 2100), None):
            with self.subTest(cycle=cycle):
                self.profile.records = copy.deepcopy(baseline)
                self.clock.value = 5800
                self.desktop.sleep_cycle.return_value = cycle
                self.gateway.state = "asleep"
                self.app.handle(Request())
                self.assertEqual(self.gateway.commands, [])

    def test_hidden_states_and_busy_operation_do_not_consume_opportunity(self):
        self.resume()
        before = copy.deepcopy(self.profile.records)
        for visibility in Visibility:
            if visibility is Visibility.VISIBLE:
                continue
            self.desktop.state.return_value = visibility
            self.app.handle(Request())
            self.assertEqual(self.profile.records, before)
        self.desktop.state.return_value = Visibility.VISIBLE
        self.profile.busy = True
        self.app.handle(Request())
        self.assertEqual(self.profile.records, before)
        self.factory.assert_not_called()
        self.profile.busy = False
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)

    def test_local_and_server_wait_defer_without_consuming_wake(self):
        self.resume()
        deadline = self.clock.now() + 7200
        cache = self.profile.read(Record.STATE) | {"consecutive_read_errors": 3,
            "read_retry_at": self.clock.now() + 900,
            "tesla_retry_after": {"value": "7200", "received_at": self.clock.now(), "delay": 7200}}
        self.profile.write(Record.STATE, cache)
        self.app.handle(Request())
        self.factory.assert_not_called()
        self.assertIn("pending", self.profile.read(Record.RESUME))
        self.clock.value = deadline - 1
        self.app.handle(Request())
        self.factory.assert_not_called()
        self.clock.value = deadline
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)
        self.assertNotIn("pending", self.profile.read(Record.RESUME))

    def test_manual_refresh_is_read_only_and_fresh_result_satisfies_resume(self):
        self.resume()
        self.gateway.state = "online"
        self.app.handle(Request("refresh"))
        self.assertEqual(self.gateway.commands, [])
        self.app.handle(Request())
        self.assertEqual(self.gateway.calls, ["vehicles", "reading"])
        self.assertEqual(self.profile.read(Record.RESUME)["outcome"], "already_refreshed")
        self.assertNotIn("pending", self.profile.read(Record.RESUME))

    def test_local_backoff_alone_defers_and_unknown_probe_cannot_release_pending(self):
        self.resume()
        cycle = self.desktop.sleep_cycle.return_value
        deadline = self.clock.now() + 900
        self.profile.write(Record.STATE, self.profile.read(Record.STATE) | {
            "consecutive_read_errors": 3, "read_retry_at": deadline})
        self.app.handle(Request())
        self.factory.assert_not_called()
        self.assertIn("pending", self.profile.read(Record.RESUME))
        self.clock.value = deadline
        self.desktop.sleep_cycle.return_value = None
        self.app.handle(Request())
        self.assertEqual(self.gateway.commands, [])
        self.assertIn("pending", self.profile.read(Record.RESUME))
        self.desktop.sleep_cycle.return_value = cycle
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)

    def test_later_short_sleep_or_reboot_cancels_deferred_event(self):
        self.resume()
        self.profile.write(Record.STATE, self.profile.read(Record.STATE) | {
            "consecutive_read_errors": 3, "read_retry_at": self.clock.now() + 900})
        self.app.handle(Request())
        pending = copy.deepcopy(self.profile.records)
        for cycle in (SleepCycle(100, 6000, 6060), SleepCycle(6100, 0, 0)):
            self.profile.records = copy.deepcopy(pending)
            self.desktop.sleep_cycle.return_value = cycle
            self.clock.value = 7000
            self.app.handle(Request())
            self.assertEqual(self.gateway.commands, [])
            self.assertNotIn("pending", self.profile.read(Record.RESUME))

    def test_another_long_sleep_permits_one_new_wake(self):
        self.resume()
        self.app.handle(Request())
        self.clock.value = 10000
        self.desktop.sleep_cycle.return_value = SleepCycle(100, 6000, 9900)
        self.gateway.state = "asleep"
        self.app.handle(Request())
        self.assertEqual([c.name for c in self.gateway.commands], ["wake", "wake"])

    def test_failed_or_asleep_manual_read_does_not_consume_resume(self):
        self.resume()
        self.app.handle(Request("refresh"))
        self.app.handle(Request())  # Immediate redraw must reuse the manual result.
        self.assertIn("pending", self.profile.read(Record.RESUME))
        self.assertEqual(self.gateway.commands, [])
        self.clock.value += 300
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)

    def test_failed_wake_and_failed_availability_never_repeat_for_same_sleep(self):
        self.resume()
        def uncertain(command):
            self.gateway.commands.append(command)
            raise AppError("Network unavailable")
        self.gateway.execute = uncertain
        self.app.handle(Request())
        self.clock.value += 300
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)
        # A new long sleep permits a new attempt, but failed GET never sends wake.
        self.clock.value += 4000
        self.desktop.sleep_cycle.return_value = SleepCycle(100, 7000, 10900)
        self.clock.value = 11000
        self.gateway.failure = AppError("Network unavailable")
        self.app.handle(Request())
        self.gateway.failure = None
        self.app.handle(Request())
        self.assertEqual(len(self.gateway.commands), 1)

    def test_revoked_vehicle_and_changed_selection_do_not_wake_cached_vin(self):
        self.resume()
        self.gateway.vehicles = lambda: []
        self.app.handle(Request())
        self.assertEqual(self.gateway.commands, [])
        pending = {"boot_at": 100, "armed_at": 2000, "seen_sleep_at": 2100,
                   "pending": {"sleep_at": 2100, "wake_at": 5701, "vin": "OLD"}}
        self.profile.write(Record.RESUME, pending)
        self.app.handle(Request())
        self.assertNotIn("pending", self.profile.read(Record.RESUME))

    def test_first_observation_baselines_old_sleep_without_waking(self):
        self.resume()
        self.profile.delete(Record.RESUME)
        self.app.handle(Request())
        self.assertEqual(self.gateway.commands, [])

    def test_wake_entrypoint_respects_server_advice_even_without_cached_error(self):
        self.profile.write(Record.STATE, self.profile.read(Record.STATE) | {
            "state": "asleep", "tesla_retry_after": {"received_at": self.clock.now(), "delay": 60}})
        self.vehicles.wake_and_refresh(self.profile.config)
        self.factory.assert_not_called()
        self.assertEqual(self.gateway.commands, [])

    def test_new_server_advice_prevents_wake(self):
        self.resume()
        self.gateway.failure = RemoteError(Failure.RATE_LIMITED, "Wait", 600,
            retry_advice=RetryAdvice("600", self.clock.now(), 600))
        self.app.handle(Request())
        self.assertEqual(self.gateway.commands, [])
        self.assertEqual(self.profile.read(Record.STATE)["tesla_retry_after"]["value"], "600")

    def test_debug_shows_pending_and_handled_without_exposing_vin(self):
        resume = {"last_sleep_at": 2100, "last_wake_at": 6000,
                  "pending": {"vin": "PRIVATEVIN"}}
        menu = MenuRenderer(MenuContext(6001, "/example/action", resume=resume)).render({}, {})
        self.assertIn("Last observed Mac sleep: 65.0 min", menu)
        self.assertIn("Mac resume refresh: pending", menu)
        self.assertNotIn("PRIVATEVIN", menu)
        resume.pop("pending")
        resume.update(handled_at=6001, outcome="refresh_attempted")
        menu = MenuRenderer(MenuContext(6001, "/example/action", resume=resume)).render({}, {})
        self.assertIn("Mac resume refresh: attempted", menu)


class SleepProbeTests(unittest.TestCase):
    OUTPUT = "kern.boottime: { sec = 100, usec = 0 } date\nkern.sleeptime: { sec = 2000, usec = 123456 } date\nkern.waketime: { sec = 7000, usec = 654321 } date\n"

    def test_kernel_output_and_bounded_read_only_probe(self):
        expected = SleepCycle(100, 2000.123456, 7000.654321)
        self.assertEqual(sleep_cycle_from_output(self.OUTPUT), expected)
        with patch("src.tesla_bar.infrastructure.visibility.subprocess.run",
                   return_value=Mock(stdout=self.OUTPUT, returncode=0)) as run:
            self.assertEqual(DesktopVisibility().sleep_cycle(), expected)
        self.assertEqual(run.call_args.args[0], ["/usr/sbin/sysctl", "kern.boottime", "kern.sleeptime", "kern.waketime"])
        self.assertEqual(run.call_args.kwargs["timeout"], 3)

    def test_missing_denied_incomplete_or_invalid_probe_cannot_authorize_wake(self):
        for output in ("", "{}", self.OUTPUT.splitlines()[0], self.OUTPUT + self.OUTPUT,
                       self.OUTPUT.replace("123456", "1000000")):
            self.assertIsNone(sleep_cycle_from_output(output))
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("sysctl", 3)):
            with patch("src.tesla_bar.infrastructure.visibility.subprocess.run", side_effect=error):
                self.assertIsNone(DesktopVisibility().sleep_cycle())
        with patch("src.tesla_bar.infrastructure.visibility.subprocess.run", return_value=Mock(returncode=1)):
            self.assertIsNone(DesktopVisibility().sleep_cycle())
        baseline = {"boot_at": 100, "armed_at": 1000, "seen_sleep_at": 0}
        for cycle in (SleepCycle(100, 2000, 0), SleepCycle(100, 2000, float("nan")),
                      SleepCycle(100, 2000, 9000), SleepCycle(100, 50, 6000)):
            self.assertEqual(observe_sleep(baseline, cycle, "EXAMPLE", now=7000), baseline)


if __name__ == "__main__":
    unittest.main()
