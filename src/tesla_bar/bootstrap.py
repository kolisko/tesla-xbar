"""Composition root: the only runtime module that connects all four layers."""
from .application.ports import MenuContext, Record
from .application.vehicle import VehicleService
from .application.commands import CommandService
from .application.location import LocationService
from .application.settings import SettingsService
from .application.accounts import AccountService
from .application.plugin import PluginService
from .domain.models import active_status_icons, charging_is_current, STALE_AFTER_SECONDS
from .infrastructure import auth, runtime, settings_input, display
from .infrastructure.profile import FileProfile, SystemClock, KeychainVault, SetupSession
from .infrastructure.gateway import TeslaGateway
from .infrastructure.maps import MapMapMedia, AppleGeocoder
from .infrastructure.transport import session_scope
from .presentation.menu import MenuRenderer
from .presentation.settings_form import settings_fields_html
from .presentation.cli import run


class InteractiveSettings:
    """Wire interactive adapters to settings use cases without reverse imports."""
    def __init__(self, profile, settings):
        self.profile, self.settings = profile, settings

    def configure(self):
        settings_input.configure(self.profile.configuration, self.settings.apply)

    def provision(self, config, launch=True):
        settings_input.provision(config, self.settings.apply, SetupSession(), settings_fields_html, launch)


def menu_context(profile, clock, maps, cache):
    now = clock.now()
    return MenuContext(now, str(runtime.APP_DIR / "tesla-action.sh"),
        display.status_icon_bytes(active_status_icons(cache, now=now)), maps.saved(cache),
        profile.read(Record.COMMAND_RESULT), profile.read(Record.ACTION_NOTICE), profile.read(Record.COMMAND_SETUP))


def present(result, profile, clock, maps):
    context = menu_context(profile, clock, maps, result.cache)
    menu = MenuRenderer(context).render(result.cache, result.config, result.demo)
    if not result.demo:
        pulse = result.cache.get("updated_at", 0) + STALE_AFTER_SECONDS if charging_is_current(result.cache, now=context.now) else 0
        display.publish_display(menu, pulse)
    return menu


def build():
    profile, clock, maps = FileProfile(), SystemClock(), MapMapMedia()
    location = LocationService(clock, maps, AppleGeocoder())
    vehicles = VehicleService(profile, clock, TeslaGateway, location)
    commands = CommandService(profile, clock, vehicles, TeslaGateway)
    settings = SettingsService(profile, KeychainVault())
    accounts = AccountService(profile, auth.OAuthIdentity(), InteractiveSettings(profile, settings))
    service = PluginService(profile, clock, accounts, vehicles, commands, location)
    return service, lambda result: present(result, profile, clock, maps)


def main(argv=None):
    with session_scope():
        service, presenter = build()
        return run(service, presenter, argv)
