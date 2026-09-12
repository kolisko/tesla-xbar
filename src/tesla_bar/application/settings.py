"""Settings and credential-change rules shared by all input adapters."""
from .ports import Profile, CredentialVault, Record
from ..domain.settings import validate_configuration
from ..domain.errors import AppError

class SettingsService:
    def __init__(self, profile: Profile, vault: CredentialVault):
        self.profile = profile
        self.vault = vault

    def apply_settings(self, config, changes, secret=""):
        """Validate before writing; every credential/settings UI uses this path."""
        updated = validate_configuration(config | changes, require_connection=True)
        if not isinstance(secret, str) or len(secret) > 2048:
            raise AppError("Invalid Client Secret.")
        vault = self.vault
        changed_client = bool(config.get("client_id") and config["client_id"] != updated["client_id"])
        if not secret and (changed_client or not vault.get("client-secret")):
            raise AppError("Enter the Client Secret for this application.")
        if secret:
            vault.set("client-secret", secret)
        if changed_client:
            vault.delete("oauth")
            updated.pop("vin", None)
            updated.pop("registered", None)
            self.profile.write(Record.STATE, {})
        updated = self.profile.save_configuration(updated)
        cache = self.profile.read(Record.STATE)
        cache.pop("next_poll", None)
        self.profile.write(Record.STATE, cache)
        return updated

    def apply(self, changes, secret=""):
        with self.profile.locked():
            return self.apply_settings(self.profile.configuration(), changes, secret)
