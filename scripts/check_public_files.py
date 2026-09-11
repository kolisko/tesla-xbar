#!/usr/bin/env python3
"""Check tracked publishable files for private runtime data and personal identifiers."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"config.json", "cache.json", "command-result.json", "command-setup.json",
                 "command-sessions.json", "authorization.json", "setup-session.json", "action-notice.json",
                 "SETUP_STATUS.md", "ukazka-spiciho-auta.md", "display.c", "test_display.py", "location-map.png"}
PRIVATE_DIRS = {".runtime", "build", "verification-site", ".openai", ".codex", ".agents", "node_modules"}
PATTERNS = {
    "absolute personal home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "Tesla vehicle identifier": re.compile(r"\b(?:5YJ|7SA|LRW|XP7)[A-HJ-NPR-Z0-9]{14}\b"),
    "Tesla authorization code": re.compile(r"\b(?:EU|NA|CN)_[A-Za-z0-9_-]{24,}\b"),
    "personal hosted app": re.compile(r"https?://[A-Za-z0-9.-]+\.chatgpt\.site\b"),
    "credential assignment": re.compile(r'["\'](?:access_token|refresh_token|client_secret)["\']\s*:\s*["\'][A-Za-z0-9_.-]{40,}["\']'),
}


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    problems = []
    for name in filter(None, paths):
        path = Path(name)
        if (path.name in PRIVATE_NAMES or set(path.parts) & PRIVATE_DIRS
                or path.name.startswith(".env") or path.suffix in {".pem", ".key", ".p12", ".pfx", ".log"}):
            problems.append(f"{name}: private or non-release file is tracked")
        if (ROOT / path).is_symlink():
            problems.append(f"{name}: symlink cannot be published")
            continue
        data = (ROOT / path).read_bytes()
        if path.suffix == ".png":
            # Documentation PNGs must contain no text metadata or embedded profiles.
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                problems.append(f"{name}: invalid PNG")
            pos = 8
            while pos + 12 <= len(data):
                length = int.from_bytes(data[pos:pos+4], "big")
                chunk = data[pos+4:pos+8]
                if chunk in {b"tEXt", b"iTXt", b"zTXt", b"eXIf"}:
                    problems.append(f"{name}: embedded image metadata")
                pos += length + 12
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: unexpected binary file")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{name}: {label}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("Public file check passed; no private profile files or matching personal identifiers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
