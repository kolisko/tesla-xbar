"""Menu responsibilities for Tesla xBar."""
import base64
import datetime as dt
import json
import math
import os
import tempfile
import time
import urllib.request
from . import runtime
from .config import SETTINGS
from .runtime import read_json
from .models import CLIMATE_MODES, LOCK_TRUNK_COMMANDS, STALE_AFTER_SECONDS, STATUS_ICON_ORDER, VEHICLE_COMMANDS, active_status_icons, battery_color, cable_connected, charging_is_current, climate_mode, number, status_is_current, temperature_limits, trunk_open_state, vehicle_range
from .location import coordinates, saved_map_png


def safe_text(value):
    value = str(value).replace("|", "¦")
    value = " ".join(value.split())
    value = "".join(c for c in value if c.isprintable())
    return value.lstrip("-")[:180]


def action(label, command, *args, terminal=False):
    launcher = runtime.APP_DIR / "tesla-action.sh"
    params = " ".join(f"param{i}={json.dumps(str(arg))}" for i, arg in enumerate((command,) + args, 1))
    return f'{label} | shell={json.dumps(str(launcher))} {params} terminal={str(terminal).lower()} refresh=true'


def status_icon_image(icons):
    names = [name for name in STATUS_ICON_ORDER if name in icons]
    if not names or ("camp" in names and "pet" in names):
        return ""
    try:
        return base64.b64encode((runtime.HERE / "icons" / ("-".join(names) + ".png")).read_bytes()).decode("ascii")
    except OSError:
        return ""  # Textual status remains available if an asset is missing.


def status_menu_lines(cache):
    lines = []
    climate = cache.get("climate") or {}
    current = status_is_current(cache, "climate")
    mode = {"camp": "Camp Mode", "dog": "Pet Mode", "pet": "Pet Mode", "on": "Keep Climate On", "off": "Off"}.get(climate_mode(cache))
    if mode is not None:
        label = "Climate mode" if current else "Last known climate mode"
        lines.append(f"{label}: {mode}")
    if isinstance(climate.get("is_climate_on"), bool):
        label = "Climate" if current else "Last known climate"
        lines.append(f"{label}: {'on' if climate['is_climate_on'] else 'off'}")
    vehicle = cache.get("vehicle_status") or {}
    if isinstance(vehicle.get("locked"), bool):
        label = "Vehicle" if status_is_current(cache, "vehicle_status") else "Last known vehicle lock"
        lines.append(f"{label}: {'locked' if vehicle['locked'] else 'unlocked'}")
    return lines


def sentry_menu(cache, vehicle_action):
    state = (cache.get("vehicle_status") or {}).get("sentry_mode")
    current = status_is_current(cache, "vehicle_status")
    label = "Sentry" if current else "Last known Sentry"
    value = ("on" if state else "off") if isinstance(state, bool) else "unavailable"
    lines = ["Sentry", f"--{label}: {value} | color=gray", "-----"]
    for command in ("sentry-on", "sentry-off"):
        checked = current and state is (command == "sentry-on")
        label = ("✓ " if checked else "") + VEHICLE_COMMANDS[command][1]
        lines.append("--" + vehicle_action(label, "command", command))
    return lines


def locks_trunks_menu(cache, vehicle_action):
    status = cache.get("vehicle_status") or {}
    current = status_is_current(cache, "vehicle_status")
    locked = status.get("locked")
    lock_state = ("locked" if locked else "unlocked") if isinstance(locked, bool) else "unavailable"
    label = "Vehicle lock" if current else "Last known vehicle lock"
    lines = ["Locks and trunks", f"--{label}: {lock_state} | color=gray"]
    for field, label in (("ft", "Front trunk"), ("rt", "Rear trunk")):
        opened = trunk_open_state(status, field)
        value = ("open" if opened else "closed") if opened is not None else "unavailable"
        label = label if current else "Last known " + label.lower()
        lines.append(f"--{label}: {value} | color=gray")
    lines.append("-----")
    for command in LOCK_TRUNK_COMMANDS:
        if command == "frunk-open":
            lines.append("-----")
        lines.append("--" + vehicle_action(VEHICLE_COMMANDS[command][1], "command", command))
    lines.append("--Rear trunk closing depends on vehicle support. | color=gray")
    return lines


