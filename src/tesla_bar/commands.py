"""Commands responsibilities for Tesla xBar."""
import os
import subprocess
import time
import urllib.request
from . import runtime
from .runtime import read_json, save_json
from .errors import APIError, AppError
from . import api
from .models import CLIMATE_MODES, LOCK_TRUNK_COMMANDS, VEHICLE_COMMANDS, VEHICLE_SCOPE_PREFIXES, cable_connected, climate_mode, number, status_is_current, temperature_limits, trunk_open_state
from .vehicle import fetch_state, pinned_vehicle_config, wake_and_refresh


def send_vehicle_command(client, vin, command, capabilities, temperature=None):
    temperature = validate_command(command, temperature)
    cli_command, _, endpoint = VEHICLE_COMMANDS[command]
    arguments, body = [], {}
    if command in CLIMATE_MODES:
        mode, code = CLIMATE_MODES[command]
        arguments = [mode]
        body = {"climate_keeper_mode": code, "manual_override": False}
    elif command == "climate-set-temp":
        arguments = [f"{temperature:g}C"]
        body = {"driver_temp": temperature, "passenger_temp": temperature}
    elif command.startswith("sentry-"):
        arguments = ["on" if command == "sentry-on" else "off"]
        body = {"on": command == "sentry-on"}
    elif command in ("frunk-open", "trunk-move"):
        body = {"which_trunk": "front" if command == "frunk-open" else "rear"}
    if not capabilities["signing_required"]:
        path = "/api/1/vehicles/" + urllib.parse.quote(vin, safe="") + "/command/" + endpoint
        response = client.request(path, body=body).get("response", {})
        if response.get("result") is not True:
            raise AppError(command_error(str(response.get("reason", "")), command))
        return
    if not capabilities["key_paired"]:
        raise AppError("First add the app key to your vehicle using the Tesla mobile app.")
    binary, key = runtime.HERE / "tesla-control", runtime.APP_DIR / "command-key.pem"
    if not binary.is_file() or not key.is_file():
        raise AppError("The command signing helper is not installed.")
    token = client.access_token()
    args = [str(binary), "-token-file", "/dev/stdin", "-key-file", str(key),
            "-vin", vin, "-session-cache", str(runtime.APP_DIR / "command-sessions.json"),
            "-connect-timeout", "20s", "-command-timeout", "15s", cli_command] + arguments
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
        raise AppError(command_error(result.stderr + result.stdout, command))


def validate_command(command, temperature=None):
    if command not in VEHICLE_COMMANDS:
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


