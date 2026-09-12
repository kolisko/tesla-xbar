"""Application entry use cases. No UI syntax, network, paths or subprocesses."""
from .ports import Profile, Clock, AccountFlow, Request, Result, Record
from .vehicle import VehicleService
from .commands import CommandService
from .location import LocationService
from ..domain.errors import AppError
from ..domain.settings import DEFAULTS, SETTINGS

class PluginService:
    def __init__(self, profile: Profile, clock: Clock, accounts: AccountFlow,
                 vehicles: VehicleService, commands: CommandService, location: LocationService):
        self.profile, self.clock, self.accounts = profile, clock, accounts
        self.vehicles, self.commands, self.location = vehicles, commands, location

    def handle(self, args: Request):
        config = dict(DEFAULTS)
        result = Result(config)
        try:
            config = self.profile.configuration()
            if args.command == "configure":
                self.accounts.configure()
            elif args.command == "provision":
                self.accounts.provision(config, launch=not args.no_browser)
            elif args.command == "authorize":
                self.accounts.authorize(config, launch=not args.no_browser)
            elif args.command in ("location-enable", "location-disable"):
                with self.profile.locked(blocking=False):
                    config = self.profile.configuration()
                    config["location_enabled"] = args.command == "location-enable"
                    config = self.profile.save_configuration(config)
                    if not config["location_enabled"]:
                        cache = self.profile.read(Record.STATE)
                        cache.pop("location", None)
                        cache.pop("location_error", None)
                        self.location.clear_location_map(cache)
                        self.profile.write(Record.STATE, cache)
                        result.cache = cache
                if config["location_enabled"]:
                    result.messages.append("Location uses Tesla GPS data. Address lookup shares those coordinates with Apple.")
                    self.accounts.authorize(config, launch=not args.no_browser)
            elif args.command in ("map-enable", "map-disable"):
                with self.profile.locked(blocking=False):
                    config = self.profile.configuration()
                    config["location_map_enabled"] = args.command == "map-enable"
                    config = self.profile.save_configuration(config)
                    cache = self.profile.read(Record.STATE)
                    self.location.update_location_map(cache, config)
                    self.profile.write(Record.STATE, cache)
                    result.cache = cache
            elif args.command == "register":
                with self.profile.locked():
                    self.accounts.register(config)
                result.messages.append("Region registration complete.")
            elif args.command in ("command", "wake-refresh", "command-setup"):
                # Refuse concurrent actions immediately; never queue physical commands.
                with self.profile.locked(blocking=False):
                    if not args.vin:
                        raise AppError("Refresh the menu in xBar and try again; no vehicle was specified.")
                    config = self.vehicles.pinned_vehicle_config(self.profile.configuration(), args.vin)
                    self.profile.delete(Record.ACTION_NOTICE)
                    if args.command == "command":
                        cache = self.commands.run_vehicle_command(config, args.value, temperature=args.temperature)
                    elif args.command == "wake-refresh":
                        cache = self.vehicles.wake_and_refresh(config)
                    else:
                        ready = self.commands.command_setup(config)
                        missing = []
                        if not ready["charging_authorized"]:
                            missing.append("Allow Vehicle Charging Management via Connect Tesla account.")
                        if not ready.get("vehicle_authorized"):
                            missing.append("Allow Vehicle Commands via Connect Tesla account.")
                        if ready["pairing_required"]:
                            missing.append("Add the app key to your vehicle using your phone.")
                        self.profile.write(Record.COMMAND_RESULT, {"vin": ready["vin"], "at": self.clock.now(),
                            "status": "error" if missing else "success", "message": " ".join(missing) if missing else "Command setup is ready."})
                        cache = self.profile.read(Record.STATE)
                result.cache = cache
            elif args.command == "display":
                if args.value not in dict(SETTINGS["display_mode"].choices):
                    raise AppError("Choose range or percentage display.")
                with self.profile.locked():
                    config = self.profile.configuration()
                    config["display_mode"] = args.value
                    config = self.profile.save_configuration(config)
            elif args.command == "select":
                with self.profile.locked():
                    vehicles = self.profile.read(Record.STATE).get("vehicles", [])
                    if not any(v.get("vin") == args.value for v in vehicles):
                        raise AppError("The vehicle is not in the current list.")
                    config["vin"] = args.value
                    config = self.profile.save_configuration(config)
                    self.profile.write(Record.STATE, {})
            elif args.command == "demo":
                result.demo = True
                result.cache = {"name": "Tesla • demo data", "state": "online", "updated_at": self.clock.now(),
                    "gui_settings": {"gui_distance_units": "km/hr", "gui_range_display": "Rated"},
                    "charge": {"battery_level": 72, "battery_range": 205, "charge_limit_soc": 80,
                               "charging_state": "Charging", "charger_power": 11, "minutes_to_full_charge": 35}}
            else:
                if not config.get("client_id"):
                    cache = {"error": "Complete setup in the Tesla Developer portal and Settings."}
                else:
                    try:
                        with self.profile.locked(blocking=False):
                            cache = self.vehicles.fetch_state(config)
                    except BlockingIOError:
                        cache = self.profile.read(Record.STATE)
                result.cache = cache
        except BlockingIOError:
            cache = self.profile.read(Record.STATE)
            message = "Action not performed: another operation was in progress. Try again."
            self.profile.write(Record.ACTION_NOTICE, {"vin": cache.get("vin"), "at": self.clock.now(), "message": message})
            result.cache = cache
        except (AppError, OSError, ValueError, KeyError) as exc:
            # Never print raw exceptions: they may contain request bodies or credentials.
            message = str(exc) if isinstance(exc, AppError) else "Could not read Settings or Keychain."
            if args.command in ("menu", "refresh", "wake-refresh", "command", "command-setup"):
                cache = self.profile.read(Record.STATE)
                if args.command in ("command", "command-setup", "wake-refresh"):
                    self.profile.write(Record.COMMAND_RESULT, {"vin": cache.get("vin"), "at": self.clock.now(),
                        "status": "error", "message": message})
                else:
                    cache["error"] = message
                result.cache = cache
            else:
                result.error = message
        result.config = config
        return result
