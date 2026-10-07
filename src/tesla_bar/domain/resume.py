"""One wake opportunity after observed Mac sleep or inactivity over an hour."""
from dataclasses import dataclass
from .models import number

MAC_SLEEP_THRESHOLD = 60 * 60
INACTIVE_STATES = {"locked", "display_off", "screensaver", "inactive"}


@dataclass(frozen=True)
class SleepCycle:
    boot_at: float
    sleep_at: float
    wake_at: float

    def valid(self, now):
        if not all(number(value) for value in (self.boot_at, self.sleep_at, self.wake_at, now)):
            return False
        return 0 < self.boot_at <= now and (
            self.sleep_at == self.wake_at == 0 or
            self.boot_at <= self.sleep_at < self.wake_at <= now)


def observe_sleep(previous, cycle, vin, *, now):
    """Retain deferred work, but never turn a missing probe or old event into a wake."""
    if not isinstance(cycle, SleepCycle) or not cycle.valid(now):
        return dict(previous)
    if (previous.get("boot_at") != cycle.boot_at
            or not number(previous.get("armed_at"))
            or not number(previous.get("seen_sleep_at"))
            or previous["armed_at"] > now
            or previous["seen_sleep_at"] > cycle.sleep_at):
        # First observation and reboot establish a baseline, not a vehicle action.
        return {"boot_at": cycle.boot_at, "armed_at": now,
                "seen_sleep_at": cycle.sleep_at}
    record = dict(previous)
    pending = record.get("pending")
    if pending and (not isinstance(pending, dict) or pending.get("vin") != vin
                    or not number(pending.get("sleep_at")) or not number(pending.get("wake_at"))
                    or not record["armed_at"] <= pending["sleep_at"] < pending["wake_at"] <= now
                    or pending["wake_at"] - pending["sleep_at"] <= MAC_SLEEP_THRESHOLD):
        record.pop("pending", None)
    if cycle.sleep_at > record["seen_sleep_at"]:
        record.update(seen_sleep_at=cycle.sleep_at, last_sleep_at=cycle.sleep_at,
                      last_wake_at=cycle.wake_at)
        # A later short sleep supersedes an older deferred wake opportunity.
        record.pop("pending", None)
        if (cycle.sleep_at >= record["armed_at"]
                and cycle.wake_at - cycle.sleep_at > MAC_SLEEP_THRESHOLD
                and isinstance(vin, str) and vin):
            record["pending"] = {"sleep_at": cycle.sleep_at, "wake_at": cycle.wake_at, "vin": vin}
    return record


def observe_inactivity(previous, visibility, vin, *, now):
    """Measure observed absence across runs; a hidden menu bar alone is not absence."""
    record = dict(previous)
    # Require an initialized boot baseline so a restart cannot carry an old lock.
    if not number(record.get("armed_at")) or not number(now):
        return record
    start = record.get("inactive_since")
    valid = (number(start) and record["armed_at"] <= start <= now
             and record.get("inactive_vin") == vin)
    if visibility in INACTIVE_STATES:
        if not valid:
            record.update(inactive_since=now, inactive_vin=vin,
                          inactive_reason=visibility)
        # Changing from locked to display-off is still the same absence.
        return record
    reason = record.get("inactive_reason")
    for key in ("inactive_since", "inactive_vin", "inactive_reason"):
        record.pop(key, None)
    if visibility in ("visible", "bar_hidden") and valid:
        record.update(last_inactive_at=start, last_active_at=now,
                      last_inactive_reason=reason)
        if now - start > MAC_SLEEP_THRESHOLD and isinstance(vin, str) and vin:
            # Merge with any system-sleep event from the same absence, not a
            # second queued wake. The caller consumes this one common record.
            record["pending"] = {"sleep_at": start, "wake_at": now,
                                 "vin": vin, "source": "inactivity"}
    # A hidden bar alone means an active desktop: finish an existing absence,
    # but do not claim its wake until the bar is visible. Unknown visibility
    # breaks the measurement rather than guessing the user stayed away.
    return record
