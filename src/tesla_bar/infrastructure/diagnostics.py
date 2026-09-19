"""Two timestamps per event, private and shared with the signed-command helper."""
import fcntl
import math
import os
import time
from . import runtime

EVENTS = ("plugin_runs", "tesla_api_calls")


def snapshot():
    data = runtime.read_json("diagnostics.json")
    result = {}
    for event in EVENTS:
        values = data.get(event, [])
        result[event] = sorted((x for x in values if type(x) in (int, float) and math.isfinite(x) and x > 0), reverse=True)[:2] if isinstance(values, list) else []
    return result


def record(event, at=None):
    if event not in EVENTS:
        return
    try:
        runtime.APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(runtime.APP_DIR / "diagnostics.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = snapshot()
            data[event] = sorted(data[event] + [time.time() if at is None else at], reverse=True)[:2]
            runtime.save_json("diagnostics.json", data)
    except (OSError, ValueError):
        pass  # Diagnostics must not fail a refresh or replay a physical command.


def tesla_host(host):
    return bool(host and any(host.endswith(suffix) for suffix in (".tesla.com", ".tesla.cn", ".teslamotors.com")))


def request_sent(host):
    if tesla_host(host):
        record("tesla_api_calls")
