"""One schema for profile loading, settings forms, menu choices and installation."""
from dataclasses import dataclass
import re
import urllib.parse

from .errors import AppError

REGION_NAMES = ("eu", "na", "cn")
REDIRECT = "http://localhost:8765/callback"


@dataclass(frozen=True)
class Setting:
    label: str
    default: object
    choices: tuple = ()
    max_length: int = 256


SETTINGS = {
    "client_id": Setting("Client ID", ""),
    "domain": Setting("Public key domain", ""),
    "region": Setting("Region", "eu", tuple((r, r.upper()) for r in REGION_NAMES)),
    "redirect_uri": Setting("Redirect URI", REDIRECT, max_length=2048),
    "display_mode": Setting("Menu bar display", "range", (("range", "Range"), ("percent", "Percentage"))),
    "location_enabled": Setting("Location", False),
    "location_map_enabled": Setting("Map preview", False),
    "vin": Setting("Vehicle", "", max_length=64),
}
DEFAULTS = {name: field.default for name, field in SETTINGS.items()}
CONNECTION_FIELDS = ("client_id", "domain", "region", "redirect_uri")


def validate_setting(name, value):
    field = SETTINGS[name]
    if isinstance(field.default, bool):
        if not isinstance(value, bool):
            raise AppError(f"{field.label} must be enabled or disabled.")
        return value
    if not isinstance(value, str) or len(value) > field.max_length or any(ord(c) < 32 for c in value):
        raise AppError(f"Invalid {field.label.lower()} in Settings.")
    value = value.strip()
    if field.choices and value not in dict(field.choices):
        raise AppError(f"Invalid {field.label.lower()} in Settings.")
    if name == "domain" and value:
        value = value.removeprefix("https://").rstrip("/").lower()
        if len(value) > 253 or "." not in value or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in value.split(".")
        ):
            raise AppError("Enter only the public HTTPS domain name.")
    if name == "redirect_uri":
        try:
            url = urllib.parse.urlsplit(value)
            valid = (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")
                     and url.port and url.path == "/callback" and not url.query and not url.fragment
                     and not url.username and not url.password)
        except ValueError:
            valid = False
        if not valid:
            raise AppError("Use a local callback, such as http://localhost:8765/callback.")
    return value


def validate_configuration(config, *, require_connection=False):
    if not isinstance(config, dict):
        raise AppError("Settings must contain a JSON object.")
    result = dict(config)
    result.pop("poll_minutes", None)  # Scheduling belongs exclusively to xBar.
    for name, field in SETTINGS.items():
        result[name] = validate_setting(name, config.get(name, field.default))
    if require_connection:
        for name in ("client_id", "domain"):
            if not result[name]:
                raise AppError(f"{SETTINGS[name].label} is required.")
    return result
