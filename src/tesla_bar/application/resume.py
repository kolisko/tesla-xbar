"""Claim a resume refresh under the caller's existing operation lock."""
from .ports import Record, Visibility
from ..domain.models import number
from ..domain.polling import retry_not_before, reuse_manual_refresh
from ..domain.resume import SleepCycle, observe_sleep, observe_inactivity


class ResumeService:
    def __init__(self, profile, clock, desktop):
        self.profile, self.clock, self.desktop = profile, clock, desktop

    def observe(self, config, cache, visibility, *, may_wake=False):
        now = self.clock.now()
        cycle = self.desktop.sleep_cycle()
        previous = self.profile.read(Record.RESUME)
        vin = config.get("vin") or cache.get("vin") or cache.get("selected_vin")
        record = observe_sleep(previous, cycle, vin, now=now)
        state = visibility.value if isinstance(visibility, Visibility) else "unknown"
        record = observe_inactivity(record, state, vin, now=now)
        pending = record.get("pending")
        claimed = False
        if (may_wake and visibility == Visibility.VISIBLE
                and isinstance(cycle, SleepCycle) and cycle.valid(now) and pending):
            updated = cache.get("updated_at")
            if (number(updated) and pending["wake_at"] <= updated <= now
                    and cache.get("vin") == vin and not cache.get("error")):
                # A manual action may already have obtained a fresh reading.
                record.pop("pending")
                record.update(handled_at=now, outcome="already_refreshed")
            elif now >= retry_not_before(cache) and not reuse_manual_refresh(cache, now=now):
                # Persist before dispatch: timeouts/crashes must never replay wake.
                record.pop("pending")
                record.update(handled_at=now, outcome="refresh_attempted")
                claimed = True
        if record != previous:
            self.profile.write(Record.RESUME, record)
        return claimed
