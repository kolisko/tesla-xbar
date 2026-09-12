"""Strict private profile configuration persistence."""
import json
from ..domain.settings import Setting, DEFAULTS, REDIRECT, SETTINGS, CONNECTION_FIELDS, validate_setting, validate_configuration
from ..domain.errors import AppError
from . import runtime
from .runtime import save_json

REGIONS = {"eu": "https://fleet-api.prd.eu.vn.cloud.tesla.com",
           "na": "https://fleet-api.prd.na.vn.cloud.tesla.com",
           "cn": "https://fleet-api.prd.cn.vn.cloud.tesla.cn"}


def configuration():
    try:
        raw = (runtime.APP_DIR / "config.json").read_text()
    except FileNotFoundError:
        return dict(DEFAULTS)
    except OSError:
        raise AppError("Could not read Settings. Check the profile permissions.") from None
    try:
        value = json.loads(raw)
    except ValueError:
        raise AppError("Settings contain invalid JSON. Restore or repair config.json.") from None
    return validate_configuration(value)

def save_configuration(config, changes=None):
    """Caller holds the profile lock; unknown private metadata is preserved."""
    result = validate_configuration(config | (changes or {}))
    save_json("config.json", result)
    return result
