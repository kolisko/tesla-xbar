"""Runtime responsibilities for Tesla xBar."""
from pathlib import Path
import contextlib
import fcntl
import json
import os
import tempfile


APP_DIR = Path(os.environ.get("TESLA_XBAR_HOME", Path.home() / "Library/Application Support/Tesla xBar"))


HERE = Path(__file__).resolve().parents[1]
if HERE.name == "tesla-runtime.zip":
    HERE = HERE.parent  # Helpers/icons live beside the atomically installed bundle.


def read_json(name, default=None):
    try:
        value = json.loads((APP_DIR / name).read_text())
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def save_json(name, value):
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=APP_DIR)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, APP_DIR / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(blocking=True):
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (APP_DIR / "app.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
