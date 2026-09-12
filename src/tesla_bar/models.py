"""Models responsibilities for Tesla xBar."""
import math
import time


STALE_AFTER_SECONDS = 30 * 60


STATUS_ICON_ORDER = ("charging", "camp", "pet", "fan", "unlocked", "sentry", "frunk", "trunk")


VEHICLE_COMMANDS = {
    "charge-start": ("charging-start", "Start charging", "charge_start"),
    "charge-stop": ("charging-stop", "Stop charging", "charge_stop"),
    "port-open": ("charge-port-open", "Open charge port", "charge_port_door_open"),
    "port-close": ("charge-port-close", "Close charge port", "charge_port_door_close"),
    "climate-on": ("climate-on", "Turn climate on", "auto_conditioning_start"),
    "climate-off": ("climate-off", "Turn climate and modes off", "auto_conditioning_stop"),
    "climate-keep": ("climate-keeper", "Keep Climate On", "set_climate_keeper_mode"),
    "climate-camp": ("climate-keeper", "Camp Mode", "set_climate_keeper_mode"),
    "climate-pet": ("climate-keeper", "Pet Mode", "set_climate_keeper_mode"),
    "climate-mode-off": ("climate-keeper", "Turn modes off", "set_climate_keeper_mode"),
    "climate-set-temp": ("climate-set-temp", "Set temperature", "set_temps"),
    "sentry-on": ("sentry-mode", "Turn Sentry on", "set_sentry_mode"),
    "sentry-off": ("sentry-mode", "Turn Sentry off", "set_sentry_mode"),
    "door-lock": ("lock", "Lock vehicle", "door_lock"),
    "door-unlock": ("unlock", "Unlock vehicle", "door_unlock"),
    "frunk-open": ("frunk-open", "Open front trunk", "actuate_trunk"),
    "trunk-move": ("trunk-move", "Open / close rear trunk", "actuate_trunk"),
}


LOCK_TRUNK_COMMANDS = ("door-lock", "door-unlock", "frunk-open", "trunk-move")


VEHICLE_SCOPE_PREFIXES = ("climate-", "sentry-", "door-", "frunk-", "trunk-")


CLIMATE_MODES = {"climate-keep": ("on", 1), "climate-pet": ("dog", 2),
                 "climate-camp": ("camp", 3), "climate-mode-off": ("off", 0)}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def temperature_limits(cache):
    climate = cache.get("climate") or {}
    low, high = climate.get("min_avail_temp"), climate.get("max_avail_temp")
    # Bound menu size and reject malformed ranges; the actual limits come from Tesla.
    if number(low) and number(high) and -50 <= low <= high <= 100 and high - low <= 50:
        return low, high
    return None


def trunk_open_state(vehicle_status, field):
    value = vehicle_status.get(field)
    # Tesla closure readings use zero for closed and nonzero for open/ajar.
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255:
        return value != 0
    return None


def vehicle_range_miles(cache):
    gui = cache.get("gui_settings") or {}
    field = {"Rated": "battery_range", "Ideal": "ideal_battery_range"}.get(gui.get("gui_range_display"))
    value = (cache.get("charge") or {}).get(field)
    return value if number(value) and value >= 0 else None


def vehicle_range(cache):
    """Format Tesla's range in the vehicle's units; never derive it from SOC."""
    gui = cache.get("gui_settings") or {}
    units = {"km/hr": (1.609344, "km"), "mi/hr": (1, "mi")}.get(gui.get("gui_distance_units"))
    value = vehicle_range_miles(cache)
    if not units or value is None:
        return None
    factor, label = units
    return f"{math.floor(value * factor + 0.5)} {label}"


def cable_connected(charge):
    state = charge.get("charging_state")
    if state == "Disconnected":
        return False
    if state in ("Charging", "Complete", "Stopped", "NoPower", "Starting"):
        return True
    cable = charge.get("conn_charge_cable")
    if isinstance(cable, str) and cable.strip() and cable.lower() not in ("<invalid>", "invalid", "unknown", "none"):
        return True
    return None


def battery_color(cache):
    connected = cable_connected(cache.get("charge") or {})
    if connected is True:
        return "#32CD66"
    miles = vehicle_range_miles(cache)
    if connected is False and miles is not None:
        km = math.floor(miles * 1.609344 + 0.5)
        if km < 300:
            return "#EF4444"
        if km < 350:
            return "#F5A623"
    return None  # Native text color: white in the user's dark menu bar.


def charging_is_current(cache, config=None):
    fresh_until = cache.get("updated_at", 0) + STALE_AFTER_SECONDS
    return (cache.get("charge", {}).get("charging_state") == "Charging"
            and cache.get("state") == "online" and not cache.get("error")
            and time.time() < fresh_until)


def status_is_current(cache, section):
    data = cache.get(section) or {}
    timestamp = data.get("updated_at")
    return (cache.get("state") == "online" and not cache.get("error")
            and number(timestamp) and 0 <= time.time() - timestamp < STALE_AFTER_SECONDS)


def climate_mode(cache):
    value = (cache.get("climate") or {}).get("climate_keeper_mode")
    return value.strip().lower() if isinstance(value, str) else None


def active_status_icons(cache):
    icons = ["charging"] if charging_is_current(cache) else []
    if status_is_current(cache, "climate"):
        mode = climate_mode(cache)
        if mode == "camp":
            icons.append("camp")
        elif mode in ("dog", "pet"):
            icons.append("pet")
        if cache["climate"].get("is_climate_on") is True:
            icons.append("fan")
    if status_is_current(cache, "vehicle_status") and cache["vehicle_status"].get("locked") is False:
        icons.append("unlocked")
    if status_is_current(cache, "vehicle_status") and cache["vehicle_status"].get("sentry_mode") is True:
        icons.append("sentry")
    if status_is_current(cache, "vehicle_status"):
        for field, icon in (("ft", "frunk"), ("rt", "trunk")):
            if trunk_open_state(cache["vehicle_status"], field) is True:
                icons.append(icon)
    return icons
