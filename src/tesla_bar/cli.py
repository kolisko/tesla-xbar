"""Cli responsibilities for Tesla xBar."""
import argparse
import subprocess
import sys
import time
from . import runtime
from .runtime import locked, read_json, save_json
from .errors import AppError
from .config import DEFAULTS, configuration, save_configuration, SETTINGS
from .auth import authorize, register
from .vehicle import fetch_state, pinned_vehicle_config, wake_and_refresh
from .commands import command_setup, run_vehicle_command
from .location import clear_location_map, update_location_map
from .menu import publish_display, render
from .settings_ui import configure, provision


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="menu", choices=["menu", "refresh", "wake-refresh", "command", "command-setup", "configure", "provision", "register", "authorize", "location-enable", "location-disable", "map-enable", "map-disable", "select", "display", "demo"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--vin", help="Vehicle bound to the clicked menu item")
    parser.add_argument("--temperature", help="Target Celsius temperature for climate-set-temp")
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
        elif args.command in ("location-enable", "location-disable"):
            with locked(blocking=False):
                config = configuration()
                config["location_enabled"] = args.command == "location-enable"
                config = save_configuration(config)
                if not config["location_enabled"]:
                    cache = read_json("cache.json")
                    cache.pop("location", None)
                    cache.pop("location_error", None)
                    clear_location_map(cache)
                    save_json("cache.json", cache)
                    publish_display(cache, config, render(cache, config))
            if config["location_enabled"]:
                print("Location uses Tesla GPS data. Address lookup shares those coordinates with Apple.")
                authorize(config, launch=not args.no_browser)
        elif args.command in ("map-enable", "map-disable"):
            with locked(blocking=False):
                config = configuration()
                config["location_map_enabled"] = args.command == "map-enable"
                config = save_configuration(config)
                cache = read_json("cache.json")
                update_location_map(cache, config)
                save_json("cache.json", cache)
                menu = render(cache, config)
                publish_display(cache, config, menu)
                print(menu)
        elif args.command == "register":
            with locked():
                register(config)
        elif args.command in ("command", "wake-refresh", "command-setup"):
            # Refuse concurrent actions immediately; never queue physical commands.
            with locked(blocking=False):
                if not args.vin:
                    raise AppError("Refresh the menu in xBar and try again; no vehicle was specified.")
                config = pinned_vehicle_config(configuration(), args.vin)
                (runtime.APP_DIR / "action-notice.json").unlink(missing_ok=True)
                if args.command == "command":
                    cache = run_vehicle_command(config, args.value, temperature=args.temperature)
                elif args.command == "wake-refresh":
                    cache = wake_and_refresh(config)
                else:
                    ready = command_setup(config)
                    missing = []
                    if not ready["charging_authorized"]:
                        missing.append("Allow Vehicle Charging Management via Connect Tesla account.")
                    if not ready.get("vehicle_authorized"):
                        missing.append("Allow Vehicle Commands via Connect Tesla account.")
                    if ready["signing_required"] and not ready["key_paired"]:
                        missing.append("Add the app key to your vehicle using your phone.")
                    save_json("command-result.json", {"vin": ready["vin"], "at": time.time(),
                        "status": "error" if missing else "success", "message": " ".join(missing) if missing else "Command setup is ready."})
                    cache = read_json("cache.json")
            menu = render(cache, config)
            publish_display(cache, config, menu)
            print(menu)
        elif args.command == "display":
            if args.value not in dict(SETTINGS["display_mode"].choices):
                raise AppError("Choose range or percentage display.")
            with locked():
                config = configuration()
                config["display_mode"] = args.value
                config = save_configuration(config)
        elif args.command == "select":
            with locked():
                vehicles = read_json("cache.json").get("vehicles", [])
                if not any(v.get("vin") == args.value for v in vehicles):
                    raise AppError("The vehicle is not in the current list.")
                config["vin"] = args.value
                config = save_configuration(config)
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


def main():
    from .transport import session_scope
    with session_scope():
        return run()
