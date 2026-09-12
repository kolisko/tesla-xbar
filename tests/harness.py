"""Fixture composition for historical behavior tests, using the production layers.

This module is not installed. Services, rules and rendering remain production code;
only fixture shape conversion and dependency construction are performed here.
"""
import base64
import getpass
import http.server
import time
from src.tesla_bar import bootstrap
from src.tesla_bar.application.ports import Record
from src.tesla_bar.application.vehicle import VehicleService
from src.tesla_bar.application.commands import CommandService
from src.tesla_bar.application.location import LocationService
from src.tesla_bar.application.settings import SettingsService
from src.tesla_bar.domain import models
from src.tesla_bar.domain.models import STALE_AFTER_SECONDS, STATUS_ICON_ORDER, LOCK_TRUNK_COMMANDS, number, temperature_limits, trunk_open_state, vehicle_range, vehicle_range_miles, cable_connected, battery_color, climate_mode
from src.tesla_bar.domain.errors import AppError
from src.tesla_bar.infrastructure.errors import APIError
from src.tesla_bar.infrastructure import runtime, maps, settings_input, display
from src.tesla_bar.infrastructure.runtime import read_json, save_json, locked
from src.tesla_bar.infrastructure.configuration import DEFAULTS, REGIONS, configuration
from src.tesla_bar.infrastructure.auth import Keychain
from src.tesla_bar.application.accounts import reset_authorized_state
from src.tesla_bar.infrastructure.api import Client
from src.tesla_bar.infrastructure.gateway import TeslaGateway
from src.tesla_bar.infrastructure.profile import FileProfile, SystemClock, SetupSession
from src.tesla_bar.infrastructure.command_transport import COMMAND_ROUTES, command_error
from src.tesla_bar.infrastructure.transport import NoRedirect, retry_after_seconds
from src.tesla_bar.infrastructure.maps import MAP_IMAGE_FILE, MAP_IMAGE_LIMIT, location_map_request, saved_map_png, download_location_map, reverse_geocode
from src.tesla_bar.presentation.menu import MenuRenderer, safe_text
from src.tesla_bar.presentation.settings_form import settings_fields_html

# Legacy raw-response fixtures use the Tesla transport mapping.
VEHICLE_COMMANDS = {name: (route[0], models.COMMAND_LABELS[name], route[1]) for name, route in COMMAND_ROUTES.items()}
CLIMATE_MODES = {k: (v, {"off": 0, "on": 1, "dog": 2, "camp": 3}[v]) for k, v in models.CLIMATE_MODES.items()}
main = bootstrap.main


def services():
    profile, clock = FileProfile(), SystemClock()
    location = LocationService(clock, maps.MapMapMedia(), maps.AppleGeocoder())
    vehicle = VehicleService(profile, clock, TeslaGateway, location)
    return vehicle, CommandService(profile, clock, vehicle, TeslaGateway), location


def fetch_state(config, client=None):
    return services()[0].fetch_state(config, TeslaGateway(config, client) if client is not None else None)


def wake_and_refresh(config, client=None, timeout=90):
    return services()[0].wake_and_refresh(config, TeslaGateway(config, client) if client is not None else None, timeout)


def run_vehicle_command(config, command, client=None, temperature=None):
    return services()[1].run_vehicle_command(config, command, TeslaGateway(config, client) if client is not None else None, temperature)


def update_location(cache, response, now):
    raw = response.get("drive_state") or {}
    stamp = raw.get("timestamp")
    data = raw | {"updated_at": stamp / 1000 if number(stamp) else None}
    return services()[2].update_location(cache, data, now)


def update_location_map(cache, config):
    return services()[2].update_location_map(cache, config)


def renderer(cache):
    return MenuRenderer(bootstrap.menu_context(FileProfile(), SystemClock(), maps.MapMapMedia(), cache))


def render(cache, config, demo=False):
    return renderer(cache).render(cache, config, demo)


def location_menu(cache, config):
    return renderer(cache).location_menu(cache, config)


def status_menu_lines(cache):
    return renderer(cache).status_menu_lines(cache)


def active_status_icons(cache):
    return models.active_status_icons(cache, now=time.time())


def charging_is_current(cache, config=None):
    return models.charging_is_current(cache, now=time.time())


def status_icon_image(icons):
    data = display.status_icon_bytes(icons)
    return base64.b64encode(data).decode("ascii") if data else ""


def publish_display(cache, config, menu):
    pulse = cache.get("updated_at", 0) + STALE_AFTER_SECONDS if charging_is_current(cache) else 0
    display.publish_display(menu, pulse)


def apply_settings(config, changes, secret="", vault=None):
    return SettingsService(FileProfile(), vault if vault is not None else Keychain()).apply_settings(config, changes, secret)


def configure():
    settings_input.configure(configuration, SettingsService(FileProfile(), Keychain()).apply)


def provision(config, launch=True):
    settings_input.provision(config, SettingsService(FileProfile(), Keychain()).apply, SetupSession(), settings_fields_html, launch)


def reset_after_authorization():
    profile = FileProfile()
    profile.write(Record.STATE, reset_authorized_state(profile.read(Record.STATE)))


def authorize(config, launch=True):
    bootstrap.build()[0].accounts.authorize(config, launch)
