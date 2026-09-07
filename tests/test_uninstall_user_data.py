"""Optional uninstall data cleanup: policy and isolated native Pascal tests."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / 'packaging/DPort.iss').read_text(encoding='utf-8')
BEGIN = '{ ===== DPORT OPTIONAL USER DATA BEGIN ===== }'
END = '{ ===== DPORT OPTIONAL USER DATA END ===== }'
BLOCK = TEXT.split(BEGIN, 1)[1].split(END, 1)[0]
CACHE = TEXT.split('procedure CleanupUninstallCache();', 1)[1].split('function InitializeUninstall()', 1)[0]


class UserDataUninstallTests(unittest.TestCase):
    def test_opt_in_and_post_uninstall_only(self):
        init = TEXT.split('function InitializeUninstall(): Boolean;', 1)[1].split('function PrepareToInstall', 1)[0]
        self.assertIn('DeleteUserSettings := False;', init)
        self.assertIn('if not UserUninstallUI then exit;', init)
        self.assertIn('/SILENT /DPORTUI=1 /NORESTART', TEXT)
        self.assertIn("ExpandConstant('{param:DPORTUI|0}') = '1'", init)
        self.assertIn('Option.Checked := False;', init)
        self.assertIn('LogOption.Checked := False;', init)
        self.assertIn('DeleteUserLog := UninstallOptionsAccepted and LogOption.Checked;', init)
        self.assertIn('UninstallProgressForm.ShowModal() = mrOK', init)
        self.assertNotIn('CreateCustomForm', init)
        self.assertIn('if not UninstallOptionsAccepted then Abort;', TEXT)
        self.assertIn('UninstallOptionsAccepted and Option.Checked', init)
        self.assertIn('(CurUninstallStep = usPostUninstall) and (DeleteUserSettings or DeleteUserLog)', TEXT)
        self.assertEqual(TEXT.count('DeleteSelectedUserData(UninstallUserDataPath, DeleteUserSettings, DeleteUserLog)'), 1)

    def test_direct_launch_hands_off_before_any_mutation(self):
        init = TEXT.split('function InitializeUninstall(): Boolean;', 1)[1].split('procedure InitializeUninstallProgressForm', 1)[0]
        self.assertIn("ShellExec('open', ExpandConstant('{uninstallexe}')", init)
        self.assertIn("'/SILENT /DPORTUI=1 /NORESTART'", init)
        self.assertLess(init.index('if not UninstallSilent then begin'), init.index('StopVerifiedPassiveDPort()'))
        handoff = init.split('if not UninstallSilent then begin', 1)[1].split('UserUninstallUI :=', 1)[0]
        self.assertIn('exit;', handoff)
        self.assertNotIn('Result := True', handoff)

    def test_fixed_files_no_recursive_delete_and_locked_ancestors(self):
        self.assertIn("+ 'config.json'", BLOCK)
        self.assertIn("+ 'dport.log'", BLOCK)
        self.assertNotIn('DelTree', BLOCK)
        self.assertNotIn('RemoveDir', BLOCK)
        self.assertNotIn('commonappdata', BLOCK)
        self.assertIn('DataOpenDirectory(Paths[I], 1, 3, 0, 3, $02200000, 0)', BLOCK)
        self.assertIn('if IsRep then exit', BLOCK)
        self.assertIn('finally', BLOCK)

    @unittest.skipUnless(os.name == 'nt', 'Windows/Inno native test')
    def test_native_only_selected_files_removed(self):
        compiler = Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe'
        if not compiler.exists():
            self.skipTest('Stable Inno compiler unavailable')
        # Generated test harness operates solely in its own installer temp dir.
        code = r'''
[Setup]
AppName=DPort cleanup test
AppVersion=1
DefaultDirName={tmp}\NeverInstalled
PrivilegesRequired=lowest
Uninstallable=no
OutputBaseFilename=probe
[Code]
function GetFileAttributesW(Name: string): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function PathCanonical(const Path: string; var Canon: string): Boolean;
begin Canon := ExpandFileName(Path); Result := True; end;
function PathIsReparse(const Path: string; var IsReparse: Boolean): Boolean;
var A: LongWord;
begin
  A := GetFileAttributesW(Path);
  Result := A <> $FFFFFFFF;
  IsReparse := (A and $400) <> 0;
end;
''' + BLOCK + r'''
function ChainIsReparseFree(const Path: string; var Reason: string): Boolean;
var IsRep: Boolean;
begin Result := PathIsReparse(Path, IsRep) and not IsRep; end;
function LocationIsAclProtected(const Path: string; var Reason: string): Boolean;
begin Result := True; end;
''' + 'procedure CleanupUninstallCache();' + CACHE.replace('{commonappdata}', '{tmp}') + r'''
procedure Check(Condition: Boolean; Message: string);
begin if not Condition then RaiseException(Message); end;
function InitializeSetup(): Boolean;
var P, Report: string; H: LongWord; Choice: Integer;
begin
  Result := False;
  Report := ExpandConstant('{param:REPORT}');
  try
    P := ExpandConstant('{tmp}\DPort');
    ForceDirectories(P);
    H := DataOpenDirectory(P, 1, 3, 0, 3, $02200000, 0);
    Check(H <> $FFFFFFFF, 'directory pin failed');
    try
      Check(not RenameFile(P, P + '-moved'), 'pinned directory was movable');
    finally DataCloseHandle(H); end;
    for Choice := 0 to 3 do begin
      SaveStringToFile(P + '\config.json', 'test settings', False);
      SaveStringToFile(P + '\dport.log', 'test log', False);
      Check(DeleteSelectedUserData(P, (Choice and 1) <> 0, (Choice and 2) <> 0), 'selection failed');
      Check(FileExists(P + '\config.json') = ((Choice and 1) = 0), 'wrong settings selection');
      Check(FileExists(P + '\dport.log') = ((Choice and 2) = 0), 'wrong log selection');
    end;
    SaveStringToFile(P + '\config.json', 'synthetic settings', False);
    SaveStringToFile(P + '\dport.log', 'synthetic log', False);
    SaveStringToFile(P + '\unrelated.txt', 'preserve', False);
    Check(DeleteSelectedUserData(P, True, True), 'cleanup failed');
    Check(not FileExists(P + '\config.json'), 'config remains');
    Check(not FileExists(P + '\dport.log'), 'log remains');
    Check(FileExists(P + '\unrelated.txt'), 'unrelated file lost');
    Check(DeleteSelectedUserData(P, True, True), 'idempotency failed');
    SaveStringToFile(P + '\dport.log', 'locked log', False);
    H := DataOpenDirectory(P + '\dport.log', $80000000, 0, 0, 3, 0, 0);
    Check(H <> $FFFFFFFF, 'could not lock test file');
    try
      Check(not DeleteSelectedUserData(P, True, True), 'locked file reported success');
      Check(FileExists(P + '\dport.log'), 'locked log lost');
    finally DataCloseHandle(H); end;
    Check(DeleteSelectedUserData(P, True, True), 'retry failed');
    ForceDirectories(P + '\config.json');
    Check(not DeleteSelectedUserData(P, True, True), 'directory accepted as config');
    Check(DirExists(P + '\config.json'), 'directory removed');
    ForceDirectories(P + '\updates');
    SaveStringToFile(P + '\updates\DPort-Setup-3.17.exe', 'old test installer', False);
    SaveStringToFile(P + '\updates\unrelated.exe', 'preserve', False);
    SaveStringToFile(P + '\dns_state.json', 'preserve recovery', False);
    CleanupUninstallCache();
    Check(not FileExists(P + '\updates\DPort-Setup-3.17.exe'), 'cache installer remains');
    Check(FileExists(P + '\updates\unrelated.exe'), 'unknown cache file removed');
    Check(FileExists(P + '\dns_state.json'), 'recovery data removed');
    DeleteFile(P + '\updates\unrelated.exe');
    CleanupUninstallCache();
    Check(not DirExists(P + '\updates'), 'empty cache remains');
    SaveStringToFile(Report, 'PASS', False);
  except
    SaveStringToFile(Report, 'FAIL: ' + GetExceptionMessage, False);
  end;
end;
'''
        with tempfile.TemporaryDirectory(prefix='dport-uninstall-test-') as tmp:
            base = Path(tmp)
            script = base / 'probe.iss'
            script.write_text(code, encoding='utf-8-sig')
            compiled = subprocess.run([str(compiler), '/Q', '/O' + tmp, str(script)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            report = base / 'result.txt'
            run = subprocess.run([str(base / 'probe.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                                  '/REPORT=' + str(report)], capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 1)  # InitializeSetup intentionally cancels.
            self.assertEqual(report.read_text(encoding='utf-8-sig'), 'PASS')


if __name__ == '__main__':
    unittest.main()
