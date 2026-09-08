#!/usr/bin/env python3
"""Tesla Fleet API battery indicator for xBar. Python standard library only."""
import argparse
import base64
import contextlib
import datetime as dt
import email.utils
import fcntl
import getpass
import html
import http.server
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

APP_DIR = Path(os.environ.get("TESLA_XBAR_HOME", Path.home() / "Library/Application Support/Tesla xBar"))
HERE = Path(__file__).resolve().parent
REGIONS = {r: f"https://fleet-api.prd.{r}.vn.cloud.tesla.com" for r in ("eu", "na", "cn")}
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
AUTH_URL = "https://auth.tesla.com/oauth2/v3/authorize"
SCOPES = "openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds"
REDIRECT = "http://localhost:8765/callback"
DEFAULTS = {"region": "eu", "redirect_uri": REDIRECT, "display_mode": "range"}
STALE_AFTER_SECONDS = 30 * 60
VEHICLE_COMMANDS = {
    "charge-start": ("charging-start", "Start charging", "charge_start"),
    "charge-stop": ("charging-stop", "Stop charging", "charge_stop"),
    "port-open": ("charge-port-open", "Open charge port", "charge_port_door_open"),
    "port-close": ("charge-port-close", "Close charge port", "charge_port_door_close"),
}


class AppError(Exception):
    pass


class APIError(AppError):
    def __init__(self, status, retry_after=0):
        self.status = status
        self.retry_after = retry_after
        messages = {401: "Your session has expired. Connect your Tesla account again.",
                    402: "Set up billing in the Tesla Developer portal.",
                    403: "Tesla denied access. Check the app permissions and registration.",
                    404: "Vehicle or registration not found.",
                    408: "The vehicle is unavailable or asleep.",
                    412: "Complete the app registration in the EU region.",
                    421: "Your account is in another region. Change the region in Settings.",
                    429: "Tesla rate limit reached. Refresh has been postponed."}
        super().__init__(messages.get(status, f"Tesla API: HTTP error {status}."))


