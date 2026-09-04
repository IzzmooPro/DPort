"""Persistent recovery compatibility; only isolated temporary files are used."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core import secure_store
from test_dns_snapshots import gui_method, snapshot


class DnsPersistence(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (("secure_root", str(self.root)),
                            ("apply_protected_acl", True),
                            ("written_by_privileged_process", True),
                            ("is_reparse_point", False)):
            p = patch.object(secure_store, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.old = {"Ethernet": {
            "ipv4": {"dhcp": False, "primary": "8.8.8.8", "secondary": "1.1.1.1"},
            "ipv6": {"dhcp": True, "primary": None}}}

    def test_old_envelope_survives_save_and_restart_read(self):
        self.assertTrue(secure_store.save_dns_backup(self.old))
        self.assertEqual(secure_store.load_dns_backup(), self.old)
        envelope = json.loads((self.root / secure_store.DNS_STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(envelope, {"version": 1, "dns_backup": self.old})

    def test_failures_preserve_old_backup_and_clean_temporary_file(self):
        self.assertTrue(secure_store.save_dns_backup(self.old))
        newer = {**self.old, "Wi-Fi": snapshot()}
        for target, kwargs in (
            ("apply_protected_acl", {"return_value": False}),
            ("written_by_privileged_process", {"return_value": False}),
            ("os.fsync", {"side_effect": OSError("disk full")}),
            ("os.replace", {"side_effect": PermissionError("locked")}),
        ):
            with self.subTest(target=target), patch("core.secure_store." + target, **kwargs):
                self.assertFalse(secure_store.save_dns_backup(newer))
            self.assertEqual(secure_store.load_dns_backup(), self.old)
            self.assertEqual([p.name for p in self.root.iterdir()], [secure_store.DNS_STATE_FILE])

    def test_readback_mismatch_is_not_success(self):
        with patch.object(secure_store, "load_dns_backup", return_value={}):
            self.assertFalse(secure_store.save_dns_backup(self.old))

    def test_store_unavailable_is_failure(self):
        with patch.object(secure_store, "secure_root", return_value=None):
            self.assertFalse(secure_store.save_dns_backup(self.old))

    def test_new_activation_retains_old_original_and_adds_adapter(self):
        self.assertTrue(secure_store.save_dns_backup(self.old))
        app = types.SimpleNamespace(_get_dns_backup=secure_store.load_dns_backup,
                                    _dns_backup_mem={}, log_mgr=Mock())
        app._set_dns_backup = types.MethodType(
            gui_method("_set_dns_backup", secure_store=secure_store), app)
        gui_method("_backup_dns", get_dns=lambda name: snapshot())(
            app, [{"name": "Ethernet"}, {"name": "Wi-Fi"}])
        stored = secure_store.load_dns_backup()
        self.assertEqual(stored["Ethernet"]["ipv4"]["servers"], ["8.8.8.8", "1.1.1.1"])
        self.assertEqual(stored["Wi-Fi"]["ipv4"]["servers"], snapshot()["ipv4"]["servers"])

    def test_launcher_uses_same_python_and_pinned_requirements(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/Calistir.bat").read_text(encoding="utf-8")
        self.assertIn('python -m pip install -r "%ROOT%\\requirements.txt"', source)
        self.assertIn('if errorlevel 1 (', source)
        self.assertIn('python "app\\main.py" --source-dev', source)
        self.assertNotIn('pip install Pillow', source)

    def test_actual_backup_failure_blocks_activation_in_both_modes(self):
        for source_dev in (False, True):
            with self.subTest(source_dev=source_dev):
                app = Mock()
                app._dns_backup_mem = {}
                app._get_dns_backup = lambda: {}
                app._set_dns_backup = types.MethodType(
                    gui_method("_set_dns_backup", secure_store=secure_store), app)
                app._backup_dns = types.MethodType(
                    gui_method("_backup_dns", get_dns=lambda name: snapshot()), app)
                setter = Mock()
                lang = {k: k for k in ("st_setting_dns", "st_dns_backup_failed")}
                activate = gui_method(
                    "_activate_connection_w", _source_dev_mode=lambda: source_dev,
                    get_active_adapters=lambda: [{"name": "Ethernet"}],
                    set_dns=setter, L=lang, YELL="yellow", RED="red")
                with patch.object(secure_store, "apply_protected_acl", return_value=False):
                    activate(app)
                setter.assert_not_called()
                app._enable_discord_unblock.assert_not_called()
                app._restore_dns.assert_not_called()
                app._st.assert_any_call("st_dns_backup_failed", "red")

    def test_old_backup_can_restore_even_when_store_cannot_write(self):
        app = types.SimpleNamespace(
            _get_dns_backup=lambda: self.old, _set_dns_backup=Mock(return_value=False),
            _live_adapter_names=lambda: {"Ethernet"}, log_mgr=Mock())
        from core.dns_manager import normalize_snapshot
        app._sanitize_dns_snapshot = normalize_snapshot
        restore = Mock(return_value=(True, "OK"))
        self.assertTrue(gui_method("_restore_dns", restore_dns=restore)(app))
        self.assertEqual(restore.call_args.args[1]["ipv4"]["servers"], ["8.8.8.8", "1.1.1.1"])


if __name__ == "__main__":
    unittest.main()
