"""Updates must never start while DPort's connection path is active."""
from pathlib import Path
import sys
import types
import unittest
import os
import subprocess
import tempfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from gui import app as gui_app  # noqa: E402


class UpdateActiveGuard(unittest.TestCase):
    def app(self, active=False):
        app = gui_app.DPortApp.__new__(gui_app.DPortApp)
        app._connection_action_mode = "restore" if active else "activate"
        app._unblocker = types.SimpleNamespace(is_active=lambda: False)
        app._alive = True
        app._busy = False
        app._update_download_active = False
        app.log_mgr = types.SimpleNamespace(write=Mock())
        app._notify = Mock()
        app._st = Mock()
        app._update_checks = types.SimpleNamespace(request=Mock())
        app._prompt_update = Mock()
        app.after = Mock()
        return app

    def passive(self, app):
        return patch.multiple(
            gui_app, is_hosts_redirect_active=Mock(return_value=False))

    def test_passive_connection_allows_update(self):
        app = self.app()
        with self.passive(app), patch.object(gui_app.secure_store, "load_dns_backup", return_value={}):
            self.assertFalse(app._update_connection_is_active())
            app._check_update_clicked()
        app._update_checks.request.assert_called_once_with(manual=True)

    def test_active_connection_cancels_manual_check(self):
        app = self.app(active=True)
        app._check_update_clicked()
        app._update_checks.request.assert_not_called()
        app._notify.assert_called_once_with(
            gui_app.L["update_title"], gui_app.L["update_active_blocked"])

    def test_available_update_is_not_prompted_while_active(self):
        app = self.app(active=True)
        app._deliver_update_check({"available": True}, None, False)
        app._prompt_update.assert_not_called()

    def test_persistent_backup_or_hosts_residue_blocks_update(self):
        for backup, hosts in (({"Ethernet": {}}, False), ({}, True)):
            with self.subTest(backup=bool(backup), hosts=hosts):
                app = self.app()
                with patch.object(gui_app.secure_store, "load_dns_backup", return_value=backup), \
                     patch.object(gui_app, "is_hosts_redirect_active", return_value=hosts):
                    self.assertTrue(app._update_connection_is_active())

    def test_unknown_connection_state_fails_closed(self):
        app = self.app()
        app._unblocker = types.SimpleNamespace(is_active=Mock(side_effect=OSError("unknown")))
        self.assertTrue(app._update_connection_is_active())

    def test_download_is_not_started_if_connection_became_active(self):
        app = self.app(active=True)
        with patch.object(gui_app, "download_update") as download:
            self.assertIsNone(app._download_and_launch_update({"version": "3.16"}))
        download.assert_not_called()
        app.after.assert_called_once_with(
            0, app._report_update_cancelled_for_active_connection)


class InstallerActiveGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / "packaging/DPort.iss").read_text(encoding="utf-8")

    def test_force_close_is_gated_by_persistent_active_state(self):
        self.assertIn("CloseApplications=no", self.text)
        block = self.text[self.text.index("function ConnectionRequiresRestore"):
                          self.text.index("procedure CurStepChanged")]
        self.assertIn("{commonappdata}\\DPort\\dns_state.json", block)
        self.assertIn("HostsHasDPortResidue", block)
        self.assertIn("function StopVerifiedPassiveDPort", block)
        self.assertIn("PathIsVerifiedInstall", block)
        self.assertIn("ExecutablePath,$target", block)
        self.assertIn("Stop-Process -Id $p.ProcessId -Force", block)
        self.assertIn("function PrepareToInstall", block)
        self.assertIn("{cm:ActiveConnectionBlock}", block)

    def test_real_uninstall_gate_with_stubbed_system_operations(self):
        compiler = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Inno Setup 6/ISCC.exe'
        if not compiler.is_file():
            self.skipTest('Inno Setup compiler unavailable')
        logic = self.text[self.text.index('function InitializeUninstall():'):
                          self.text.index('procedure InitializeUninstallProgressForm(')]
        # Run the real gate in a non-installing, non-elevated harness. Suppress
        # only dialogs, not the active-state or process-stop decisions.
        logic = logic.replace('UninstallSilent', 'True')
        script = r'''
[Setup]
AppName=DPort guard test
AppVersion=1
DefaultDirName={tmp}\dport-guard-test
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputBaseFilename=guard-test
[Code]
var Active, StopOK: Boolean; Calls: Integer;
    DeleteUserSettings, DeleteUserLog: Boolean; UninstallUserDataPath: string;
    UninstallOptionsAccepted, UserUninstallUI: Boolean;
function ConnectionRequiresRestore(): Boolean;
begin Result := Active; end;
function StopVerifiedPassiveDPort(): Boolean;
begin Calls := Calls + 1; Result := StopOK; end;
__LOGIC__
function InitializeSetup(): Boolean;
var Rows: TArrayOfString;
begin
  SetArrayLength(Rows, 3);
  Active := True; StopOK := True; Calls := 0;
  if (not InitializeUninstall()) and (Calls = 0) then Rows[0] := 'active:OK';
  Active := False; StopOK := False; Calls := 0;
  if (not InitializeUninstall()) and (Calls = 1) then Rows[1] := 'stop_failed:OK';
  StopOK := True; Calls := 0;
  if InitializeUninstall() and (Calls = 1) and (not DeleteUserSettings) and (not DeleteUserLog) then Rows[2] := 'passive:OK';
  SaveStringsToFile(ExpandConstant('{param:Out}'), Rows, False);
  Result := False;
end;
'''.replace('__LOGIC__', logic)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / 'guard.iss'
            source.write_text(script, encoding='utf-8')
            compiled = subprocess.run([str(compiler), '/Q', '/O' + directory, str(source)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            output = path / 'result.txt'
            subprocess.run([str(path / 'guard-test.exe'), '/VERYSILENT', '/Out=' + str(output)],
                           capture_output=True, timeout=30)
            self.assertEqual(output.read_text(encoding='utf-8-sig').splitlines(),
                             ['active:OK', 'stop_failed:OK', 'passive:OK'])


if __name__ == "__main__":
    unittest.main()
