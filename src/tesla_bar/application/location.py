"""Location freshness and map-cache policy, independent of map providers."""
from .ports import Clock, MapMedia, Geocoder
from ..domain.location import coordinates
from ..domain.models import number
from ..domain.errors import AppError, RemoteError, Failure

class LocationService:
    def __init__(self, clock: Clock, maps: MapMedia, geocoder: Geocoder):
        self.clock = clock
        self.maps = maps
        self.geocoder = geocoder

    def update_location(self, cache, data, now):
        point = coordinates(data)
        if point is None:
            cache["location_error"] = "Tesla has not provided a current location."
            return
        previous = cache.get("location") or {}
        timestamp = data.get("updated_at")
        if not number(timestamp) or timestamp <= 0 or timestamp > now + 60:
            cache["location_error"] = "Tesla has not provided a valid location timestamp."
            return
        stamp = min(now, timestamp)
        if number(previous.get("updated_at")) and stamp < previous["updated_at"]:
            cache["location_error"] = "Tesla returned an older location. Keeping the last known position."
            return
        snapshot = {"latitude": point[0], "longitude": point[1], "updated_at": stamp}
        # An address belongs only to the exact coordinates which were looked up.
        same_point = point == coordinates(previous)
        if same_point and previous.get("address"):
            snapshot["address"] = previous["address"]
        attempted = previous.get("geocoded_at", 0)
        snapshot["geocoded_at"] = attempted
        if not snapshot.get("address") and now - attempted >= 60:
            snapshot["geocoded_at"] = now
            address = self.geocoder.address(point)
            if address:
                snapshot["address"] = address
        cache["location"] = snapshot
        cache.pop("location_error", None)

    def clear_location_map(self, cache):
        cache.pop("location_map", None)
        self.maps.delete()


    def update_location_map(self, cache, config):
        if config.get("location_enabled") is not True or config.get("location_map_enabled") is not True:
            self.clear_location_map(cache)
            return
        key = self.maps.identity(cache)
        if key is None:
            self.clear_location_map(cache)
            return
        if self.maps.saved(cache) is not None:
            return
        previous = cache.get("location_map") or {}
        if self.clock.now() < previous.get("retry_at", 0):
            return
        state = {"key": key}
        cache["location_map"] = state
        try:
            data = self.maps.fetch(cache)
            state["sha256"] = self.maps.save(data)
        except (AppError, OSError, ValueError) as exc:
            if isinstance(exc, RemoteError) and exc.reason == Failure.RATE_LIMITED:
                state["retry_at"] = self.clock.now() + exc.retry_after
            state["error"] = "Map preview unavailable. Open the position in Apple Maps."
