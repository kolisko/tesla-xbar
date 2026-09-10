"""Audit the command helper's dependencies with its CLI adapter materialized."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def materialize_sources(checkout, adapter, destination):
    # govulncheck's parser reads source paths directly, unlike the Go compiler's
    # overlay support. Keep the pinned checkout untouched and audit a full copy.
    shutil.copytree(checkout, destination, ignore=shutil.ignore_patterns(".git"))
    for source in adapter.glob("*.go"):
        shutil.copyfile(source, destination / "cmd" / "tesla-control" / ("xbar_" + source.name))


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "build"
    checkout = build / "vehicle-command"
    if not (build / "command-overlay.json").is_file():
        raise RuntimeError("Build the command helper before auditing it.")
    env = {key: value for key, value in os.environ.items() if key != "GOFLAGS"}
    env.update(GOCACHE=str(build / "go-cache"), GOMODCACHE=str(build / "go-modules"), GOTOOLCHAIN="local")
    with tempfile.TemporaryDirectory(prefix="command-audit-", dir=build) as directory:
        destination = Path(directory) / "source"
        materialize_sources(checkout, root / "src" / "commands", destination)
        subprocess.run(["go", "run", "golang.org/x/vuln/cmd/govulncheck@v1.7.0",
                        "-C", str(destination), "./cmd/tesla-control"], env=env, check=True)


if __name__ == "__main__":
    main()