def read_json(name, default=None):
    try:
        value = json.loads((APP_DIR / name).read_text())
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def save_json(name, value):
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=APP_DIR)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, APP_DIR / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(blocking=True):
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (APP_DIR / "app.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Keychain:
    def request(self, operation, account, value=None):
        payload = {"operation": operation, "account": account}
        if value is not None:
            payload["value"] = value
        result = subprocess.run([str(HERE / "tesla-keychain")], input=json.dumps(payload),
                                capture_output=True, text=True, timeout=90)
        if result.returncode == 3:
            return None
        if result.returncode:
            raise AppError("Keychain is unavailable. Unlock it and try again.")
        return result.stdout

    def get(self, account):
        return self.request("get", account)

    def set(self, account, value):
        self.request("set", account, value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward bearer tokens or secrets across redirects.


def request_json(url, *, token=None, form=None, body=None):
    headers = {"Accept": "application/json", "User-Agent": "Tesla-xBar/1.0"}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.build_opener(NoRedirect).open(
                urllib.request.Request(url, data=data, headers=headers), timeout=18) as response:
            result = json.load(response)
            if not isinstance(result, dict):
                raise AppError("Tesla returned an unexpected response.")
            return result
    except urllib.error.HTTPError as exc:
        raise APIError(exc.code, retry_after_seconds(exc.headers.get("Retry-After", ""))) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AppError("Network unavailable. Showing the last known reading.") from None
    except (ValueError, TypeError):
        raise AppError("Tesla returned invalid data.") from None


def retry_after_seconds(value):
    """Honor Tesla's delay (seconds or HTTP date), without a local minimum."""
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0  # Without a usable header, retry on the next xBar run.


def configuration():
    config = DEFAULTS | read_json("config.json")
    config.pop("poll_minutes", None)  # Scheduling belongs exclusively to xBar.
    if config.get("region") not in REGIONS:
        raise AppError("Invalid region in Settings.")
    return config


def reset_after_authorization():
    # A scope upgrade must not erase the last reading while the car is asleep.
    # The next vehicle-list response still checks the VIN before reusing it.
    cache = read_json("cache.json")
    for key in ("next_poll", "retry_at", "retry_status", "error", "wake_in_progress"):
        cache.pop(key, None)
    cache["state"] = "unknown"
    save_json("cache.json", cache)


class Client:
    def __init__(self, config, vault=None):
        self.config = config
        self.vault = vault or Keychain()

    def save_tokens(self, result, previous=None):
        if not result.get("access_token") or not (result.get("refresh_token") or (previous or {}).get("refresh_token")):
            raise AppError("Tesla did not return the required tokens. Allow offline access.")
        stored = {"access_token": result["access_token"],
                  "refresh_token": result.get("refresh_token") or previous["refresh_token"],
                  "expires_at": time.time() + float(result.get("expires_in", 3600))}
        # Save rotated refresh token before making any subsequent request.
        self.vault.set("oauth", json.dumps(stored))
        return stored

    def access_token(self, force=False):
        raw = self.vault.get("oauth")
        if not raw:
            raise AppError("Connect your Tesla account from the plugin menu.")
        tokens = json.loads(raw)
        if not force and tokens.get("expires_at", 0) > time.time() + 120:
            return tokens["access_token"]
        result = request_json(TOKEN_URL, form={"grant_type": "refresh_token",
            "client_id": self.config["client_id"], "refresh_token": tokens["refresh_token"]})
        return self.save_tokens(result, tokens)["access_token"]

    def get(self, path):
        return self.request(path)

    def wake(self, vin):
        path = "/api/1/vehicles/" + urllib.parse.quote(vin, safe="") + "/wake_up"
        return self.request(path, body={})

    def granted_scopes(self):
        # Used only to explain missing consent; Tesla validates authorization.
        try:
            part = self.access_token().split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            scopes = payload.get("scp", payload.get("scope", []))
            return set(scopes.split() if isinstance(scopes, str) else scopes)
        except (ValueError, IndexError, TypeError):
            return set()

    def command_capabilities(self, vin):
        response = self.request("/api/1/vehicles/fleet_status", body={"vins": [vin]}).get("response", {})
        info = response.get("vehicle_info", {}).get(vin, {})
        required = info.get("vehicle_command_protocol_required")
        if not isinstance(required, bool):
            raise AppError("Tesla did not confirm the command authorization method for this vehicle.")
        return {"vin": vin, "signing_required": required,
                "key_paired": vin in response.get("key_paired_vins", []),
                "charging_authorized": "vehicle_charging_cmds" in self.granted_scopes()}

    def vehicle_command(self, vin, command, capabilities):
        if command not in VEHICLE_COMMANDS:
            raise AppError("Unsupported command.")
        cli_command, _, endpoint = VEHICLE_COMMANDS[command]
        if not capabilities["signing_required"]:
            path = "/api/1/vehicles/" + urllib.parse.quote(vin, safe="") + "/command/" + endpoint
            response = self.request(path, body={}).get("response", {})
            if response.get("result") is not True:
                raise AppError(command_error(str(response.get("reason", ""))))
            return
        if not capabilities["key_paired"]:
            raise AppError("First add the app key to your vehicle using the Tesla mobile app.")
        binary, key = HERE / "tesla-control", APP_DIR / "command-key.pem"
        if not binary.is_file() or not key.is_file():
            raise AppError("The command signing helper is not installed.")
        token = self.access_token()
        args = [str(binary), "-token-file", "/dev/stdin", "-key-file", str(key),
                "-vin", vin, "-session-cache", str(APP_DIR / "command-sessions.json"),
                "-connect-timeout", "20s", "-command-timeout", "15s", cli_command]
        # Tokens go through a pipe, never argv, environment or a temporary file.
        env = {k: v for k, v in os.environ.items() if not k.startswith("TESLA_")}
        env["TESLA_VERBOSE"] = "false"
        try:
            result = subprocess.run(args, input=token, capture_output=True, text=True,
                                    timeout=45, env=env, umask=0o077)
        except subprocess.TimeoutExpired:
            raise AppError("The command result is unconfirmed. Check the vehicle status; the command will not be retried automatically.") from None
        if result.returncode:
            # The SDK may include sensitive context in errors. Never show raw output.
            raise AppError(command_error(result.stderr + result.stdout))

    def request(self, path, body=None):
        for attempt in range(2):
            token = self.access_token(force=attempt == 1)
            try:
                return request_json(REGIONS[self.config["region"]] + path, token=token, **({"body": body} if body is not None else {}))
            except APIError as exc:
                if exc.status != 401 or attempt:
                    raise


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def command_error(text):
    value = text.lower()
    for needles, message in (
        (("has not been paired", "not on whitelist", "unknown key"), "First add the app key to your vehicle using the Tesla mobile app."),
        (("403", "forbidden", "insufficient scope"), "Tesla denied the command. Allow Vehicle Charging Management via Connect Tesla account."),
        (("401", "unauthorized"), "Your session has expired. Connect your Tesla account again."),
        (("no_power", "no power"), "The charger is not supplying power."),
        (("disconnected",), "The charging cable is disconnected."),
        (("not_charging", "not charging"), "The vehicle is not charging."),
        (("is_charging", "already charging"), "The vehicle is already charging."),
        (("complete",), "Charging has reached the set limit."),
        (("cable connected",), "Disconnect the cable before closing the charge port."),
        (("not allowed", "not in park"), "The vehicle does not allow this command in its current state."),
    ):
        if any(needle in value for needle in needles):
            return message
    return "The command was not confirmed. Check the vehicle status; the command will not be retried automatically."


def fetch_state(config, client=None):
    cache = read_json("cache.json")
    now = time.time()
    cache.pop("next_poll", None)
    if cache.get("retry_status") == 429 and now < cache.get("retry_at", 0):
        return cache
    client = client or Client(config)
    cache.pop("retry_at", None)
    cache.pop("retry_status", None)
    cache["vehicle_verified"] = False
    try:
        vehicles = client.get("/api/1/vehicles").get("response")
        if not isinstance(vehicles, list):
            raise AppError("Tesla did not provide the vehicle list.")
        vehicles = [v for v in vehicles if isinstance(v, dict) and v.get("vin")]
        cache["vehicles"] = [{"vin": v["vin"], "name": v.get("display_name") or "Tesla"} for v in vehicles]
        vin = config.get("vin") or cache.get("vin") or cache.get("selected_vin")
        selected = next((v for v in vehicles if v["vin"] == vin), None) if vin else (vehicles[0] if len(vehicles) == 1 else None)
        if selected is None:
            # Do not attribute the old battery reading to a different/revoked vehicle.
            cache = {"vehicles": cache["vehicles"], "selected_vin": vin, "vehicle_verified": False}
            if not vin and len(vehicles) > 1:
                raise AppError("Select a vehicle from the plugin menu.")
            raise AppError("The selected Tesla is unavailable. Connect your account or select a vehicle.")
        if cache.get("vin") != selected["vin"]:
            cache = {"vehicles": cache["vehicles"]}
        cache.update(vin=selected["vin"], name=selected.get("display_name") or "Tesla",
                     selected_vin=selected["vin"], vehicle_verified=True,
                     state=selected.get("state", "unknown"), checked_at=now)
        cache.pop("error", None)
        cache.pop("retry_at", None)
        cache.pop("retry_status", None)
        if cache["state"] == "online":
            path = "/api/1/vehicles/" + urllib.parse.quote(selected["vin"], safe="") + "/vehicle_data?endpoints=charge_state%3Bgui_settings"
            response = client.get(path).get("response")
            charge = response.get("charge_state") if isinstance(response, dict) else None
            if not isinstance(charge, dict) or not number(charge.get("battery_level")) or not 0 <= charge["battery_level"] <= 100:
                raise AppError("Tesla has not provided battery data yet.")
            # Keep charging fields and display preferences, never the full response.
            keys = ("battery_level", "usable_battery_level", "battery_range", "ideal_battery_range", "charge_limit_soc",
                    "charging_state", "conn_charge_cable", "charger_power", "minutes_to_full_charge", "time_to_full_charge",
                    "charge_port_door_open")
            cache["charge"] = {key: charge[key] for key in keys if key in charge}
            gui = response.get("gui_settings")
            cache["gui_settings"] = {key: gui[key] for key in ("gui_distance_units", "gui_range_display")
                                     if key in gui} if isinstance(gui, dict) else {}
            timestamp = charge.get("timestamp")
            cache["updated_at"] = min(now, timestamp / 1000) if number(timestamp) and timestamp > 0 else now
    except AppError as exc:
        cache["error"] = str(exc)
        cache["retry_status"] = exc.status if isinstance(exc, APIError) else None
        if isinstance(exc, APIError) and exc.status == 429:
            cache["retry_at"] = time.time() + exc.retry_after
        if isinstance(exc, APIError) and exc.status == 408:
            cache["state"] = "offline"  # Unavailable is not proof of sleep.
    save_json("cache.json", cache)
    return cache


def wake_and_refresh(config, client=None, timeout=90):
    """Explicit menu action only. Send at most one wake request, then read status."""
    config = pinned_vehicle_config(config)
    client = client or Client(config)
    cache = fetch_state(config, client=client)
    if cache.get("error") and cache.get("retry_status") == 408 and cache.get("vehicle_verified"):
        cache.pop("error", None)
        cache.pop("retry_at", None)
        cache.pop("retry_status", None)
    if cache.get("error") or cache.get("state") == "online" or not cache.get("vin"):
        return cache
    vin = cache["vin"]
    cache["wake_in_progress"] = True
    save_json("cache.json", cache)
    try:
        result = client.wake(vin).get("response")
        if not isinstance(result, dict) or not result.get("state"):
            raise AppError("Tesla did not confirm the wake request. Try again later.")
        deadline = time.monotonic() + timeout
        while result.get("state") != "online":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppError("The vehicle did not connect. Showing the last known reading; try again later.")
            time.sleep(min(5, remaining))
            if time.monotonic() >= deadline:
                raise AppError("The vehicle did not connect. Showing the last known reading; try again later.")
            result = client.get("/api/1/vehicles/" + urllib.parse.quote(vin, safe="")).get("response")
            if not isinstance(result, dict):
                raise AppError("Tesla has not provided the vehicle connection status yet.")
        # Pin the same vehicle for the final read even if the vehicle list changes.
        cache = fetch_state(config | {"vin": vin}, client=client)
        if cache.get("state") != "online" and not cache.get("error"):
            cache["error"] = "The vehicle has not provided fresh data after waking. Showing the last known range."
    except AppError as exc:
        cache["error"] = ("Waking requires the Vehicle Commands permission. Connect your Tesla account again."
                          if isinstance(exc, APIError) and exc.status == 403 else str(exc))
        if isinstance(exc, APIError) and exc.status == 429:
            cache["retry_at"] = time.time() + exc.retry_after
            cache["retry_status"] = 429
    finally:
        cache.pop("wake_in_progress", None)
        save_json("cache.json", cache)
    return cache


def safe_text(value):
    value = str(value).replace("|", "¦")
    value = " ".join(value.split())
    value = "".join(c for c in value if c.isprintable())
    return value.lstrip("-")[:180]


def command_setup(config, client=None):
    config = pinned_vehicle_config(config)
    client = client or Client(config)
    cache = fetch_state(config, client=client)
    if not cache.get("vehicle_verified") or not cache.get("vin") or (cache.get("error") and cache.get("retry_status") != 408):
        raise AppError(cache.get("error", "Select a vehicle first."))
    capabilities = client.command_capabilities(cache["vin"])
    save_json("command-setup.json", capabilities)
    return capabilities


def run_vehicle_command(config, command, client=None):
    """Explicit menu action only. Validate current vehicle, consent and key first."""
    if command not in VEHICLE_COMMANDS:
        raise AppError("Unsupported command.")
    client = client or Client(config)
    previous = read_json("cache.json")
    report = {"vin": previous.get("vin"), "command": command, "at": time.time(),
              "message": "Running: " + VEHICLE_COMMANDS[command][1], "status": "pending"}
    save_json("command-result.json", report)
    try:
        config = pinned_vehicle_config(config)
        capabilities = command_setup(config, client=client)
        vin = capabilities["vin"]
        report["vin"] = vin
        if command.startswith("charge-") and not capabilities["charging_authorized"]:
            raise AppError("Allow Vehicle Charging Management via Connect Tesla account.")
        if capabilities["signing_required"] and not capabilities["key_paired"]:
            raise AppError("First add the app key to your vehicle using the Tesla mobile app.")
        cache = read_json("cache.json")
        if cache.get("state") != "online":
            cache = wake_and_refresh(config | {"vin": vin}, client=client)
        if cache.get("error") or cache.get("state") != "online":
            raise AppError(cache.get("error", "The vehicle is unavailable."))
        charge = cache.get("charge") or {}
        connected = cable_connected(charge)
        if command == "charge-start" and connected is not True:
            raise AppError("Tesla has not confirmed that the charging cable is connected.")
        if command == "port-close" and connected is not False:
            raise AppError("Disconnect the cable before closing the charge port.")
        already_done = ((command == "charge-start" and charge.get("charging_state") == "Charging")
                        or (command == "charge-stop" and charge.get("charging_state") in ("Stopped", "Complete", "Disconnected", "NoPower")))
        if already_done:
            message = "The vehicle is already charging." if command == "charge-start" else "Charging is already stopped."
        else:
            client.vehicle_command(vin, command, capabilities)
            message = "Command accepted: " + VEHICLE_COMMANDS[command][1]
            fresh = fetch_state(config | {"vin": vin}, client=client)
            state = fresh.get("charge", {}).get("charging_state")
            if not fresh.get("error") and fresh.get("state") == "online":
                if command == "charge-start" and state == "Charging":
                    message = "Charging started • confirmed by the vehicle."
                elif command == "charge-stop" and state in ("Stopped", "Complete", "Disconnected", "NoPower"):
                    message = "Charging stopped • confirmed by the vehicle."
        report.update(status="success", message=message)
    except (AppError, OSError, subprocess.SubprocessError) as exc:
        report.update(status="error", message=str(exc) if isinstance(exc, AppError) else "The command could not be completed.")
    finally:
        report["at"] = time.time()
        save_json("command-result.json", report)
    return read_json("cache.json")


def pinned_vehicle_config(config, menu_vin=None):
    """Keep a manual action on the displayed vehicle, including after list changes."""
    cache = read_json("cache.json")
    selected = config.get("vin") or cache.get("vin") or cache.get("selected_vin")
    if menu_vin and selected and menu_vin != selected:
        raise AppError("The selected vehicle has changed. Refresh the menu and try again.")
    vin = menu_vin or selected
    if not vin:
        raise AppError("Refresh the data and select a vehicle from the plugin menu first.")
    return config | {"vin": vin}


def action(label, command, *args, terminal=False):
    launcher = APP_DIR / "tesla-action.sh"
    params = " ".join(f"param{i}={json.dumps(str(arg))}" for i, arg in enumerate((command,) + args, 1))
    return f'{label} | shell={json.dumps(str(launcher))} {params} terminal={str(terminal).lower()} refresh=true'


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


def charging_is_current(cache, config):
    fresh_until = cache.get("updated_at", 0) + STALE_AFTER_SECONDS
    return (cache.get("charge", {}).get("charging_state") == "Charging"
            and cache.get("state") == "online" and not cache.get("error")
            and time.time() < fresh_until)


def publish_display(cache, config, menu):
    """Publish a private text snapshot for the fast renderer, without credentials."""
    pulse_until = (cache.get("updated_at", 0) + STALE_AFTER_SECONDS
                   if charging_is_current(cache, config) else 0)
    fd, temporary = tempfile.mkstemp(prefix=".display-", dir=APP_DIR)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(f"TESLA_XBAR_DISPLAY_V1 {pulse_until:.0f}\n{menu}\n")
        os.replace(temporary, APP_DIR / "display.txt")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render(cache, config, demo=False):
    charge = cache.get("charge") or {}
    level = charge.get("battery_level")
    level = level if number(level) and 0 <= level <= 100 else None
    now = time.time()
    stale = now - cache.get("updated_at", 0) > STALE_AFTER_SECONDS
    offline = cache.get("state") != "online"
    charging = charging_is_current(cache, config)
    suffix = " ⚡" if charging else {"asleep": " ☾", "offline": " ⛓️‍💥"}.get(cache.get("state"), "")
    if (stale or cache.get("error")) and level is not None:
        suffix += " ·"
    color = battery_color(cache)
    distance = vehicle_range(cache)
    value = (f"{level:g}%" if level is not None else None) if config.get("display_mode") == "percent" else distance
    top = f"{'DEMO ' if demo else ''}{value if value is not None else '—'}{suffix}"
    lines = [top + (f" | color={color}" if color else ""), "---",
             safe_text(cache.get("name", "Tesla xBar")) + " | size=15"]
    if level is not None:
        lines.append(f"Battery: {level:g} %")
        if distance is not None:
            lines.append(f"Tesla range: {distance}")
        elif config.get("display_mode") != "percent":
            lines.append("Range or distance units are not available yet. | color=gray")
        if number(charge.get("charge_limit_soc")):
            lines.append(f"Charge limit: {charge['charge_limit_soc']:g} %")
        connected = cable_connected(charge)
        if connected is not None:
            lines.append(("Last known cable state: " if offline or stale or cache.get("error") else "Cable: ")
                         + ("connected" if connected else "disconnected"))
        labels = {"Charging": "Charging", "Complete": "Charge complete", "Stopped": "Charging stopped", "Disconnected": "Disconnected", "NoPower": "No power"}
        state = labels.get(charge.get("charging_state"), "Unknown charging state")
        lines.append(("Last known state: " if offline or stale or cache.get("error") else "") + state)
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
    if cache.get("state") == "asleep":
        lines.append("Vehicle asleep • last known data | color=gray")
    elif cache.get("state") == "offline":
        lines.append("⛓️‍💥 Vehicle offline • last known data | color=gray")
    elif offline and cache.get("state"):
        lines.append("Vehicle connection unverified • last known data | color=gray")
    if cache.get("error"):
        lines.extend(["---", safe_text(cache["error"]) + " | color=#D9534F"])
    if cache.get("wake_in_progress"):
        lines.append("Waking the vehicle and waiting for it to connect… | color=gray")
    if stale and level is not None:
        lines.append("The dot marks an old or unverified reading. | color=gray")
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
        lines.append("--" + vehicle_action(label, "command", command))
    domain = config.get("domain", "")
    if domain and "/" not in domain and ":" not in domain:
        lines.append("--Add key to vehicle… | href=https://www.tesla.com/_ak/" + domain)
    lines.append("--" + vehicle_action("Check command setup", "command-setup"))
    lines.extend(["---", "Refresh now | refresh=true",
                  vehicle_action("Wake vehicle and refresh", "wake-refresh"),
                  action("Connect Tesla account…", "authorize", terminal=True),
                  action("Settings…", "configure", terminal=True)])
    lines.append("Menu bar display")
    for mode, label in (("range", "Range"), ("percent", "Percentage")):
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


def configure():
    print("Tesla xBar • Settings\nFind your Client ID and Client Secret in the Tesla Developer portal.")
    config = configuration()
    client_id = input(f"Client ID [{config.get('client_id', '')}]: ").strip() or config.get("client_id")
    if not client_id:
        raise AppError("Client ID is required.")
    secret = getpass.getpass("Client Secret (press Enter to keep the saved value): ").strip()
    domain = input(f"Public key domain [{config.get('domain', '')}]: ").strip() or config.get("domain", "")
    domain = domain.removeprefix("https://").rstrip("/")
    if not domain or "/" in domain or ":" in domain or "." not in domain:
        raise AppError("Enter only the public HTTPS domain name.")
    region = input(f"Region eu/na/cn [{config['region']}]: ").strip() or config["region"]
    if region not in REGIONS:
        raise AppError("Invalid region.")
    redirect = input(f"Redirect URI [{config['redirect_uri']}]: ").strip() or config["redirect_uri"]
    parsed = urllib.parse.urlsplit(redirect)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or not parsed.port:
        raise AppError("Use a local callback, such as http://localhost:8765/callback.")
    if parsed.path != "/callback" or parsed.query or parsed.fragment or parsed.username:
        raise AppError("The callback must end with /callback and have no query parameters.")
    with locked():
        vault = Keychain()
        if secret:
            vault.set("client-secret", secret)
        if config.get("client_id") and config["client_id"] != client_id:
            vault.request("delete", "oauth")
            save_json("cache.json", {})
            config.pop("vin", None)
            config.pop("registered", None)
        config.update(client_id=client_id, domain=domain, region=region, redirect_uri=redirect)
        config.pop("poll_minutes", None)
        save_json("config.json", config)
        cache = read_json("cache.json")
        cache.pop("next_poll", None)
        save_json("cache.json", cache)
    print("Settings saved. Next, register the app and connect your Tesla account.")


def register(config):
    domain = config.get("domain", "")
    if not domain or "/" in domain or ":" in domain or "." not in domain:
        raise AppError("Set the public app domain first.")
    client_secret = Keychain().get("client-secret")
    if not client_secret or not config.get("client_id"):
        raise AppError("Save your Client ID and Client Secret in Settings first.")
    token = request_json(TOKEN_URL, form={"grant_type": "client_credentials",
        "client_id": config["client_id"], "client_secret": client_secret,
        "audience": REGIONS[config["region"]], "scope": "vehicle_device_data"})
    if not token.get("access_token"):
        raise AppError("Tesla did not return a partner token.")
    request_json(REGIONS[config["region"]] + "/api/1/partner_accounts",
                 token=token["access_token"], body={"domain": domain})
    config["registered"] = True
    save_json("config.json", config)
    print("Region registration complete.")


def provision(config, launch=True):
    """Short-lived loopback form for private browser-to-Keychain provisioning."""
    nonce = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    result = {}

    class Setup(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def valid_request(self):
            return self.path == "/setup/" + nonce and self.headers.get("Host") == "127.0.0.1:8766"

        def respond(self, text, status=200):
            body = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>Tesla xBar • Connection setup</title><style>body{font:18px system-ui;max-width:560px;margin:8vh auto;padding:24px}"
                    "label{display:block;margin:24px 0 8px}input{box-sizing:border-box;width:100%;padding:12px;font:inherit}"
                    "button{margin-top:24px;padding:12px 24px;font:inherit}</style><body>" + text + "</body></html>").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.valid_request():
                self.send_error(404)
                return
            self.respond("<h1>Connect Tesla xBar</h1><p>Your credentials will be stored in this Mac's Keychain.</p>"
                "<form method='post' autocomplete='off'>"
                f"<input type='hidden' name='csrf' value='{csrf}'>"
                "<label for='client_id'>Client ID</label>"
                "<input id='client_id' name='client_id' required maxlength='256'>"
                "<label for='client_secret'>Client Secret</label><input id='client_secret' name='client_secret' type='password' required maxlength='2048'>"
                "<button type='submit'>Save to Keychain</button></form>")

        def do_POST(self):
            # Embedded browsers may send an opaque Origin. Both the unguessable
            # URL and a separate form token are required; other origins fail.
            if not self.valid_request() or self.headers.get("Origin") not in (None, "null", "http://127.0.0.1:8766"):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 8192 or self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                    self.send_error(400)
                    return
                fields = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if not secrets.compare_digest(fields.get("csrf", [""])[0], csrf):
                    self.send_error(403)
                    return
                client_id = fields.get("client_id", [""])[0].strip()
                client_secret = fields.get("client_secret", [""])[0].strip()
                if not client_id or len(client_id) > 256 or not client_secret or len(client_secret) > 2048:
                    self.send_error(400)
                    return
                with locked():
                    vault = Keychain()
                    vault.set("client-secret", client_secret)
                    if config.get("client_id") and config["client_id"] != client_id:
                        vault.request("delete", "oauth")
                        config.pop("vin", None)
                        config.pop("registered", None)
                    config["client_id"] = client_id
                    save_json("config.json", config)
                    save_json("cache.json", {})
                result["success"] = True
                self.respond("<h1>Credentials saved</h1><p>You can now complete registration and connect your Tesla account.</p>")
            except (ValueError, AppError, subprocess.SubprocessError):
                self.respond("<h1>Could not save credentials</h1><p>Unlock Keychain and try connecting again.</p>", 400)

    with http.server.HTTPServer(("127.0.0.1", 8766), Setup) as server:
        server.timeout = 1
        url = "http://127.0.0.1:8766/setup/" + nonce
        save_json("setup-session.json", {"url": url, "expires_at": time.time() + 600})
        print("Local credential setup is ready (expires in 10 minutes).", flush=True)
        if launch:
            webbrowser.open(url)
        deadline = time.monotonic() + 600
        try:
            while not result and time.monotonic() < deadline:
                server.handle_request()
        finally:
            (APP_DIR / "setup-session.json").unlink(missing_ok=True)
    if not result:
        raise AppError("Credential setup timed out.")
    print("Credentials saved to Keychain.")


def authorize(config, launch=True):
    if not config.get("client_id") or not Keychain().get("client-secret"):
        raise AppError("Save your Client ID and Client Secret in Settings first.")
    parsed = urllib.parse.urlsplit(config["redirect_uri"])
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or parsed.path != "/callback" or not parsed.port:
        raise AppError("Set the local Redirect URI to http://localhost:8765/callback.")
    state = secrets.token_urlsafe(32)
    outcome = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth codes never enter request logs.

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            params = urllib.parse.parse_qs(url.query)
            expected_hosts = {f"localhost:{parsed.port}", f"127.0.0.1:{parsed.port}"}
            if url.path != "/callback" or self.headers.get("Host") not in expected_hosts:
                self.send_error(404)
                return
            supplied_state = params.get("state", [""])[0]
            if not secrets.compare_digest(supplied_state, state):
                self.send_error(400, "Invalid OAuth state")
                return
            if "error" in params:
                outcome["error"] = "Tesla account access was denied."
            elif params.get("code"):
                outcome["code"] = params["code"][0]
            else:
                self.send_error(400, "Missing authorization code")
                return
            # Exchange before showing success; the callback server is loopback-only.
            if "code" in outcome:
                try:
                    with locked():
                        tokens = request_json(TOKEN_URL, form={"grant_type": "authorization_code",
                            "client_id": config["client_id"], "client_secret": Keychain().get("client-secret"),
                            "code": outcome.pop("code"), "audience": REGIONS[config["region"]],
                            "redirect_uri": config["redirect_uri"]})
                        Client(config).save_tokens(tokens)
                        reset_after_authorization()
                    outcome["success"] = True
                except AppError as exc:
                    outcome["error"] = str(exc)
            title = "Tesla account connected" if outcome.get("success") else "Could not connect"
            message = "Return to xBar. Battery data will be loaded on the next refresh." if outcome.get("success") else outcome["error"]
            page = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>" + title + "</title><body style='font:18px system-ui;max-width:600px;margin:15vh auto;padding:24px'>"
                    "<h1>" + title + "</h1><p>" + html.escape(message) + "</p></body></html>").encode()
            self.send_response(200 if outcome.get("success") else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    try:
        server = http.server.HTTPServer(("127.0.0.1", parsed.port), Callback)
    except OSError:
        raise AppError(f"Port {parsed.port} is already in use or unavailable.") from None
    server.timeout = 1
    url = AUTH_URL + "?" + urllib.parse.urlencode({"client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"], "response_type": "code", "scope": SCOPES,
        "state": state, "locale": "en-US", "require_requested_scopes": "true", "prompt_missing_scopes": "true"})
    save_json("authorization.json", {"url": url, "expires_at": time.time() + 600})
    print("Tesla sign-in is ready (expires in 10 minutes).", flush=True)
    if launch:
        webbrowser.open(url)
    deadline = time.monotonic() + 600
    try:
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
        (APP_DIR / "authorization.json").unlink(missing_ok=True)
    if not outcome.get("success"):
        raise AppError(outcome.get("error", "Sign-in timed out. Connect your account again."))
    print("Tesla account connected. Tokens are stored in Keychain.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "refresh", "wake-refresh", "command", "command-setup", "configure", "provision", "register", "authorize", "select", "display", "demo"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--vin", help="Vehicle bound to the clicked menu item")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    config = DEFAULTS
    try:
        config = configuration()
        if args.command == "configure":
            configure()
        elif args.command == "provision":
            provision(config, launch=not args.no_browser)
        elif args.command == "authorize":
            authorize(config, launch=not args.no_browser)
        elif args.command == "register":
            with locked():
                register(config)
        elif args.command in ("command", "wake-refresh", "command-setup"):
            # Refuse concurrent actions immediately; never queue physical commands.
            with locked(blocking=False):
                if not args.vin:
                    raise AppError("Refresh the menu in xBar and try again; no vehicle was specified.")
                config = pinned_vehicle_config(configuration(), args.vin)
                (APP_DIR / "action-notice.json").unlink(missing_ok=True)
                if args.command == "command":
                    cache = run_vehicle_command(config, args.value)
                elif args.command == "wake-refresh":
                    cache = wake_and_refresh(config)
                else:
                    ready = command_setup(config)
                    missing = []
                    if not ready["charging_authorized"]:
                        missing.append("Allow Vehicle Charging Management via Connect Tesla account.")
                    if ready["signing_required"] and not ready["key_paired"]:
                        missing.append("Add the app key to your vehicle using your phone.")
                    save_json("command-result.json", {"vin": ready["vin"], "at": time.time(),
                        "status": "error" if missing else "success", "message": " ".join(missing) if missing else "Command setup is ready."})
                    cache = read_json("cache.json")
            menu = render(cache, config)
            publish_display(cache, config, menu)
            print(menu)
        elif args.command == "display":
            if args.value not in ("range", "percent"):
                raise AppError("Choose range or percentage display.")
            with locked():
                config = configuration()
                config["display_mode"] = args.value
                save_json("config.json", config)
        elif args.command == "select":
            with locked():
                vehicles = read_json("cache.json").get("vehicles", [])
                if not any(v.get("vin") == args.value for v in vehicles):
                    raise AppError("The vehicle is not in the current list.")
                config["vin"] = args.value
                save_json("config.json", config)
                save_json("cache.json", {})
        elif args.command == "demo":
            print(render({"name": "Tesla • demo data", "state": "online", "updated_at": time.time(),
                "gui_settings": {"gui_distance_units": "km/hr", "gui_range_display": "Rated"},
                "charge": {"battery_level": 72, "battery_range": 205, "charge_limit_soc": 80,
                           "charging_state": "Charging", "charger_power": 11, "minutes_to_full_charge": 35}}, config, demo=True))
        else:
            if not config.get("client_id"):
                cache = {"error": "Complete setup in the Tesla Developer portal and Settings."}
            else:
                try:
                    with locked(blocking=False):
                        cache = fetch_state(config)
                except BlockingIOError:
                    cache = read_json("cache.json")
            menu = render(cache, config)
            publish_display(cache, config, menu)
            print(menu)
    except BlockingIOError:
        cache = read_json("cache.json")
        message = "Action not performed: another operation was in progress. Try again."
        save_json("action-notice.json", {"vin": cache.get("vin"), "at": time.time(), "message": message})
        menu = render(cache, config)
        publish_display(cache, config, menu)
        print(menu)
    except (AppError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Never print raw exceptions: they may contain request bodies or credentials.
        message = str(exc) if isinstance(exc, AppError) else "Could not read Settings or Keychain."
        if args.command in ("menu", "refresh", "wake-refresh", "command", "command-setup"):
            cache = read_json("cache.json")
            if args.command in ("command", "command-setup", "wake-refresh"):
                save_json("command-result.json", {"vin": cache.get("vin"), "at": time.time(),
                    "status": "error", "message": message})
            else:
                cache["error"] = message
            menu = render(cache, config)
            publish_display(cache, config, menu)
            print(menu)
        else:
            print(message, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
