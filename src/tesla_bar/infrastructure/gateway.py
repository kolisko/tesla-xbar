"""Tesla adapter: raw Fleet API payloads become application readings here."""
import urllib.parse
from . import api
from ..domain.commands import VehicleCommand
from ..domain.models import number
from ..domain.errors import AppError


class TeslaGateway:
    def __init__(self, config, client=None):
        self._capabilities = {}
        self.client = client if client is not None else api.Client(config)

    def granted_scopes(self):
        return self.client.granted_scopes()

    def vehicles(self):
        raw = self.client.get("/api/1/vehicles").get("response")
        if not isinstance(raw, list):
            raise AppError("Tesla did not provide the vehicle list.")
        return [{"vin": v["vin"], "name": v.get("display_name") or "Tesla", "state": v.get("state", "unknown")}
                for v in raw if isinstance(v, dict) and v.get("vin")]

    def reading(self, vin, include_location, now):
        path = "/api/1/vehicles/" + urllib.parse.quote(vin, safe="") + "/vehicle_data?endpoints=charge_state%3Bgui_settings%3Bclimate_state%3Bvehicle_state"
        raw = self.client.get(path + ("%3Blocation_data" if include_location else "")).get("response")
        charge = raw.get("charge_state") if isinstance(raw, dict) else None
        if not isinstance(charge, dict) or not number(charge.get("battery_level")) or not 0 <= charge["battery_level"] <= 100:
            raise AppError("Tesla has not provided battery data yet.")
        def timestamp(data):
            value = data.get("timestamp")
            return min(now, value / 1000) if number(value) and value > 0 else now
        keys = ("battery_level", "usable_battery_level", "battery_range", "ideal_battery_range", "charge_limit_soc",
                "charging_state", "conn_charge_cable", "charger_power", "minutes_to_full_charge", "time_to_full_charge", "charge_port_door_open")
        result = {"charge": {k: charge[k] for k in keys if k in charge}, "updated_at": timestamp(charge)}
        gui = raw.get("gui_settings")
        result["gui_settings"] = {k: gui[k] for k in ("gui_distance_units", "gui_range_display") if k in gui} if isinstance(gui, dict) else {}
        for source, destination, fields in (
            ("climate_state", "climate", ("climate_keeper_mode", "is_climate_on", "driver_temp_setting", "passenger_temp_setting", "min_avail_temp", "max_avail_temp", "inside_temp", "outside_temp")),
            ("vehicle_state", "vehicle_status", ("locked", "sentry_mode", "ft", "rt")),
        ):
            data = raw.get(source)
            snapshot = {k: data[k] for k in fields if k in data} if isinstance(data, dict) else {}
            if snapshot:
                snapshot["updated_at"] = timestamp(data)
            result[destination] = snapshot
        if include_location:
            data = raw.get("drive_state") or {}
            stamp = data.get("timestamp") if isinstance(data, dict) else None
            result["position"] = ({"latitude": data.get("latitude"), "longitude": data.get("longitude"),
                                   "updated_at": stamp / 1000 if number(stamp) else None} if isinstance(data, dict) else {})
        return result

    def connection_state(self, vin):
        raw = self.client.get("/api/1/vehicles/" + urllib.parse.quote(vin, safe="")).get("response")
        if not isinstance(raw, dict):
            raise AppError("Tesla has not provided the vehicle connection status yet.")
        return raw.get("state", "unknown")

    def capabilities(self, vin):
        raw = self.client.command_capabilities(vin)
        self._capabilities[vin] = raw
        return {"vin": vin, "charging_authorized": raw.get("charging_authorized", False),
                "vehicle_authorized": raw.get("vehicle_authorized", False),
                "pairing_required": bool(raw["signing_required"] and not raw.get("key_paired"))}

    def execute(self, command: VehicleCommand):
        if command.name == "wake":
            raw = self.client.wake(command.vin).get("response")
            if not isinstance(raw, dict) or not raw.get("state"):
                raise AppError("Tesla did not confirm the wake request. Try again later.")
            return raw["state"]
        if command.vin not in self._capabilities:
            self.capabilities(command.vin)
        capabilities = self._capabilities[command.vin]
        if command.temperature is None:
            return self.client.vehicle_command(command.vin, command.name, capabilities)
        return self.client.vehicle_command(command.vin, command.name, capabilities, temperature=command.temperature)
