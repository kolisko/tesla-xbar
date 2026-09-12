"""Vehicle responsibilities for Tesla xBar."""
import time
import urllib.request
from .runtime import read_json, save_json
from .errors import APIError, AppError
from . import api
from .models import number
from .location import update_location, update_location_map


def fetch_state(config, client=None):
    cache = read_json("cache.json")
    location_enabled = config.get("location_enabled") is True
    if not location_enabled:
        cache.pop("location", None)
        cache.pop("location_error", None)
    now = time.time()
    cache.pop("next_poll", None)
    if cache.get("retry_status") == 429 and now < cache.get("retry_at", 0):
        update_location_map(cache, config)
        save_json("cache.json", cache)
        return cache
    client = client or api.Client(config)
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
        location_allowed = location_enabled and "vehicle_location" in client.granted_scopes()
        if location_enabled and not location_allowed:
            cache.pop("location", None)
            cache["location_error"] = "Allow Vehicle Location via Connect Tesla account."
        elif location_allowed:
            # Consent can be renewed while the car is offline. Do not keep an
            # obsolete permission/lookup error until its next live GPS reading.
            cache.pop("location_error", None)
        if cache["state"] == "online":
            path = "/api/1/vehicles/" + urllib.parse.quote(selected["vin"], safe="") + "/vehicle_data?endpoints=charge_state%3Bgui_settings%3Bclimate_state%3Bvehicle_state"
            try:
                response = client.get(path + ("%3Blocation_data" if location_allowed else "")).get("response")
            except APIError as exc:
                if not location_allowed or exc.status != 403:
                    raise
                # A revoked location grant must not prevent battery/climate reads.
                location_allowed = False
                cache.pop("location", None)
                cache["location_error"] = "Tesla denied location access. Connect your Tesla account again."
                response = client.get(path).get("response")
            charge = response.get("charge_state") if isinstance(response, dict) else None
            if not isinstance(charge, dict) or not number(charge.get("battery_level")) or not 0 <= charge["battery_level"] <= 100:
                raise AppError("Tesla has not provided battery data yet.")
            # Keep only the fields used by the UI, never the full response.
            keys = ("battery_level", "usable_battery_level", "battery_range", "ideal_battery_range", "charge_limit_soc",
                    "charging_state", "conn_charge_cable", "charger_power", "minutes_to_full_charge", "time_to_full_charge",
                    "charge_port_door_open")
            cache["charge"] = {key: charge[key] for key in keys if key in charge}
            gui = response.get("gui_settings")
            cache["gui_settings"] = {key: gui[key] for key in ("gui_distance_units", "gui_range_display")
                                     if key in gui} if isinstance(gui, dict) else {}
            timestamp = charge.get("timestamp")
            cache["updated_at"] = min(now, timestamp / 1000) if number(timestamp) and timestamp > 0 else now
            for source, destination, fields in (
                ("climate_state", "climate", ("climate_keeper_mode", "is_climate_on", "driver_temp_setting",
                                              "passenger_temp_setting", "min_avail_temp", "max_avail_temp",
                                              "inside_temp", "outside_temp")),
                ("vehicle_state", "vehicle_status", ("locked", "sentry_mode", "ft", "rt")),
            ):
                data = response.get(source)
                snapshot = {key: data[key] for key in fields if key in data} if isinstance(data, dict) else {}
                if snapshot:
                    timestamp = data.get("timestamp")
                    snapshot["updated_at"] = min(now, timestamp / 1000) if number(timestamp) and timestamp > 0 else now
                # Missing fields must not make an older active state look fresh.
                cache[destination] = snapshot
            if location_allowed:
                update_location(cache, response, now)
    except AppError as exc:
        cache["error"] = str(exc)
        cache["retry_status"] = exc.status if isinstance(exc, APIError) else None
        if isinstance(exc, APIError) and exc.status == 429:
            cache["retry_at"] = time.time() + exc.retry_after
        if isinstance(exc, APIError) and exc.status == 408:
            cache["state"] = "offline"  # Unavailable is not proof of sleep.
    update_location_map(cache, config)
    save_json("cache.json", cache)
    return cache


def wake_and_refresh(config, client=None, timeout=90):
    """Explicit menu action only. Send at most one wake request, then read status."""
    config = pinned_vehicle_config(config)
    client = client or api.Client(config)
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