def location_menu(cache, config):
    lines = ["Location"]
    if config.get("location_enabled") is not True:
        lines.extend(["--Location is disabled | color=gray",
                      "--Address lookup shares vehicle coordinates with Apple | color=gray",
                      "--" + action("Enable Location…", "location-enable", terminal=True)])
        return lines
    location = cache.get("location") or {}
    point = coordinates(location)
    current = status_is_current(cache, "location") and not cache.get("location_error")
    if point is not None:
        if config.get("location_map_enabled") is True:
            png = saved_map_png(cache)
            if png is not None:
                lines.append("--\u200b | image=" + base64.b64encode(png).decode())
            else:
                lines.append("--Map preview unavailable • use Open in Apple Maps | color=gray")
        label = "Address" if current else "Last known address"
        address = location.get("address")
        if isinstance(address, str) and address:
            # Split multiline postal addresses into safe, non-actionable menu rows.
            lines.append(f"--{label} | color=gray")
            for part in address.splitlines()[:6]:
                lines.append("--" + safe_text(part) + " | color=gray")
        else:
            lines.append("--Address unavailable • position available on map | color=gray")
        stamp = location.get("updated_at")
        if number(stamp) and stamp > 0:
            lines.append("--Location reading from " + dt.datetime.fromtimestamp(stamp).strftime("%d %b %H:%M") + " | color=gray")
        url = "https://maps.apple.com/?" + urllib.parse.urlencode({"ll": f"{point[0]:.6f},{point[1]:.6f}", "q": "Tesla", "z": "17"})
        lines.append("--" + ("Open in Apple Maps" if current else "Open last known position in Apple Maps") + " | href=" + url)
    else:
        lines.append("--Location is not available yet | color=gray")
    if cache.get("location_error"):
        lines.append("--" + safe_text(cache["location_error"]) + " | color=gray")
    if config.get("location_map_enabled") is True:
        lines.append("--" + action("Hide map preview", "map-disable"))
    else:
        lines.extend(["--Map preview shares the map area with MapMap | color=gray",
                      "--" + action("Enable map preview", "map-enable")])
    lines.extend(["-----", "--" + action("Connect Tesla account…", "authorize", terminal=True),
                  "--" + action("Disable Location", "location-disable")])
    return lines


def clima_menu(cache, vehicle_action):
    climate = cache.get("climate") or {}
    current = status_is_current(cache, "climate")
    lines = ["Clima"]
    for line in status_menu_lines(cache):
        if "climate" in line.lower():
            lines.append("--" + line + " | color=gray")
    driver, passenger = climate.get("driver_temp_setting"), climate.get("passenger_temp_setting")
    label = "Target temperature" if current else "Last known target temperature"
    if number(driver) and number(passenger):
        value = f"{driver:g} °C" if driver == passenger else f"driver {driver:g} °C / passenger {passenger:g} °C"
        lines.append(f"--{label}: {value} | color=gray")
    for field, label in (("inside_temp", "Inside temperature"), ("outside_temp", "Outside temperature")):
        value = climate.get(field)
        if number(value):
            label = label if current else "Last known " + label.lower()
            lines.append(f"--{label}: {value:g} °C | color=gray")
        else:
            lines.append(f"--{label}: unavailable | color=gray")
    lines.append("-----")
    for command in ("climate-on", "climate-keep", "climate-camp", "climate-pet"):
        expected = CLIMATE_MODES.get(command, ("off",))[0]
        mode = "dog" if climate_mode(cache) == "pet" else climate_mode(cache)
        checked = current and mode == expected and climate.get("is_climate_on") is True
        label = ("✓ " if checked else "") + VEHICLE_COMMANDS[command][1]
        lines.append("--" + vehicle_action(label, "command", command))
    lines.extend(["--Set temperature (°C)", "----Both front zones | color=gray"])
    limits = temperature_limits(cache)
    if limits:
        for half_degrees in range(math.ceil(limits[0] * 2), math.floor(limits[1] * 2) + 1):
            temperature = half_degrees / 2
            checked = current and driver == temperature and passenger == temperature
            label = ("✓ " if checked else "") + f"{temperature:g} °C"
            lines.append("----" + vehicle_action(label, "command", "climate-set-temp", "--temperature", f"{temperature:g}"))
    else:
        lines.append("----Refresh vehicle data to load temperature limits | color=gray")
    lines.append("-----")
    for command in ("climate-mode-off", "climate-off"):
        lines.append("--" + vehicle_action(VEHICLE_COMMANDS[command][1], "command", command))
    return lines


