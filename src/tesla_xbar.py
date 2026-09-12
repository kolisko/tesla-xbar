#!/usr/bin/env python3
"""Tesla xBar entrypoint; runtime responsibilities live in tesla_bar/."""
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tesla-runtime.zip"))
    from tesla_bar.cli import main
else:
    from .tesla_bar.runtime import APP_DIR, HERE, read_json, save_json, locked
    from .tesla_bar.errors import AppError, APIError
    from .tesla_bar.config import REGIONS, REDIRECT, DEFAULTS, configuration
    from .tesla_bar.transport import NoRedirect, request_json, retry_after_seconds
    from .tesla_bar.auth import TOKEN_URL, AUTH_URL, SCOPES, Keychain, Authenticator, reset_after_authorization, register, authorize
    from .tesla_bar.api import Client
    from .tesla_bar.models import STALE_AFTER_SECONDS, STATUS_ICON_ORDER, VEHICLE_COMMANDS, LOCK_TRUNK_COMMANDS, VEHICLE_SCOPE_PREFIXES, CLIMATE_MODES, number, temperature_limits, trunk_open_state, vehicle_range_miles, vehicle_range, cable_connected, battery_color, charging_is_current, status_is_current, climate_mode, active_status_icons
    from .tesla_bar.vehicle import fetch_state, wake_and_refresh, pinned_vehicle_config
    from .tesla_bar.commands import send_vehicle_command, validate_command, command_error, command_setup, run_vehicle_command, climate_command_confirmed, lock_trunk_confirmation
    from .tesla_bar.location import MAP_IMAGE_LIMIT, MAP_IMAGE_FILE, coordinates, reverse_geocode, update_location, clear_location_map, location_map_request, valid_map_png, saved_map_png, download_location_map, update_location_map
    from .tesla_bar.menu import safe_text, action, status_icon_image, status_menu_lines, sentry_menu, locks_trunks_menu, location_menu, clima_menu, publish_display, render
    from .tesla_bar.settings_ui import configure, provision
    from .tesla_bar.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
