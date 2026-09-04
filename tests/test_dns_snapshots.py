"""DNS regression tests. Every subprocess and persistent store is mocked."""
import ast
import copy
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from core import dns_manager as dns  # noqa: E402


def snapshot():
    return {
        "ipv4": {"dhcp": False, "servers": ["1.1.1.1", "8.8.8.8", "9.9.9.9"]},
        "ipv6": {"dhcp": False, "servers": ["2001:4860:4860::8888", "2606:4700:4700::1111"]},
    }


def gui_method(name, **scope):
    tree = ast.parse((ROOT / "app/gui/app.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DPortApp")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {"normalize_snapshot": dns.normalize_snapshot, **scope}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<gui-dns-test>", "exec"), env)
    return env[name]


class DnsSnapshots(unittest.TestCase):
    def setUp(self):
        self.runner = patch.object(dns.subprocess, "run", side_effect=AssertionError("Unmocked subprocess"))
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def test_order_and_all_servers_preserved(self):
        self.assertEqual(dns.normalize_snapshot(snapshot())["ipv4"]["servers"],
                         ["1.1.1.1", "8.8.8.8", "9.9.9.9"])

    def test_complete_legacy_snapshot_supported(self):
        old = {"ipv4": {"dhcp": False, "primary": "8.8.8.8", "secondary": "1.1.1.1"},
               "ipv6": {"dhcp": True, "primary": None}}
        self.assertEqual(dns.normalize_snapshot(old)["ipv4"]["servers"], ["8.8.8.8", "1.1.1.1"])

    def test_invalid_snapshot_never_writes(self):
        samples = [None, {}, {"ipv4": {"dhcp": True}}]
        for field, value in [("dhcp", "false"), ("servers", []),
                             ("servers", ["8.8.8.8 & calc"]), ("servers", ["::1"])]:
            data = snapshot()
            data["ipv4"][field] = value
            samples.append(data)
        for data in samples:
            with self.subTest(data=data):
                self.assertFalse(dns.restore_dns("Ethernet", data)[0])

    def test_read_failure_never_becomes_dhcp(self):
        for result in [subprocess.CompletedProcess([], 1, "", "error"),
                       subprocess.CompletedProcess([], 0, "{}", ""),
                       subprocess.CompletedProcess([], 0, "not json", ""),
                       subprocess.TimeoutExpired("powershell", 15)]:
            with self.subTest(result=result):
                with patch.object(dns.subprocess, "run") as run:
                    if isinstance(result, Exception):
                        run.side_effect = result
                    else:
                        run.return_value = result
                    with self.assertRaises(dns.DnsSnapshotError):
                        dns.get_dns("Ethernet")

    def test_structured_read_and_alias_is_data(self):
        raw = snapshot()
        for family in raw.values():
            family["effective"] = family["servers"][:]
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, json.dumps(raw), "")) as run:
            result = dns.get_dns("Ağ '$(); test")
        self.assertEqual(result["ipv4"]["servers"], raw["ipv4"]["servers"])
        self.assertNotIn("Ağ '$(); test", run.call_args.args[0][-1])
        self.assertIn("OpenSubKey($path, $false)", run.call_args.args[0][-1])

    def test_disabled_family_preserves_configured_servers(self):
        raw = snapshot()
        for family in raw.values():
            family["effective"] = []
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, json.dumps(raw), "")):
            actual = dns.get_dns("Ethernet")
        self.assertEqual(actual["ipv6"]["servers"], raw["ipv6"]["servers"])

    def test_all_restore_commands_and_readback(self):
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, "", "")) as run, \
             patch.object(dns, "get_dns", return_value=snapshot()):
            self.assertTrue(dns.restore_dns("Ethernet", snapshot())[0])
        commands = [c.args[0] for c in run.call_args_list]
        self.assertEqual(len(commands), 5)
        self.assertIn("9.9.9.9", commands[2])
        self.assertIn("index=3", commands[2])

    def test_ipv6_errors_are_failures(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, int(command[2] == "ipv6"), "", "blocked")
        with patch.object(dns.subprocess, "run", side_effect=run):
            self.assertFalse(dns.restore_dns("Ethernet", snapshot())[0])

    def test_success_exit_but_wrong_readback_is_failure(self):
        wrong = snapshot()
        wrong["ipv4"]["servers"].reverse()
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, "", "")), \
             patch.object(dns, "get_dns", return_value=wrong):
            self.assertFalse(dns.restore_dns("Ethernet", snapshot())[0])

    def test_readback_failure_keeps_failure(self):
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, "", "")), \
             patch.object(dns, "get_dns", side_effect=dns.DnsSnapshotError("offline")):
            self.assertFalse(dns.restore_dns("Ethernet", snapshot())[0])

    def test_automatic_restored_as_automatic(self):
        data = {f: {"dhcp": True, "servers": []} for f in ("ipv4", "ipv6")}
        with patch.object(dns.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, "", "")) as run, \
             patch.object(dns, "get_dns", return_value=data):
            self.assertTrue(dns.restore_dns("Ethernet", data)[0])
        self.assertTrue(all(c.args[0][-1] == "dhcp" for c in run.call_args_list))

    def test_guid_change_blocks_writes(self):
        data = snapshot()
        data["interface_guid"] = "00000000-0000-0000-0000-000000000001"
        other = copy.deepcopy(data)
        other["interface_guid"] = "00000000-0000-0000-0000-000000000002"
        with patch.object(dns, "get_dns", return_value=other):
            self.assertFalse(dns.restore_dns("Ethernet", data)[0])

    def test_backup_batch_failure_does_not_save_partial_snapshot(self):
        app = types.SimpleNamespace(_get_dns_backup=lambda: {}, _set_dns_backup=Mock(),
                                    log_mgr=Mock())
        reader = Mock(side_effect=[snapshot(), dns.DnsSnapshotError("unknown")])
        method = gui_method("_backup_dns", get_dns=reader)
        with self.assertRaises(dns.DnsSnapshotError):
            method(app, [{"name": "Ethernet"}, {"name": "Wi-Fi"}])
        app._set_dns_backup.assert_not_called()

    def test_existing_backup_preserved_new_adapter_added(self):
        original = {"Ethernet": snapshot()}
        app = types.SimpleNamespace(_get_dns_backup=lambda: original,
                                    _set_dns_backup=Mock(), log_mgr=Mock())
        reader = Mock(return_value=snapshot())
        gui_method("_backup_dns", get_dns=reader)(app, [{"name": "Ethernet"}, {"name": "Wi-Fi"}])
        self.assertEqual([c.args[0] for c in reader.call_args_list], ["Ethernet", "Wi-Fi"])
        self.assertEqual(set(app._set_dns_backup.call_args.args[0]), {"Ethernet", "Wi-Fi"})

    def test_invalid_and_failed_restore_keep_backup(self):
        for data, result in [({}, (True, "OK")), (snapshot(), (False, "IPv6 failed"))]:
            app = types.SimpleNamespace(
                _get_dns_backup=lambda: {"Ethernet": data}, _set_dns_backup=Mock(),
                _live_adapter_names=lambda: {"Ethernet"},
                _sanitize_dns_snapshot=dns.normalize_snapshot, log_mgr=Mock())
            restore = Mock(return_value=result)
            self.assertFalse(gui_method("_restore_dns", restore_dns=restore)(app))
            self.assertIn("Ethernet", app._set_dns_backup.call_args.args[0])
            if not data:
                restore.assert_not_called()

    def test_activation_stops_before_mutation_when_backup_fails(self):
        for problem in ("backup", "apply"):
            with self.subTest(problem=problem):
                app = Mock()
                app._preflight_failsafe_target.return_value = True
                app._preflight_discord_unblock.return_value = True
                if problem == "backup":
                    app._backup_dns.side_effect = dns.DnsSnapshotError("unknown")
                setter = Mock(return_value=(False, "IPv6 failed"))
                lang = {k: k for k in ("st_setting_dns", "st_dns_backup_failed",
                                      "st_dns_apply_failed", "st_no_adapter", "st_path_prep")}
                method = gui_method(
                    "_activate_connection_w", set_dns=setter, L=lang,
                    _source_dev_mode=lambda: False,
                    get_active_adapters=lambda: [{"name": "Ethernet"}],
                    DNS_V4=["1.1.1.1", "1.0.0.1"],
                    DNS_V6=["2606:4700:4700::1111", "2606:4700:4700::1001"],
                    YELL="yellow", RED="red", GREEN="green",
                )
                method(app)
                app._enable_discord_unblock.assert_not_called()
                if problem == "backup":
                    setter.assert_not_called()
                    app._restore_dns.assert_not_called()
                else:
                    app._restore_dns.assert_called_once()

    def test_ipv6_set_failure_is_not_success(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, int(command[2] == "ipv6"), "", "failed")
        with patch.object(dns.subprocess, "run", side_effect=run):
            self.assertFalse(dns.set_dns("Ethernet", "1.1.1.1", "1.0.0.1",
                                        "2606:4700:4700::1111", "2606:4700:4700::1001")[0])


if __name__ == "__main__":
    unittest.main()
