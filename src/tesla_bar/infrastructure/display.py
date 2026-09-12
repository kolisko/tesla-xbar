"""Private display snapshot and icon assets; no rendering rules."""
import os
import tempfile
from . import runtime
from ..domain.models import STATUS_ICON_ORDER

def status_icon_bytes(icons):
    names = [name for name in STATUS_ICON_ORDER if name in icons]
    if not names or ("camp" in names and "pet" in names):
        return None
    try:
        return (runtime.HERE / "icons" / ("-".join(names) + ".png")).read_bytes()
    except OSError:
        return None

def publish_display(menu, pulse_until):
    """Publish a private text snapshot for the fast renderer, without credentials."""
    runtime.APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".display-", dir=runtime.APP_DIR)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(f"TESLA_XBAR_DISPLAY_V1 {pulse_until:.0f}\n{menu}\n")
        os.replace(temporary, runtime.APP_DIR / "display.txt")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
