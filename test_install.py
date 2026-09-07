from pathlib import Path
import tempfile
import unittest

import install


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target, self.plugins = (self.root / name for name in ("source", "profile", "plugins"))
        for path in (self.source, self.target, self.plugins):
            path.mkdir()
        (self.source / "tesla_xbar.py").write_text("# generic code\n")
        for name in ("tesla-control", "tesla-keychain"):
            (self.target / name).write_bytes(b"existing helper")

    def test_new_profile_gets_unique_key_outside_source(self):
        install.ensure_keys(self.target)
        private = self.target / "command-key.pem"
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.target / "public-key.pem").stat().st_mode & 0o777, 0o600)
        self.assertIn(b"PUBLIC KEY", (self.target / "public-key.pem").read_bytes())
        self.assertEqual(list(self.source.glob("*.pem")), [])
        other = self.root / "other-profile"
        other.mkdir()
        install.ensure_keys(other)
        self.assertNotEqual(private.read_bytes(), (other / "command-key.pem").read_bytes())

    def test_update_preserves_private_profile_key_helpers_and_interval(self):
        install.ensure_keys(self.target)
        # Updating must also tighten permissions on an existing identical file.
        (self.target / "public-key.pem").chmod(0o644)
        for name in ("config.json", "cache.json", "command-result.json", "command-sessions.json"):
            (self.target / name).write_text('{"example": "preserve this value"}')
        before = {p.name: p.read_bytes() for p in self.target.iterdir() if p.is_file()}
        wrapper = self.plugins / "tesla-battery.5m.sh"
        wrapper.write_text("# old wrapper")
        result = install.install(self.source, self.target, self.plugins, runtime_only=True, python="/usr/bin/python3")
        self.assertEqual(result, wrapper)
        self.assertEqual([p.name for p in self.plugins.iterdir()], [wrapper.name])
        for name, content in before.items():
            self.assertEqual((self.target / name).read_bytes(), content, name)
        self.assertEqual((self.target / "tesla_xbar.py").read_bytes(), (self.source / "tesla_xbar.py").read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.target / "public-key.pem").stat().st_mode & 0o777, 0o600)

    def test_missing_existing_key_is_not_silently_regenerated(self):
        (self.target / "config.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "Restore"):
            install.ensure_keys(self.target)
        self.assertFalse((self.target / "command-key.pem").exists())

    def test_multiple_active_plugins_fail_before_profile_changes(self):
        for interval in ("1m", "5m"):
            (self.plugins / f"tesla-battery.{interval}.sh").touch()
        with self.assertRaisesRegex(RuntimeError, "Multiple"):
            install.install(self.source, self.target, self.plugins, runtime_only=True)
        self.assertFalse((self.target / "command-key.pem").exists())


if __name__ == "__main__":
    unittest.main()
