"""Account use cases own profile effects after successful external authorization."""
from .ports import Profile, IdentityProvider, SettingsInput, Record
from ..domain.settings import validate_configuration


def reset_authorized_state(cache):
    """Preserve last readings; renewed consent is not a new vehicle reading."""
    cache = dict(cache)
    for key in ("next_poll", "retry_at", "retry_reason", "error", "wake_in_progress"):
        cache.pop(key, None)
    cache["state"] = "unknown"
    return cache


class AccountService:
    def __init__(self, profile: Profile, identity: IdentityProvider, inputs: SettingsInput):
        self.profile, self.identity, self.inputs = profile, identity, inputs

    def configure(self):
        self.inputs.configure()

    def provision(self, config, launch=True):
        self.inputs.provision(config, launch)

    def register(self, config):
        config = validate_configuration(config, require_connection=True)
        self.identity.register(config)
        self.profile.save_configuration(config, {"registered": True})

    def authorize(self, config, launch=True):
        config = validate_configuration(config)
        def complete(code):
            with self.profile.locked():
                current = self.profile.configuration()
                # A callback may arrive after Settings has changed the application.
                if any(current.get(key) != config.get(key) for key in ("client_id", "redirect_uri")):
                    from ..domain.errors import AppError
                    raise AppError("Settings changed during sign-in. Connect your Tesla account again.")
                region = self.identity.exchange_code(config, code)
                if region:
                    self.profile.save_configuration(current, {"region": region})
                self.profile.write(Record.STATE, reset_authorized_state(self.profile.read(Record.STATE)))
        self.identity.authorize(config, complete, launch=launch)