def command_error(text, command=""):
    value = text.lower()
    for needles, message in (
        (("has not been paired", "not on whitelist", "unknown key"), "First add the app key to your vehicle using the Tesla mobile app."),
        (("403", "forbidden", "insufficient scope"), "Tesla denied the command. Allow Vehicle Commands via Connect Tesla account."
         if command.startswith(VEHICLE_SCOPE_PREFIXES) else "Tesla denied the command. Allow Vehicle Charging Management via Connect Tesla account."),
        (("unrecognized command",), "Update the command helper: run python3 -m scripts.install from the project folder."),
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


def command_setup(config, client=None):
    config = pinned_vehicle_config(config)
    client = client or api.Client(config)
    cache = fetch_state(config, client=client)
    if not cache.get("vehicle_verified") or not cache.get("vin") or (cache.get("error") and cache.get("retry_status") != 408):
        raise AppError(cache.get("error", "Select a vehicle first."))
    capabilities = client.command_capabilities(cache["vin"])
    save_json("command-setup.json", capabilities)
    return capabilities


def run_vehicle_command(config, command, client=None, temperature=None):
    """Explicit menu action only. Validate current vehicle, consent and key first."""
    temperature = validate_command(command, temperature)
    label = (f"Set temperature to {temperature:g} °C" if temperature is not None else VEHICLE_COMMANDS[command][1])
    client = client or api.Client(config)
    previous = read_json("cache.json")
    report = {"vin": previous.get("vin"), "command": command, "at": time.time(),
              "message": "Running: " + label, "status": "pending"}
    accepted = []
    save_json("command-result.json", report)
    try:
        config = pinned_vehicle_config(config)
        capabilities = command_setup(config, client=client)
        vin = capabilities["vin"]
        report["vin"] = vin
        if command.startswith("charge-") and not capabilities["charging_authorized"]:
            raise AppError("Allow Vehicle Charging Management via Connect Tesla account.")
        if command.startswith(VEHICLE_SCOPE_PREFIXES) and not capabilities.get("vehicle_authorized"):
            raise AppError("Allow Vehicle Commands via Connect Tesla account.")
        if capabilities["signing_required"] and not capabilities["key_paired"]:
            raise AppError("First add the app key to your vehicle using the Tesla mobile app.")
        cache = read_json("cache.json")
        if cache.get("state") != "online":
            cache = wake_and_refresh(config | {"vin": vin}, client=client)
        if cache.get("error") or cache.get("state") != "online":
            raise AppError(cache.get("error", "The vehicle is unavailable."))
        if temperature is not None:
            limits = temperature_limits(cache)
            if not status_is_current(cache, "climate") or limits is None:
                raise AppError("Tesla has not provided current temperature limits. Refresh and try again.")
            if not limits[0] <= temperature <= limits[1]:
                raise AppError(f"Choose a temperature from {limits[0]:g} to {limits[1]:g} °C.")
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
            sent_at = time.time()
            # Normal climate and full shutdown must also exit Camp/Pet/Keep mode.
            if command in ("climate-on", "climate-off") and not (
                    status_is_current(cache, "climate") and climate_mode(cache) == "off"):
                client.vehicle_command(vin, "climate-mode-off", capabilities)
                accepted.append("climate-mode-off")
            if temperature is None:
                client.vehicle_command(vin, command, capabilities)
            else:
                client.vehicle_command(vin, command, capabilities, temperature=temperature)
            accepted.append(command)
            message = "Command accepted: " + label
            fresh = fetch_state(config | {"vin": vin}, client=client)
            state = fresh.get("charge", {}).get("charging_state")
            if not fresh.get("error") and fresh.get("state") == "online":
                if command == "charge-start" and state == "Charging":
                    message = "Charging started • confirmed by the vehicle."
                elif command == "charge-stop" and state in ("Stopped", "Complete", "Disconnected", "NoPower"):
                    message = "Charging stopped • confirmed by the vehicle."
                elif command.startswith("climate-") and climate_command_confirmed(fresh, command, temperature, sent_at):
                    message = label + " • confirmed by the vehicle."
                elif (command.startswith("sentry-") and status_is_current(fresh, "vehicle_status")
                      and fresh["vehicle_status"].get("updated_at", 0) >= sent_at
                      and fresh["vehicle_status"].get("sentry_mode") is (command == "sentry-on")):
                    message = label + " • confirmed by the vehicle."
                elif command in LOCK_TRUNK_COMMANDS:
                    confirmed = lock_trunk_confirmation(fresh, cache, command, sent_at)
                    if confirmed:
                        message = confirmed + " • confirmed by the vehicle."
        report.update(status="success", message=message)
    except (AppError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, AppError) else "The command could not be completed."
        if isinstance(exc, APIError) and exc.status == 403 and command.startswith(VEHICLE_SCOPE_PREFIXES):
            message = "Tesla denied the command. Allow Vehicle Commands via Connect Tesla account."
        if accepted:
            message = "Some commands were accepted; " + message
            fetch_state(config | {"vin": report["vin"]}, client=client)
        report.update(status="error", message=message)
    finally:
        report["at"] = time.time()
        save_json("command-result.json", report)
    return read_json("cache.json")


def climate_command_confirmed(cache, command, temperature, sent_at):
    climate = cache.get("climate") or {}
    if not status_is_current(cache, "climate") or climate.get("updated_at", 0) < sent_at:
        return False
    mode = climate_mode(cache)
    if command in CLIMATE_MODES:
        expected = CLIMATE_MODES[command][0]
        if mode == "pet":
            mode = "dog"
        return mode == expected and (expected == "off" or climate.get("is_climate_on") is True)
    if command in ("climate-on", "climate-off"):
        return mode == "off" and climate.get("is_climate_on") is (command == "climate-on")
    if command == "climate-set-temp":
        return all(number(climate.get(key)) and abs(climate[key] - temperature) < 0.1
                   for key in ("driver_temp_setting", "passenger_temp_setting"))
    return False


def lock_trunk_confirmation(fresh, before, command, sent_at):
    status = fresh.get("vehicle_status") or {}
    if not status_is_current(fresh, "vehicle_status") or status.get("updated_at", 0) < sent_at:
        return None
    if command.startswith("door-") and status.get("locked") is (command == "door-lock"):
        return "Vehicle locked" if command == "door-lock" else "Vehicle unlocked"
    if command == "frunk-open" and trunk_open_state(status, "ft") is True:
        return "Front trunk open"
    if command == "trunk-move" and status_is_current(before, "vehicle_status"):
        previous = trunk_open_state(before.get("vehicle_status") or {}, "rt")
        current = trunk_open_state(status, "rt")
        # A toggle acknowledgement alone does not tell us the resulting position.
        if previous is not None and current is not None and previous != current:
            return "Rear trunk open" if current else "Rear trunk closed"
    return None