def publish_display(cache, config, menu):
    """Publish a private text snapshot for the fast renderer, without credentials."""
    pulse_until = (cache.get("updated_at", 0) + STALE_AFTER_SECONDS
                   if charging_is_current(cache, config) else 0)
    fd, temporary = tempfile.mkstemp(prefix=".display-", dir=runtime.APP_DIR)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(f"TESLA_XBAR_DISPLAY_V1 {pulse_until:.0f}\n{menu}\n")
        os.replace(temporary, runtime.APP_DIR / "display.txt")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render(cache, config, demo=False):
    charge = cache.get("charge") or {}
    level = charge.get("battery_level")
    level = level if number(level) and 0 <= level <= 100 else None
    now = time.time()
    stale = now - cache.get("updated_at", 0) >= STALE_AFTER_SECONDS
    offline = cache.get("state") != "online"
    unverified = offline or stale or bool(cache.get("error"))
    charging = charging_is_current(cache, config)
    connected = cable_connected(charge)
    color = battery_color(cache)
    distance = vehicle_range(cache)
    value = (f"{level:g}%" if level is not None else None) if config.get("display_mode") == "percent" else distance
    top = f"{'DEMO ' if demo else ''}{value if value is not None else '—'}"
    if cache.get("state") in ("offline", "asleep"):
        top += " ·"
    params = [f"color={color}"] if color else []
    icon_image = status_icon_image(active_status_icons(cache))
    if icon_image:
        params.append(f"templateImage={icon_image}")
    lines = [top + (" | " + " ".join(params) if params else ""), "---",
             safe_text(cache.get("name", "Tesla xBar")) + " | size=15"]
    if level is not None:
        lines.append(f"Battery: {level:g} %")
        if distance is not None:
            lines.append(f"Tesla range: {distance}")
        elif config.get("display_mode") != "percent":
            lines.append("Range or distance units are not available yet. | color=gray")
        if number(charge.get("charge_limit_soc")):
            lines.append(f"Charge limit: {charge['charge_limit_soc']:g} %")
        if connected is not None:
            lines.append(("Last known cable state: " if unverified else "Cable: ")
                         + ("connected" if connected else "disconnected"))
        labels = {"Charging": "Charging", "Complete": "Charge complete", "Stopped": "Charging stopped", "Disconnected": "Disconnected", "NoPower": "No power"}
        state = labels.get(charge.get("charging_state"), "Unknown charging state")
        lines.append(("Last known state: " if unverified else "") + state)
        if charging and number(charge.get("charger_power")):
            lines.append(f"Power: {charge['charger_power']:g} kW")
        if charging:
            minutes = charge.get("minutes_to_full_charge")
            if not number(minutes) and number(charge.get("time_to_full_charge")):
                minutes = charge["time_to_full_charge"] * 60
            if number(minutes) and minutes > 0:
                lines.append(f"Time to charge limit: {int(minutes) // 60} h {int(minutes) % 60:02d} min")
        stamp = dt.datetime.fromtimestamp(cache.get("updated_at", 0)).strftime("%d %b %H:%M")
        lines.append(f"Battery reading from {stamp} | color=gray")
    else:
        lines.append("Battery data is not available yet.")
    lines.extend(status_menu_lines(cache))
    if cache.get("state") == "asleep":
        lines.append("Vehicle asleep • last known data | color=gray")
    elif cache.get("state") == "offline":
        lines.append("Vehicle offline • last known data | color=gray")
    elif offline and cache.get("state"):
        lines.append("Vehicle connection unverified • last known data | color=gray")
    if cache.get("error"):
        lines.extend(["---", safe_text(cache["error"]) + " | color=#D9534F"])
    if cache.get("wake_in_progress"):
        lines.append("Waking the vehicle and waiting for it to connect… | color=gray")
    if unverified and value is not None and connected is True:
        lines.append("Green text reflects the last known cable connection. | color=gray")
    report = read_json("command-result.json")
    if report and report.get("vin") in (None, cache.get("vin")):
        stamp = dt.datetime.fromtimestamp(report.get("at", 0)).strftime("%H:%M")
        color = "#D9534F" if report.get("status") == "error" else "gray"
        lines.extend(["---", safe_text(report.get("message", "")) + f" ({stamp}) | color={color}"])
    notice = read_json("action-notice.json")
    if notice and notice.get("vin") in (None, cache.get("vin")):
        stamp = dt.datetime.fromtimestamp(notice.get("at", 0)).strftime("%H:%M")
        lines.extend(["---", safe_text(notice.get("message", "")) + f" ({stamp}) | color=#D9534F"])
    def vehicle_action(label, command, *args):
        vin = cache.get("vin")
        return action(label, command, *args, "--vin", vin) if vin else label + " | color=gray"

    lines.extend(["---", "Charging and port"])
    setup = read_json("command-setup.json")
    if setup.get("vin") == cache.get("vin") and setup.get("signing_required") and not setup.get("key_paired"):
        lines.append("--First add the app key to your vehicle | color=gray")
    for command, (_, label, _) in VEHICLE_COMMANDS.items():
        if command.startswith(("charge-", "port-")):
            lines.append("--" + vehicle_action(label, "command", command))
    domain = config.get("domain", "")
    if domain and "/" not in domain and ":" not in domain:
        lines.append("--Add key to vehicle… | href=https://www.tesla.com/_ak/" + domain)
    lines.append("--" + vehicle_action("Check command setup", "command-setup"))
    lines.extend(locks_trunks_menu(cache, vehicle_action))
    lines.extend(clima_menu(cache, vehicle_action))
    lines.extend(sentry_menu(cache, vehicle_action))
    lines.extend(location_menu(cache, config))
    lines.extend(["---", "Refresh now | refresh=true",
                  vehicle_action("Wake vehicle and refresh", "wake-refresh"),
                  action("Connect Tesla account…", "authorize", terminal=True),
                  action("Settings…", "configure", terminal=True)])
    lines.append("Menu bar display")
    for mode, label in SETTINGS["display_mode"].choices:
        prefix = "✓ " if config.get("display_mode", "range") == mode else ""
        lines.append("--" + action(prefix + label, "display", mode))
    if len(cache.get("vehicles", [])) > 1:
        lines.append("Select vehicle")
        for vehicle in cache["vehicles"]:
            label = ("✓ " if vehicle["vin"] == cache.get("vin") else "") + safe_text(vehicle["name"])
            lines.append("--" + action(label, "select", vehicle["vin"]))
    lines.extend(["---", "Refresh interval managed by xBar | color=gray",
                  "Tesla Developer | href=https://developer.tesla.com",
                  "Manage Tesla permissions | href=https://www.tesla.com/teslaaccount/settings/security"])
    return "\n".join(lines)
