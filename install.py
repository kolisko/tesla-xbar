#!/usr/bin/env python3
"""Install generic code while preserving the user's private Tesla xBar profile."""
import argparse
import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from build_commands import build_commands

VERSION = "0.1.0"


def atomic_install(data, destination, mode):
    if destination.exists() and destination.read_bytes() == data:
        os.chmod(destination, mode)
        return
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_keys(target):
    """Generate a new P-256 key only for a new profile; never rotate an existing key."""
    key = target / "command-key.pem"
    if not key.exists():
        if (target / "config.json").exists():
            raise RuntimeError("Existing profile has no private key. Restore command-key.pem from your private backup before updating.")
        result = subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout"],
                                check=True, capture_output=True)
        atomic_install(result.stdout, key, 0o600)
    else:
        os.chmod(key, 0o600)
    result = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"],
                            check=True, capture_output=True)
    atomic_install(result.stdout, target / "public-key.pem", 0o644)


def build_helpers(source):
    build = source / "build"
    build.mkdir(exist_ok=True)
    binary = build / "tesla-keychain"
    subprocess.run(["/usr/bin/swiftc", "-module-cache-path", str(build / "module-cache"),
                    str(source / "keychain.swift"), "-o", str(binary)], check=True)
    return {"tesla-keychain": binary, "tesla-control": build_commands()}


def install(source, target, plugins, *, runtime_only=False, python=None):
    active = sorted(plugins.glob("tesla-battery.*.sh"))
    if len(active) > 1:
        raise RuntimeError("Multiple active Tesla plugins found. Keep only one in xBar and run the installer again.")
    plugin = active[0] if active else plugins / "tesla-battery.1m.sh"
    helpers = {} if runtime_only else build_helpers(source)
    if runtime_only and not all((target / name).is_file() for name in ("tesla-keychain", "tesla-control")):
        raise RuntimeError("Helpers are missing. Run the installer without --runtime-only first.")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    plugins.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o700)
    with (target / "app.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Tesla xBar is busy. Try updating after the current operation finishes.") from None
        ensure_keys(target)
        for name, binary in helpers.items():
            atomic_install(binary.read_bytes(), target / name, 0o700)
        atomic_install((source / "tesla_xbar.py").read_bytes(), target / "tesla_xbar.py", 0o600)
        launcher = ("#!/bin/bash\nexec " + shlex.quote(python or sys.executable) + " "
                    + shlex.quote(str(target / "tesla_xbar.py")) + ' "$@"\n')
        atomic_install(launcher.encode(), target / "tesla-action.sh", 0o700)
        wrapper = ("#!/bin/bash\n# <xbar.title>Tesla Battery</xbar.title>\n"
                   f"# <xbar.version>{VERSION}</xbar.version>\n"
                   "# <xbar.desc>Tesla battery status via Fleet API. Data stays on your Mac.</xbar.desc>\n"
                   "exec " + shlex.quote(str(target / "tesla-action.sh")) + " menu\n")
        atomic_install(wrapper.encode(), plugin, 0o700)
    return plugin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true", help="Update code using the already installed helpers")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Tesla xBar requires macOS.")
    source = Path(__file__).resolve().parent
    target = Path.home() / "Library/Application Support/Tesla xBar"
    plugins = Path.home() / "Library/Application Support/xbar/plugins"
    try:
        plugin = install(source, target, plugins, runtime_only=args.runtime_only)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Installation failed. Check your build tools and filesystem permissions.", file=sys.stderr)
        return 1
    print(f"Installed: {plugin}")
    print(f"Private profile preserved in: {target}")
    print(f"Public key to host: {target / 'public-key.pem'}")
    print("New setup: open Settings in xBar, register your own Tesla app, then connect your account. See docs/SETUP.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
