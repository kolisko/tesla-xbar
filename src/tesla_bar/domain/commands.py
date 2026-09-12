"""Semantic commands and pure validation/confirmation rules."""
from dataclasses import dataclass
from .errors import AppError
from .models import COMMAND_LABELS, CLIMATE_MODES, number, status_is_current, climate_mode, trunk_open_state

@dataclass(frozen=True)
class VehicleCommand:
    vin: str
    name: str
    temperature: float | None = None

    def __post_init__(self):
        if not isinstance(self.vin, str) or not self.vin:
            raise AppError("Select a vehicle first.")
        if self.name == "wake":
            if self.temperature is not None:
                raise AppError("Temperature is only valid for the temperature command.")
        else:
            object.__setattr__(self, "temperature", validate_command(self.name, self.temperature))

def validate_command(command, temperature=None):
    if command not in COMMAND_LABELS:
        raise AppError("Unsupported command.")
    if command != "climate-set-temp":
        if temperature is not None:
            raise AppError("Temperature is only valid for the temperature command.")
        return None
    try:
        value = float(temperature) if not isinstance(temperature, bool) else None
    except (TypeError, ValueError, OverflowError):
        value = None
    if not number(value) or not number(value * 2) or value * 2 != round(value * 2):
        raise AppError("Choose a temperature in 0.5 °C steps from the Clima menu.")
    return value

def climate_command_confirmed(cache, command, temperature, sent_at, *, now):
    climate = cache.get("climate") or {}
    if not status_is_current(cache, "climate", now=now) or climate.get("updated_at", 0) < sent_at:
        return False
    mode = climate_mode(cache)
    if command in CLIMATE_MODES:
        expected = CLIMATE_MODES[command]
        if mode == "pet":
            mode = "dog"
        return mode == expected and (expected == "off" or climate.get("is_climate_on") is True)
    if command in ("climate-on", "climate-off"):
        return mode == "off" and climate.get("is_climate_on") is (command == "climate-on")
    if command == "climate-set-temp":
        return all(number(climate.get(key)) and abs(climate[key] - temperature) < 0.1
                   for key in ("driver_temp_setting", "passenger_temp_setting"))
    return False

def lock_trunk_confirmation(fresh, before, command, sent_at, *, now):
    status = fresh.get("vehicle_status") or {}
    if not status_is_current(fresh, "vehicle_status", now=now) or status.get("updated_at", 0) < sent_at:
        return None
    if command.startswith("door-") and status.get("locked") is (command == "door-lock"):
        return "Vehicle locked" if command == "door-lock" else "Vehicle unlocked"
    if command == "frunk-open" and trunk_open_state(status, "ft") is True:
        return "Front trunk open"
    if command == "trunk-move" and status_is_current(before, "vehicle_status", now=now):
        previous = trunk_open_state(before.get("vehicle_status") or {}, "rt")
        current = trunk_open_state(status, "rt")
        # A toggle acknowledgement alone does not tell us the resulting position.
        if previous is not None and current is not None and previous != current:
            return "Rear trunk open" if current else "Rear trunk closed"
    return None
