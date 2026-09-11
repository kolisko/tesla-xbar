from pathlib import Path
import tempfile
import unittest

from scripts.audit_commands import materialize_sources


class CommandAuditTests(unittest.TestCase):
    def test_audit_contains_the_same_adapter_without_changing_pinned_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, adapter, destination = (root / name for name in ("sdk", "adapter", "audit"))
            cli = checkout / "cmd" / "tesla-control"
            cli.mkdir(parents=True)
            (cli / "main.go").write_text("package main\n")
            (checkout / "go.mod").write_text("module example\n")
            (checkout / ".git").mkdir()
            (checkout / ".git" / "config").write_text("repository metadata")
            adapter.mkdir()
            (adapter / "climate.go").write_text("package main\n// adapter\n")
            (adapter / "climate_test.go").write_text("package main\n// tests\n")
            materialize_sources(checkout, adapter, destination)
            self.assertEqual((destination / "go.mod").read_bytes(), (checkout / "go.mod").read_bytes())
            for source in adapter.glob("*.go"):
                self.assertEqual((destination / "cmd/tesla-control" / ("xbar_" + source.name)).read_bytes(), source.read_bytes())
                self.assertFalse((cli / ("xbar_" + source.name)).exists())
            self.assertFalse((destination / ".git").exists())
