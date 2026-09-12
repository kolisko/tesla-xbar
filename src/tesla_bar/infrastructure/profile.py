"""File-backed ports; filenames and macOS paths stay in infrastructure."""
import time
from . import runtime, configuration
from .auth import Keychain
from ..application.ports import Record
from .errors import HTTP_REASONS

RECORD_FILES = {
    Record.STATE: "cache.json",
    Record.COMMAND_RESULT: "command-result.json",
    Record.COMMAND_SETUP: "command-setup.json",
    Record.ACTION_NOTICE: "action-notice.json",
}


class FileProfile:
    def read(self, record):
        value = runtime.read_json(RECORD_FILES[record])
        if record is Record.STATE:
            reason = HTTP_REASONS.get(value.pop("retry_status", None))
            if reason is not None:
                value["retry_reason"] = reason
        if record is Record.COMMAND_SETUP and "signing_required" in value:
            value = {k: value[k] for k in ("vin", "charging_authorized", "vehicle_authorized") if k in value} | {
                "pairing_required": bool(value.get("signing_required") and not value.get("key_paired"))}
        return value

    def write(self, record, value):
        value = dict(value)
        if record is Record.STATE and "retry_reason" in value:
            reason = value.pop("retry_reason")
            value["retry_status"] = next((code for code, item in HTTP_REASONS.items() if item == reason), None)
        runtime.save_json(RECORD_FILES[record], value)

    def delete(self, record):
        (runtime.APP_DIR / RECORD_FILES[record]).unlink(missing_ok=True)

    def configuration(self):
        return configuration.configuration()

    def save_configuration(self, config, changes=None):
        return configuration.save_configuration(config, changes)

    def locked(self, blocking=True):
        return runtime.locked(blocking)


class SystemClock:
    def now(self):
        return time.time()

    def monotonic(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)


class KeychainVault(Keychain):
    def delete(self, account):
        self.request("delete", account)


class SetupSession:
    def save(self, value):
        runtime.save_json("setup-session.json", value)

    def delete(self):
        (runtime.APP_DIR / "setup-session.json").unlink(missing_ok=True)
