"""Command use cases through a single semantic vehicle gateway."""
from typing import Callable
from .ports import Profile, Clock, Record, VehicleGateway
from .vehicle import VehicleService
from ..domain.errors import RemoteError, AppError, Failure
from ..domain.commands import VehicleCommand, validate_command, climate_command_confirmed, lock_trunk_confirmation
from ..domain.models import COMMAND_LABELS, CLIMATE_MODES, LOCK_TRUNK_COMMANDS, VEHICLE_SCOPE_PREFIXES, cable_connected, climate_mode, status_is_current, temperature_limits

class CommandService:
    def __init__(self, profile: Profile, clock: Clock, vehicles: VehicleService, gateway_factory: Callable[[dict], VehicleGateway]):
        self.profile = profile
        self.clock = clock
        self.vehicles = vehicles
        self.gateway_factory = gateway_factory

    def command_setup(self, config, gateway=None):
        config = self.vehicles.pinned_vehicle_config(config)
        gateway = gateway or self.gateway_factory(config)
        cache = self.vehicles.fetch_state(config, gateway=gateway)
        if not cache.get("vehicle_verified") or not cache.get("vin") or (cache.get("error") and cache.get("retry_reason") != Failure.UNAVAILABLE):
            raise AppError(cache.get("error", "Select a vehicle first."))
        capabilities = gateway.capabilities(cache["vin"])
        self.profile.write(Record.COMMAND_SETUP, capabilities)
        return capabilities

    def run_vehicle_command(self, config, command, gateway=None, temperature=None):
        """Explicit menu action only. Validate current vehicle, consent and key first."""
        temperature = validate_command(command, temperature)
        label = (f"Set temperature to {temperature:g} °C" if temperature is not None else COMMAND_LABELS[command])
        gateway = gateway or self.gateway_factory(config)
        previous = self.profile.read(Record.STATE)
        report = {"vin": previous.get("vin"), "command": command, "at": self.clock.now(),
                  "message": "Running: " + label, "status": "pending"}
        accepted = []
        self.profile.write(Record.COMMAND_RESULT, report)
        try:
            config = self.vehicles.pinned_vehicle_config(config)
            capabilities = self.command_setup(config, gateway=gateway)
            vin = capabilities["vin"]
            report["vin"] = vin
            if command.startswith("charge-") and not capabilities["charging_authorized"]:
                raise AppError("Allow Vehicle Charging Management via Connect Tesla account.")
            if command.startswith(VEHICLE_SCOPE_PREFIXES) and not capabilities.get("vehicle_authorized"):
                raise AppError("Allow Vehicle Commands via Connect Tesla account.")
            if capabilities["pairing_required"]:
                raise AppError("First add the app key to your vehicle using the Tesla mobile app.")
            cache = self.profile.read(Record.STATE)
            if cache.get("state") != "online":
                cache = self.vehicles.wake_and_refresh(config | {"vin": vin}, gateway=gateway)
            if cache.get("error") or cache.get("state") != "online":
                raise AppError(cache.get("error", "The vehicle is unavailable."))
            if temperature is not None:
                limits = temperature_limits(cache)
                if not status_is_current(cache, "climate", now=self.clock.now()) or limits is None:
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
                sent_at = self.clock.now()
                # Normal climate and full shutdown must also exit Camp/Pet/Keep mode.
                if command in ("climate-on", "climate-off") and not (
                        status_is_current(cache, "climate", now=self.clock.now()) and climate_mode(cache) == "off"):
                    gateway.execute(VehicleCommand(vin, "climate-mode-off"))
                    accepted.append("climate-mode-off")
                gateway.execute(VehicleCommand(vin, command, temperature))
                accepted.append(command)
                message = "Command accepted: " + label
                fresh = self.vehicles.fetch_state(config | {"vin": vin}, gateway=gateway)
                state = fresh.get("charge", {}).get("charging_state")
                if not fresh.get("error") and fresh.get("state") == "online":
                    if command == "charge-start" and state == "Charging":
                        message = "Charging started • confirmed by the vehicle."
                    elif command == "charge-stop" and state in ("Stopped", "Complete", "Disconnected", "NoPower"):
                        message = "Charging stopped • confirmed by the vehicle."
                    elif command.startswith("climate-") and climate_command_confirmed(fresh, command, temperature, sent_at, now=self.clock.now()):
                        message = label + " • confirmed by the vehicle."
                    elif (command.startswith("sentry-") and status_is_current(fresh, "vehicle_status", now=self.clock.now())
                          and fresh["vehicle_status"].get("updated_at", 0) >= sent_at
                          and fresh["vehicle_status"].get("sentry_mode") is (command == "sentry-on")):
                        message = label + " • confirmed by the vehicle."
                    elif command in LOCK_TRUNK_COMMANDS:
                        confirmed = lock_trunk_confirmation(fresh, cache, command, sent_at, now=self.clock.now())
                        if confirmed:
                            message = confirmed + " • confirmed by the vehicle."
            report.update(status="success", message=message)
        except (AppError, OSError) as exc:
            message = str(exc) if isinstance(exc, AppError) else "The command could not be completed."
            if isinstance(exc, RemoteError) and exc.reason == Failure.FORBIDDEN and command.startswith(VEHICLE_SCOPE_PREFIXES):
                message = "Tesla denied the command. Allow Vehicle Commands via Connect Tesla account."
            if accepted:
                message = "Some commands were accepted; " + message
                self.vehicles.fetch_state(config | {"vin": report["vin"]}, gateway=gateway)
            report.update(status="error", message=message)
        finally:
            report["at"] = self.clock.now()
            self.profile.write(Record.COMMAND_RESULT, report)
        return self.profile.read(Record.STATE)
