"""Build a pinned version of Tesla's official command-line tool."""
import os
import json
from pathlib import Path
import subprocess

SDK_REVISION = "f97fa1e4bf617a364c72b85cb5d859528abeda67"


def build_commands():
    build = Path(__file__).resolve().parents[1] / "build"
    checkout = build / "vehicle-command"
    build.mkdir(exist_ok=True)
    if not (checkout / ".git").is_dir():
        checkout.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                        "https://github.com/teslamotors/vehicle-command.git"], check=True)
        subprocess.run(["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", SDK_REVISION], check=True)
        subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", SDK_REVISION], check=True)
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if revision != SDK_REVISION:
        raise RuntimeError("Tesla SDK checkout does not match the pinned revision.")
    subprocess.run(["git", "-C", str(checkout), "diff", "--exit-code", "HEAD", "--"], check=True)
    env = os.environ | {"GOCACHE": str(build / "go-cache"), "GOMODCACHE": str(build / "go-modules"), "GOTOOLCHAIN": "local"}
    overlay = build / "command-overlay.json"
    adapter = Path(__file__).resolve().parents[1] / "src" / "commands"
    replacements = {str(checkout / "cmd" / "tesla-control" / ("xbar_" + source.name)): str(source)
                    for source in adapter.glob("*.go")}
    overlay.write_text(json.dumps({"Replace": replacements}))
    subprocess.run(["go", "test", "-C", str(checkout), "-overlay", str(overlay),
                    "-run", "TestXBarClimateKeeperMode", "./cmd/tesla-control"], env=env, check=True)
    binary = build / "tesla-control"
    subprocess.run(["go", "build", "-C", str(checkout), "-overlay", str(overlay),
                    "-trimpath", "-o", str(binary), "./cmd/tesla-control"], env=env, check=True)
    return binary


if __name__ == "__main__":
    print(build_commands())
