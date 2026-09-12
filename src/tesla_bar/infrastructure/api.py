"""Low-level Fleet API transport and vehicle capability requests."""
import urllib.parse
from ..domain.errors import AppError
from .errors import APIError
from .configuration import REGIONS
from . import transport
from .auth import Authenticator


class Client:
    """Fleet API access; authentication and signed commands have separate owners."""
    def __init__(self, config, vault=None):
        self.config = config
        self.auth = Authenticator(config, vault)

    def access_token(self, force=False):
        return self.auth.access_token(force=force)

    def save_tokens(self, result, previous=None):
        return self.auth.save_tokens(result, previous)

    def granted_scopes(self):
        return self.auth.granted_scopes()

    def vehicle_command(self, vin, command, capabilities, temperature=None):
        from .command_transport import send_vehicle_command
        return send_vehicle_command(self, vin, command, capabilities, temperature)

    def get(self, path):
        return self.request(path)

    def wake(self, vin):
        path = "/api/1/vehicles/" + urllib.parse.quote(vin, safe="") + "/wake_up"
        return self.request(path, body={})

    def command_capabilities(self, vin):
        response = self.request("/api/1/vehicles/fleet_status", body={"vins": [vin]}).get("response", {})
        info = response.get("vehicle_info", {}).get(vin, {})
        required = info.get("vehicle_command_protocol_required")
        if not isinstance(required, bool):
            raise AppError("Tesla did not confirm the command authorization method for this vehicle.")
        scopes = self.granted_scopes()
        return {"vin": vin, "signing_required": required,
                "key_paired": vin in response.get("key_paired_vins", []),
                "charging_authorized": "vehicle_charging_cmds" in scopes,
                "vehicle_authorized": "vehicle_cmds" in scopes}

    def request(self, path, body=None):
        for attempt in range(2):
            token = self.access_token(force=attempt == 1)
            try:
                return transport.request_json(REGIONS[self.config["region"]] + path, token=token, **({"body": body} if body is not None else {}))
            except APIError as exc:
                if exc.status != 401 or attempt:
                    raise
