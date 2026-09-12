"""Pure xBar text rendering from a prepared context. No external effects."""
import base64
import datetime as dt
import json
import math
import urllib.parse
from ..application.ports import MenuContext
from ..domain.settings import SETTINGS
from ..domain.models import CLIMATE_MODES, LOCK_TRUNK_COMMANDS, STALE_AFTER_SECONDS, COMMAND_LABELS, battery_color, cable_connected, charging_is_current, climate_mode, number, status_is_current, temperature_limits, trunk_open_state, vehicle_range
from ..domain.location import coordinates

def safe_text(value):
    value = str(value).replace("|", "¦")
    value = " ".join(value.split())
    value = "".join(c for c in value if c.isprintable())
    return value.lstrip("-")[:180]

class MenuRenderer:
    def __init__(self, context: MenuContext):
        self.context = context

    def action(self, label, command, *args, terminal=False):
        launcher = self.context.launcher
        params = " ".join(f"param{i}={json.dumps(str(arg))}" for i, arg in enumerate((command,) + args, 1))
        return f'{label} | shell={json.dumps(str(launcher))} {params} terminal={str(terminal).lower()} refresh=true'

    def status_menu_lines(self, cache):
        lines = []
        climate = cache.get("climate") or {}
        current = status_is_current(cache, "climate", now=self.context.now)
        mode = {"camp": "Camp Mode", "dog": "Pet Mode", "pet": "Pet Mode", "on": "Keep Climate On", "off": "Off"}.get(climate_mode(cache))
        if mode is not None:
            label = "Climate mode" if current else "Last known climate mode"
            lines.append(f"{label}: {mode}")
        if isinstance(climate.get("is_climate_on"), bool):
            label = "Climate" if current else "Last known climate"
            lines.append(f"{label}: {'on' if climate['is_climate_on'] else 'off'}")
        vehicle = cache.get("vehicle_status") or {}
        if isinstance(vehicle.get("locked"), bool):
            label = "Vehicle" if status_is_current(cache, "vehicle_status", now=self.context.now) else "Last known vehicle lock"
            lines.append(f"{label}: {'locked' if vehicle['locked'] else 'unlocked'}")
        return lines

    def sentry_menu(self, cache, vehicle_action):
        state = (cache.get("vehicle_status") or {}).get("sentry_mode")
        current = status_is_current(cache, "vehicle_status", now=self.context.now)
        label = "Sentry" if current else "Last known Sentry"
        value = ("on" if state else "off") if isinstance(state, bool) else "unavailable"
        lines = ["Sentry", f"--{label}: {value} | color=gray", "-----"]
        for command in ("sentry-on", "sentry-off"):
            checked = current and state is (command == "sentry-on")
            label = ("✓ " if checked else "") + COMMAND_LABELS[command]
            lines.append("--" + vehicle_action(label, "command", command))
        return lines

    def locks_trunks_menu(self, cache, vehicle_action):
        status = cache.get("vehicle_status") or {}
        current = status_is_current(cache, "vehicle_status", now=self.context.now)
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
            lines.append("--" + vehicle_action(COMMAND_LABELS[command], "command", command))
        lines.append("--Rear trunk closing depends on vehicle support. | color=gray")
        return lines

    def location_menu(self, cache, config):
        lines = ["Location"]
        if config.get("location_enabled") is not True:
            lines.extend(["--Location is disabled | color=gray",
                          "--Address lookup shares vehicle coordinates with Apple | color=gray",
                          "--" + self.action("Enable Location…", "location-enable", terminal=True)])
            return lines
        location = cache.get("location") or {}
        point = coordinates(location)
        current = status_is_current(cache, "location", now=self.context.now) and not cache.get("location_error")
        if point is not None:
            if config.get("location_map_enabled") is True:
                png = self.context.map_image
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
            lines.append("--" + self.action("Hide map preview", "map-disable"))
        else:
            lines.extend(["--Map preview shares the map area with MapMap | color=gray",
                          "--" + self.action("Enable map preview", "map-enable")])
        lines.extend(["-----", "--" + self.action("Connect Tesla account…", "authorize", terminal=True),
                      "--" + self.action("Disable Location", "location-disable")])
        return lines

    def clima_menu(self, cache, vehicle_action):
        climate = cache.get("climate") or {}
        current = status_is_current(cache, "climate", now=self.context.now)
        lines = ["Clima"]
        for line in self.status_menu_lines(cache):
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
            expected = CLIMATE_MODES.get(command, "off")
            mode = "dog" if climate_mode(cache) == "pet" else climate_mode(cache)
            checked = current and mode == expected and climate.get("is_climate_on") is True
            label = ("✓ " if checked else "") + COMMAND_LABELS[command]
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
            lines.append("--" + vehicle_action(COMMAND_LABELS[command], "command", command))
        return lines

    def render(self, cache, config, demo=False):
        charge = cache.get("charge") or {}
        level = charge.get("battery_level")
        level = level if number(level) and 0 <= level <= 100 else None
        now = self.context.now
        stale = now - cache.get("updated_at", 0) >= STALE_AFTER_SECONDS
        offline = cache.get("state") != "online"
        unverified = offline or stale or bool(cache.get("error"))
        charging = charging_is_current(cache, now=self.context.now)
        connected = cable_connected(charge)
        color = battery_color(cache)
        distance = vehicle_range(cache)
        value = (f"{level:g}%" if level is not None else None) if config.get("display_mode") == "percent" else distance
        top = f"{'DEMO ' if demo else ''}{value if value is not None else '—'}"
        if cache.get("state") in ("offline", "asleep"):
            top += " ·"
        params = [f"color={color}"] if color else []
        icon_image = base64.b64encode(self.context.icon_image).decode("ascii") if self.context.icon_image else ""
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
        lines.extend(self.status_menu_lines(cache))
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
        report = self.context.report
        if report and report.get("vin") in (None, cache.get("vin")):
            stamp = dt.datetime.fromtimestamp(report.get("at", 0)).strftime("%H:%M")
            color = "#D9534F" if report.get("status") == "error" else "gray"
            lines.extend(["---", safe_text(report.get("message", "")) + f" ({stamp}) | color={color}"])
        notice = self.context.notice
        if notice and notice.get("vin") in (None, cache.get("vin")):
            stamp = dt.datetime.fromtimestamp(notice.get("at", 0)).strftime("%H:%M")
            lines.extend(["---", safe_text(notice.get("message", "")) + f" ({stamp}) | color=#D9534F"])
        def vehicle_action(label, command, *args):
            vin = cache.get("vin")
            return self.action(label, command, *args, "--vin", vin) if vin else label + " | color=gray"

        lines.extend(["---", "Charging and port"])
        setup = self.context.setup
        if setup.get("vin") == cache.get("vin") and setup.get("pairing_required"):
            lines.append("--First add the app key to your vehicle | color=gray")
        for command, label in COMMAND_LABELS.items():
            if command.startswith(("charge-", "port-")):
                lines.append("--" + vehicle_action(label, "command", command))
        domain = config.get("domain", "")
        if domain and "/" not in domain and ":" not in domain:
            lines.append("--Add key to vehicle… | href=https://www.tesla.com/_ak/" + domain)
        lines.append("--" + vehicle_action("Check command setup", "command-setup"))
        lines.extend(self.locks_trunks_menu(cache, vehicle_action))
        lines.extend(self.clima_menu(cache, vehicle_action))
        lines.extend(self.sentry_menu(cache, vehicle_action))
        lines.extend(self.location_menu(cache, config))
        lines.extend(["---", "Refresh now | refresh=true",
                      vehicle_action("Wake vehicle and refresh", "wake-refresh"),
                      self.action("Connect Tesla account…", "authorize", terminal=True),
                      self.action("Settings…", "configure", terminal=True)])
        lines.append("Menu bar display")
        for mode, label in SETTINGS["display_mode"].choices:
            prefix = "✓ " if config.get("display_mode", "range") == mode else ""
            lines.append("--" + self.action(prefix + label, "display", mode))
        if len(cache.get("vehicles", [])) > 1:
            lines.append("Select vehicle")
            for vehicle in cache["vehicles"]:
                label = ("✓ " if vehicle["vin"] == cache.get("vin") else "") + safe_text(vehicle["name"])
                lines.append("--" + self.action(label, "select", vehicle["vin"]))
        lines.extend(["---", "Refresh interval managed by xBar | color=gray",
                      "Tesla Developer | href=https://developer.tesla.com",
                      "Manage Tesla permissions | href=https://www.tesla.com/teslaaccount/settings/security"])
        return "\n".join(lines)
