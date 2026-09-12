"""Vehicle selection, refresh and explicit waking; no transport or filesystem."""
from typing import Callable
from .ports import Profile, Clock, VehicleGateway, Record
from .location import LocationService
from ..domain.commands import VehicleCommand
from ..domain.errors import RemoteError, AppError, Failure

class VehicleService:
    def __init__(self, profile: Profile, clock: Clock, gateway_factory: Callable[[dict], VehicleGateway], location: LocationService):
        self.profile = profile
        self.clock = clock
        self.gateway_factory = gateway_factory
        self.location = location

    def fetch_state(self, config, gateway=None):
        cache = self.profile.read(Record.STATE)
        location_enabled = config.get("location_enabled") is True
        if not location_enabled:
            cache.pop("location", None)
            cache.pop("location_error", None)
        now = self.clock.now()
        cache.pop("next_poll", None)
        if cache.get("retry_reason") == Failure.RATE_LIMITED and now < cache.get("retry_at", 0):
            self.location.update_location_map(cache, config)
            self.profile.write(Record.STATE, cache)
            return cache
        gateway = gateway or self.gateway_factory(config)
        cache.pop("retry_at", None)
        cache.pop("retry_reason", None)
        cache["vehicle_verified"] = False
        try:
            vehicles = gateway.vehicles()
            cache["vehicles"] = [{"vin": v["vin"], "name": v.get("name") or "Tesla"} for v in vehicles]
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
            cache.update(vin=selected["vin"], name=selected.get("name") or "Tesla",
                         selected_vin=selected["vin"], vehicle_verified=True,
                         state=selected.get("state", "unknown"), checked_at=now)
            cache.pop("error", None)
            cache.pop("retry_at", None)
            cache.pop("retry_reason", None)
            location_allowed = location_enabled and "vehicle_location" in gateway.granted_scopes()
            if location_enabled and not location_allowed:
                cache.pop("location", None)
                cache["location_error"] = "Allow Vehicle Location via Connect Tesla account."
            elif location_allowed:
                # Consent can be renewed while the car is offline. Do not keep an
                # obsolete permission/lookup error until its next live GPS reading.
                cache.pop("location_error", None)
            if cache["state"] == "online":
                try:
                    reading = gateway.reading(selected["vin"], location_allowed, now)
                except RemoteError as exc:
                    if not location_allowed or exc.reason != Failure.FORBIDDEN:
                        raise
                    location_allowed = False
                    cache.pop("location", None)
                    cache["location_error"] = "Tesla denied location access. Connect your Tesla account again."
                    reading = gateway.reading(selected["vin"], False, now)
                position = reading.pop("position", None)
                cache.update(reading)
                if location_allowed:
                    self.location.update_location(cache, position, now)
        except AppError as exc:
            cache["error"] = str(exc)
            cache["retry_reason"] = exc.reason if isinstance(exc, RemoteError) else None
            if isinstance(exc, RemoteError) and exc.reason == Failure.RATE_LIMITED:
                cache["retry_at"] = self.clock.now() + exc.retry_after
            if isinstance(exc, RemoteError) and exc.reason == Failure.UNAVAILABLE:
                cache["state"] = "offline"  # Unavailable is not proof of sleep.
        self.location.update_location_map(cache, config)
        self.profile.write(Record.STATE, cache)
        return cache

    def wake_and_refresh(self, config, gateway=None, timeout=90):
        """Explicit menu action only. Send at most one wake request, then read status."""
        config = self.pinned_vehicle_config(config)
        gateway = gateway or self.gateway_factory(config)
        cache = self.fetch_state(config, gateway=gateway)
        if cache.get("error") and cache.get("retry_reason") == Failure.UNAVAILABLE and cache.get("vehicle_verified"):
            cache.pop("error", None)
            cache.pop("retry_at", None)
            cache.pop("retry_reason", None)
        if cache.get("error") or cache.get("state") == "online" or not cache.get("vin"):
            return cache
        vin = cache["vin"]
        cache["wake_in_progress"] = True
        self.profile.write(Record.STATE, cache)
        try:
            state = gateway.execute(VehicleCommand(vin, "wake"))
            deadline = self.clock.monotonic() + timeout
            while state != "online":
                remaining = deadline - self.clock.monotonic()
                if remaining <= 0:
                    raise AppError("The vehicle did not connect. Showing the last known reading; try again later.")
                self.clock.sleep(min(5, remaining))
                if self.clock.monotonic() >= deadline:
                    raise AppError("The vehicle did not connect. Showing the last known reading; try again later.")
                state = gateway.connection_state(vin)
            # Pin the same vehicle for the final read even if the vehicle list changes.
            cache = self.fetch_state(config | {"vin": vin}, gateway=gateway)
            if cache.get("state") != "online" and not cache.get("error"):
                cache["error"] = "The vehicle has not provided fresh data after waking. Showing the last known range."
        except AppError as exc:
            cache["error"] = ("Waking requires the Vehicle Commands permission. Connect your Tesla account again."
                              if isinstance(exc, RemoteError) and exc.reason == Failure.FORBIDDEN else str(exc))
            if isinstance(exc, RemoteError) and exc.reason == Failure.RATE_LIMITED:
                cache["retry_at"] = self.clock.now() + exc.retry_after
                cache["retry_reason"] = Failure.RATE_LIMITED
        finally:
            cache.pop("wake_in_progress", None)
            self.profile.write(Record.STATE, cache)
        return cache

    def pinned_vehicle_config(self, config, menu_vin=None):
        """Keep a manual action on the displayed vehicle, including after list changes."""
        cache = self.profile.read(Record.STATE)
        selected = config.get("vin") or cache.get("vin") or cache.get("selected_vin")
        if menu_vin and selected and menu_vin != selected:
            raise AppError("The selected vehicle has changed. Refresh the menu and try again.")
        vin = menu_vin or selected
        if not vin:
            raise AppError("Refresh the data and select a vehicle from the plugin menu first.")
        return config | {"vin": vin}
