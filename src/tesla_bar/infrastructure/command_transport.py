"""REST / official Tesla command CLI translation. No use-case orchestration."""
import os
import subprocess
import urllib.parse
from . import runtime
from ..domain.errors import AppError
from ..domain.commands import validate_command
from ..domain.models import CLIMATE_MODES, VEHICLE_SCOPE_PREFIXES

COMMAND_ROUTES = {'charge-start': ('charging-start', 'charge_start'),
 'charge-stop': ('charging-stop', 'charge_stop'),
 'port-open': ('charge-port-open', 'charge_port_door_open'),
 'port-close': ('charge-port-close', 'charge_port_door_close'),
 'climate-on': ('climate-on', 'auto_conditioning_start'),
 'climate-off': ('climate-off', 'auto_conditioning_stop'),
 'climate-keep': ('climate-keeper', 'set_climate_keeper_mode'),
 'climate-camp': ('climate-keeper', 'set_climate_keeper_mode'),
 'climate-pet': ('climate-keeper', 'set_climate_keeper_mode'),
 'climate-mode-off': ('climate-keeper', 'set_climate_keeper_mode'),
 'climate-set-temp': ('climate-set-temp', 'set_temps'),
 'sentry-on': ('sentry-mode', 'set_sentry_mode'),
 'sentry-off': ('sentry-mode', 'set_sentry_mode'),
 'door-lock': ('lock', 'door_lock'),
 'door-unlock': ('unlock', 'door_unlock'),
 'frunk-open': ('frunk-open', 'actuate_trunk'),
 'trunk-move': ('trunk-move', 'actuate_trunk')}

def send_vehicle_command(client, vin, command, capabilities, temperature=None):
    temperature = validate_command(command, temperature)
    cli_command, endpoint = COMMAND_ROUTES[command]
    arguments, body = [], {}
    if command in CLIMATE_MODES:
        mode = CLIMATE_MODES[command]
        code = {"off": 0, "on": 1, "dog": 2, "camp": 3}[mode]
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
