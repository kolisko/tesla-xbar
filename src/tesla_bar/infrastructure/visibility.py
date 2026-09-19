"""Read desktop availability without permissions, a daemon or network calls."""
import json
import subprocess
from . import runtime
from ..application.ports import Visibility


def visibility_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return Visibility.UNKNOWN
    fields = ("session_active", "locked", "display_awake", "screensaver", "menu_bar_visible")
    if any(type(snapshot.get(field)) is not bool for field in fields):
        return Visibility.UNKNOWN
    if not snapshot["session_active"]:
        return Visibility.INACTIVE
    if snapshot["locked"]:
        return Visibility.LOCKED
    if not snapshot["display_awake"]:
        return Visibility.DISPLAY_OFF
    if snapshot["screensaver"]:
        return Visibility.SCREENSAVER
    if not snapshot["menu_bar_visible"]:
        return Visibility.BAR_HIDDEN
    return Visibility.VISIBLE


class DesktopVisibility:
    def state(self):
        try:
            result = subprocess.run([str(runtime.HERE / "tesla-visibility")],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return visibility_from_snapshot(json.loads(result.stdout))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        # Missing/broken helpers must never silently resume billable polling.
        return Visibility.UNKNOWN
