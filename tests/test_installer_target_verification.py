"""
tests/test_installer_target_verification.py

Installer, ONLOGON/HIGHEST gorevin hedefini BAGIMSIZ olarak dogrulamalidir.

  1) HEDEF YOLU: `FileExists` bir guvenlik kontrolu DEGILDIR. Custom `/DIR=`,
     onceki kurulumdan devralinan dizin, gevsek ACL veya junction uzerinden
     kullanici-yazilabilir bir DPort.exe HIGHEST gorevin hedefi olamaz.
     Yol canonical olmali, GERCEK Program Files koklerinden birinin altinda
     bulunmali, zincirinde reparse point olmamali ve dusuk yetkili
     principal'lar yazma/silme/ACL hakki TUTMAMALIDIR. Okunamazsa FAIL CLOSED.

  2) GOREV TANIMI: XML'de gorulen SON <Command>/<Arguments> degerine bakmak
     yetmez. Once zararli, sonra masum gorunen ikinci bir <Exec> eylemi olan
     gorev GUVENLI SAYILAMAZ. Tam olarak bir Exec, bir Command, bir Arguments,
     bir ONLOGON trigger ve beklenen RunLevel olmalidir.

GUVENLIK: Gercek schtasks/ACL/registry cagrisi YOK. Uretim `.iss` dosyasindan
AYIKLANAN Pascal karar kodu, sahte ilkellerle derlenip calistirilir; uretilen
deneme kurulumu InitializeSetup icinde IPTAL edilir (hicbir sey kurulmaz).
"""
import os
import subprocess
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ISS = os.path.join(_ROOT, "packaging", "DPort.iss")
_ISCC = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Programs", "Inno Setup 6", "ISCC.exe")

_TARGET_BEGIN = "{ ===== DPORT SAFE TARGET BEGIN ===== }"
_TARGET_END = "{ ===== DPORT SAFE TARGET END ===== }"
_TASK_BEGIN = "{ ===== DPORT FAILSAFE TASK BEGIN ===== }"
_TASK_END = "{ ===== DPORT FAILSAFE TASK END ===== }"

_SAFE_EXE = r"C:\Program Files\DPort\DPort.exe"
_PF64 = r"C:\Program Files"
_PF32 = r"C:\Program Files (x86)"

# Korumali kurulum: yazma haklari yalniz SYSTEM / Administrators / CREATOR OWNER.
# BU (Users) yalnizca oku+calistir (0x1200a9) tutar.
_SDDL_PROTECTED = ("O:SYG:SYD:PAI(A;;FA;;;SY)(A;;FA;;;BA)"
                   "(A;OICIIO;GA;;;CO)(A;;0x1200a9;;;BU)")
# Users TAM YETKI: kullanici exe'yi degistirebilir -> HIGHEST gorev hedefi olamaz.
_SDDL_LOOSE = "O:SYG:SYD:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BU)"
# Users yalniz "modify" (0x1301bf) -> yine de yazabilir.
_SDDL_MODIFY = "O:SYG:SYD:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x1301bf;;;BU)"
# Sahip normal bir kullanici hesabi: DACL'i istedigi an degistirebilir.
_SDDL_USER_OWNER = ("O:S-1-5-21-11-22-33-1001G:SYD:PAI(A;;FA;;;SY)"
                    "(A;;FA;;;BA)(A;;0x1200a9;;;BU)")
# Tanimadigimiz ACE turu / hak kisaltmasi -> fail closed.
_SDDL_UNKNOWN_ACE = "O:SYG:SYD:PAI(XA;;FA;;;BA)(A;;0x1200a9;;;BU)"
_SDDL_UNKNOWN_RIGHT = "O:SYG:SYD:PAI(A;;FA;;;SY)(A;;ZZ;;;BU)"
# Dangerous hak yalniz INHERIT-ONLY: bu nesneye uygulanmaz -> guvenli.
_SDDL_INHERIT_ONLY = ("O:SYG:SYD:PAI(A;;FA;;;SY)(A;;FA;;;BA)"
                      "(A;OICIIO;GA;;;BU)(A;;0x1200a9;;;BU)")

_GOOD_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Actions Context="Author">
    <Exec>
      <Command>C:\\Program Files\\DPort\\DPort.exe</Command>
      <Arguments>--cleanup-hosts</Arguments>
    </Exec>
  </Actions>
</Task>"""

_TWO_EXEC_XML = _GOOD_XML.replace(
    "  <Actions Context=\"Author\">\n    <Exec>",
    "  <Actions Context=\"Author\">\n"
    "    <Exec>\n"
    "      <Command>C:\\Users\\kurban\\evil.exe</Command>\n"
    "      <Arguments>--pwn</Arguments>\n"
    "    </Exec>\n"
    "    <Exec>")

_DUP_COMMAND_XML = _GOOD_XML.replace(
    "      <Arguments>--cleanup-hosts</Arguments>",
    "      <Command>C:\\Users\\kurban\\evil.exe</Command>\n"
    "      <Arguments>--cleanup-hosts</Arguments>")

_DUP_ARGS_XML = _GOOD_XML.replace(
    "      <Arguments>--cleanup-hosts</Arguments>",
    "      <Arguments>--pwn</Arguments>\n"
    "      <Arguments>--cleanup-hosts</Arguments>")

_LOW_RUNLEVEL_XML = _GOOD_XML.replace("HighestAvailable", "LeastPrivilege")
_NO_RUNLEVEL_XML = _GOOD_XML.replace(
    "      <RunLevel>HighestAvailable</RunLevel>\n", "")
_TIME_TRIGGER_XML = _GOOD_XML.replace("LogonTrigger", "TimeTrigger")
_EXTRA_TRIGGER_XML = _GOOD_XML.replace(
    "  </Triggers>", "    <TimeTrigger><Enabled>true</Enabled></TimeTrigger>\n"
                     "  </Triggers>")
_WRONG_ARGS_XML = _GOOD_XML.replace("--cleanup-hosts", "--cleanup-hosts --extra")
_WRONG_CMD_XML = _GOOD_XML.replace(
    "C:\\Program Files\\DPort\\DPort.exe",
    "C:\\Users\\kurban\\AppData\\Local\\DPort\\DPort.exe")
# Bilinen XML entity'si: cozulunce hedefe esit olmali.
_ENTITY_OK_XML = _GOOD_XML.replace(
    "<Command>C:\\Program Files\\DPort\\DPort.exe</Command>",
    "<Command>C:\\Program Files\\DPort\\DPort.exe</Command>").replace(
    "<Arguments>--cleanup-hosts</Arguments>",
    "<Arguments>--cleanup-hosts</Arguments>")
# Sayisal entity: DESTEKLENMEZ -> fail closed (deterministik).
_NUMERIC_ENTITY_XML = _GOOD_XML.replace(
    "<Arguments>--cleanup-hosts</Arguments>",
    "<Arguments>&#45;-cleanup-hosts</Arguments>")


def _pascal_str(value):
    return "'" + value.replace("'", "''") + "'"


def _pascal_lines(value):
    """Cok satirli metni Pascal string birlestirmesine cevirir."""
    parts = [_pascal_str(line) for line in value.split("\n")]
    return " + #13#10 + ".join(parts)


_HARNESS = """
[Setup]
AppName=DPort Target Verification Test
AppVersion=1.0
DefaultDirName={{tmp}}\\dport_target_test
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableStartupPrompt=yes
OutputDir=%(out)s
OutputBaseFilename=target_test

[Code]
var
  FakeCanonOk, FakeReparseOk, FakeRootsOk, FakeSddlOk: Boolean;
  FakeReparsePath: string;
  FakeSddl, FakeDirSddl: string;
  FakeCanonMap: string;
  FakeXml: string;
  FakeQueryOk, DeleteWorks, CreateWorks: Boolean;
  CreatedXml: string;
  Trace: string;

procedure Note(const S: string);
begin
  if Trace <> '' then Trace := Trace + ',';
  Trace := Trace + S;
end;

{ ── sahte ilkeller ──────────────────────────────────────────────────────── }
function PathCanonical(const Path: string; var Canon: string): Boolean;
begin
  Result := FakeCanonOk;
  if not Result then begin Canon := ''; exit; end;
  { FakeCanonMap bos degilse kaynak yol ONA cevrilir (custom dizin senaryosu) }
  if FakeCanonMap <> '' then Canon := FakeCanonMap else Canon := Path;
end;

function PathIsReparse(const Path: string; var IsReparse: Boolean): Boolean;
begin
  IsReparse := False;
  Result := FakeReparseOk;
  if not Result then exit;
  if (FakeReparsePath <> '') and (CompareText(Path, FakeReparsePath) = 0) then
    IsReparse := True;
end;

function ProgramFilesRoots(var Roots: TArrayOfString): Boolean;
begin
  Result := FakeRootsOk;
  if not Result then begin SetArrayLength(Roots, 0); exit; end;
  SetArrayLength(Roots, 2);
  Roots[0] := %(pf64)s;
  Roots[1] := %(pf32)s;
end;

function PathSddl(const Path: string; var Sddl: string): Boolean;
begin
  Result := FakeSddlOk;
  if not Result then begin Sddl := ''; exit; end;
  if (FakeDirSddl <> '') and (Pos('.exe', Lowercase(Path)) = 0) then
    Sddl := FakeDirSddl
  else
    Sddl := FakeSddl;
end;

function TaskQueryXml(const Name: string; var Xml: string): Boolean;
begin
  Note('query:' + Name);
  Xml := '';
  if Name <> 'DPortHostsFailsafe' then begin Result := False; exit; end;
  Result := FakeQueryOk;
  if Result then Xml := FakeXml;
end;

function TaskDeleteVerified(const Name: string): Boolean;
begin
  Note('delete:' + Name);
  Result := DeleteWorks;
  if Result and (Name = 'DPortHostsFailsafe') then begin
    FakeQueryOk := False; FakeXml := '';
  end;
end;

function TaskCreateLogon(const Name, Exe, Args: string): Boolean;
begin
  Note('create:' + Name);
  Result := CreateWorks;
  if not Result then exit;
  FakeQueryOk := True;
  FakeXml := CreatedXml;
end;

%(logic)s

{ ── senaryo surucusu ────────────────────────────────────────────────────── }
procedure ResetWorld();
begin
  FakeCanonOk := True; FakeReparseOk := True; FakeRootsOk := True;
  FakeSddlOk := True;
  FakeReparsePath := ''; FakeCanonMap := '';
  FakeSddl := %(protected)s; FakeDirSddl := '';
  FakeQueryOk := True; FakeXml := %(goodxml)s;
  CreatedXml := %(goodxml)s;
  DeleteWorks := True; CreateWorks := True;
  Trace := '';
end;

function VerifyCase(const Name: string): string;
var
  Reason: string;
  Ok: Boolean;
begin
  Ok := PathIsVerifiedInstall(%(safe)s, Reason);
  Result := Name + '|';
  if Ok then Result := Result + '1' else Result := Result + '0';
  Result := Result + '|' + Reason;
end;

function XmlCase(const Name: string): string;
var
  Ok: Boolean;
begin
  Ok := TaskDefinitionIsSafe(FakeXml, %(safe)s);
  Result := Name + '|';
  if Ok then Result := Result + '1' else Result := Result + '0';
  Result := Result + '|';
end;

function ReconcileCase(const Name: string; HostsCleaned: Boolean): string;
var
  Ok: Boolean;
  Problem: string;
begin
  Trace := '';
  Ok := ReconcileFailsafeTask(HostsCleaned, %(safe)s, Problem);
  Result := Name + '|';
  if Ok then Result := Result + '1' else Result := Result + '0';
  Result := Result + '|' + Trace + '|' + Problem;
end;

function InitializeSetup(): Boolean;
var
  R: TArrayOfString;
  N: Integer;
begin
  SetArrayLength(R, 40);
  N := 0;

  { ── hedef yolu dogrulamasi ── }
  ResetWorld();
  R[N] := VerifyCase('protected_ok'); N := N + 1;

  ResetWorld(); FakeSddl := %(loose)s;
  R[N] := VerifyCase('loose_acl'); N := N + 1;

  ResetWorld(); FakeSddl := %(modify)s;
  R[N] := VerifyCase('modify_acl'); N := N + 1;

  ResetWorld(); FakeDirSddl := %(loose)s;
  R[N] := VerifyCase('loose_parent_dir'); N := N + 1;

  ResetWorld(); FakeSddl := %(userowner)s;
  R[N] := VerifyCase('user_owner'); N := N + 1;

  ResetWorld(); FakeSddl := %(unknownace)s;
  R[N] := VerifyCase('unknown_ace'); N := N + 1;

  ResetWorld(); FakeSddl := %(unknownright)s;
  R[N] := VerifyCase('unknown_right'); N := N + 1;

  ResetWorld(); FakeSddl := %(inheritonly)s;
  R[N] := VerifyCase('inherit_only'); N := N + 1;

  ResetWorld(); FakeSddlOk := False;
  R[N] := VerifyCase('sddl_unreadable'); N := N + 1;

  ResetWorld(); FakeReparseOk := False;
  R[N] := VerifyCase('reparse_unreadable'); N := N + 1;

  ResetWorld(); FakeReparsePath := %(pf64)s + '\\DPort';
  R[N] := VerifyCase('junction_parent'); N := N + 1;

  ResetWorld(); FakeReparsePath := %(safe)s;
  R[N] := VerifyCase('junction_exe'); N := N + 1;

  ResetWorld(); FakeCanonOk := False;
  R[N] := VerifyCase('canon_fails'); N := N + 1;

  ResetWorld(); FakeRootsOk := False;
  R[N] := VerifyCase('roots_unreadable'); N := N + 1;

  { custom /DIR= : kullanici-yazilabilir konum, Program Files ALTINDA DEGIL }
  ResetWorld(); FakeCanonMap := 'C:\\Users\\kurban\\DPort\\DPort.exe';
  R[N] := VerifyCase('custom_dir'); N := N + 1;

  { metinsel onek numarasi: "C:\\Program Files Sahte\\..." kok altinda DEGILDIR }
  ResetWorld(); FakeCanonMap := 'C:\\Program Files Sahte\\DPort\\DPort.exe';
  R[N] := VerifyCase('prefix_lookalike'); N := N + 1;

  { ── gorev XML dogrulamasi ── }
  ResetWorld(); R[N] := XmlCase('xml_good'); N := N + 1;
  ResetWorld(); FakeXml := %(twoexec)s;
  R[N] := XmlCase('xml_two_exec'); N := N + 1;
  ResetWorld(); FakeXml := %(dupcmd)s;
  R[N] := XmlCase('xml_dup_command'); N := N + 1;
  ResetWorld(); FakeXml := %(dupargs)s;
  R[N] := XmlCase('xml_dup_args'); N := N + 1;
  ResetWorld(); FakeXml := %(lowrun)s;
  R[N] := XmlCase('xml_low_runlevel'); N := N + 1;
  ResetWorld(); FakeXml := %(norun)s;
  R[N] := XmlCase('xml_no_runlevel'); N := N + 1;
  ResetWorld(); FakeXml := %(timetrig)s;
  R[N] := XmlCase('xml_time_trigger'); N := N + 1;
  ResetWorld(); FakeXml := %(extratrig)s;
  R[N] := XmlCase('xml_extra_trigger'); N := N + 1;
  ResetWorld(); FakeXml := %(wrongargs)s;
  R[N] := XmlCase('xml_wrong_args'); N := N + 1;
  ResetWorld(); FakeXml := %(wrongcmd)s;
  R[N] := XmlCase('xml_wrong_cmd'); N := N + 1;
  ResetWorld(); FakeXml := %(numeric)s;
  R[N] := XmlCase('xml_numeric_entity'); N := N + 1;
  ResetWorld(); FakeXml := '';
  R[N] := XmlCase('xml_empty'); N := N + 1;

  { ── uctan uca uzlastirma ── }
  ResetWorld();
  R[N] := ReconcileCase('rec_safe_kept', False); N := N + 1;

  ResetWorld(); FakeCanonMap := 'C:\\Users\\kurban\\DPort\\DPort.exe';
  R[N] := ReconcileCase('rec_custom_dir', False); N := N + 1;

  ResetWorld(); FakeSddl := %(loose)s;
  R[N] := ReconcileCase('rec_loose_acl', False); N := N + 1;

  ResetWorld(); FakeXml := %(twoexec)s;
  R[N] := ReconcileCase('rec_two_exec', False); N := N + 1;

  ResetWorld(); FakeXml := %(twoexec)s; CreatedXml := %(twoexec)s;
  R[N] := ReconcileCase('rec_readback_bad', False); N := N + 1;

  ResetWorld(); FakeXml := %(wrongargs)s;
  R[N] := ReconcileCase('rec_bad_args', False); N := N + 1;

  ResetWorld(); FakeXml := %(wrongcmd)s; CreateWorks := False;
  R[N] := ReconcileCase('rec_create_fails', False); N := N + 1;

  ResetWorld(); FakeQueryOk := False;
  R[N] := ReconcileCase('rec_unreadable_task', False); N := N + 1;

  ResetWorld(); DeleteWorks := False;
  R[N] := ReconcileCase('rec_legacy_delete_fails', True); N := N + 1;

  ResetWorld();
  R[N] := ReconcileCase('rec_clean', True); N := N + 1;

  ResetWorld(); FakeCanonMap := 'C:\\Users\\kurban\\DPort\\DPort.exe';
  R[N] := ReconcileCase('rec_custom_dir_clean', True); N := N + 1;

  SetArrayLength(R, N);
  SaveStringsToFile(ExpandConstant('{param:Out}'), R, False);
  Result := False;
end;
"""


class _Harness:
    def __init__(self, tmp, logic):
        self.tmp = tmp
        self.logic = logic

    def run(self):
        subs = {
            "out": self.tmp, "logic": self.logic,
            "safe": _pascal_str(_SAFE_EXE),
            "pf64": _pascal_str(_PF64), "pf32": _pascal_str(_PF32),
            "protected": _pascal_str(_SDDL_PROTECTED),
            "loose": _pascal_str(_SDDL_LOOSE),
            "modify": _pascal_str(_SDDL_MODIFY),
            "userowner": _pascal_str(_SDDL_USER_OWNER),
            "unknownace": _pascal_str(_SDDL_UNKNOWN_ACE),
            "unknownright": _pascal_str(_SDDL_UNKNOWN_RIGHT),
            "inheritonly": _pascal_str(_SDDL_INHERIT_ONLY),
            "goodxml": _pascal_lines(_GOOD_XML),
            "twoexec": _pascal_lines(_TWO_EXEC_XML),
            "dupcmd": _pascal_lines(_DUP_COMMAND_XML),
            "dupargs": _pascal_lines(_DUP_ARGS_XML),
            "lowrun": _pascal_lines(_LOW_RUNLEVEL_XML),
            "norun": _pascal_lines(_NO_RUNLEVEL_XML),
            "timetrig": _pascal_lines(_TIME_TRIGGER_XML),
            "extratrig": _pascal_lines(_EXTRA_TRIGGER_XML),
            "wrongargs": _pascal_lines(_WRONG_ARGS_XML),
            "wrongcmd": _pascal_lines(_WRONG_CMD_XML),
            "numeric": _pascal_lines(_NUMERIC_ENTITY_XML),
        }
        script = os.path.join(self.tmp, "target_test.iss")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_HARNESS % subs)
        r = subprocess.run([_ISCC, "/Q", script], capture_output=True,
                           text=True, timeout=300, cwd=self.tmp)
        if r.returncode != 0:
            raise AssertionError(f"harness derlenemedi:\n{r.stdout}\n{r.stderr}")
        out = os.path.join(self.tmp, "out.txt")
        if os.path.exists(out):
            os.remove(out)
        subprocess.run([os.path.join(self.tmp, "target_test.exe"), "/VERYSILENT",
                        f"/Out={out}"], capture_output=True, timeout=300)
        results = {}
        with open(out, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("|")
                results[parts[0]] = parts[1:]
        return results


class _HarnessCase(unittest.TestCase):
    results = None

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(_ISS):
            raise unittest.SkipTest("packaging/DPort.iss yok")
        with open(_ISS, encoding="utf-8", errors="ignore") as f:
            cls.text = f.read()
        cls.logic = None
        if all(m in cls.text for m in
               (_TARGET_BEGIN, _TARGET_END, _TASK_BEGIN, _TASK_END)):
            target = cls.text[cls.text.index(_TARGET_BEGIN) + len(_TARGET_BEGIN):
                              cls.text.index(_TARGET_END)]
            task = cls.text[cls.text.index(_TASK_BEGIN) + len(_TASK_BEGIN):
                            cls.text.index(_TASK_END)]
            cls.logic = target + "\n" + task

    def setUp(self):
        if type(self).logic is None:
            self.fail("packaging/DPort.iss icinde DPORT SAFE TARGET / "
                      "DPORT FAILSAFE TASK bloklari yok (hedef dogrulamasi "
                      "bagimsiz test EDILEMIYOR)")
        if not os.path.isfile(_ISCC):
            self.skipTest("Inno Setup 6 ISCC.exe bulunamadi")
        if _HarnessCase.results is None:
            _HarnessCase.results = _Harness(tempfile.mkdtemp(),
                                            type(self).logic).run()
        self.results = _HarnessCase.results

    def assertVerified(self, key, expected, msg=""):
        row = self.results[key]
        self.assertEqual(row[0] == "1", expected,
                         f"{key}: beklenen={expected} gerekce={row[1]!r} {msg}")


# ═══════════════════════════════════════════════════════════════════════════
#  1) Hedef yolu dogrulamasi
# ═══════════════════════════════════════════════════════════════════════════
class TestSafeTargetVerification(_HarnessCase):

    def test_protected_program_files_target_is_accepted(self):
        self.assertVerified("protected_ok", True)

    def test_user_writable_custom_dir_is_rejected(self):
        self.assertVerified("custom_dir", False,
                            "custom /DIR= hedefi kabul edildi")

    def test_textual_prefix_lookalike_is_rejected(self):
        self.assertVerified("prefix_lookalike", False,
                            "'C:\\Program Files Sahte' kok altinda sayildi")

    def test_loose_acl_on_exe_is_rejected(self):
        self.assertVerified("loose_acl", False)

    def test_modify_right_for_users_is_rejected(self):
        self.assertVerified("modify_acl", False)

    def test_loose_acl_on_parent_directory_is_rejected(self):
        self.assertVerified("loose_parent_dir", False,
                            "yalnizca dosyanin ACL'ine bakiliyor")

    def test_untrusted_owner_is_rejected(self):
        self.assertVerified("user_owner", False)

    def test_unknown_ace_type_fails_closed(self):
        self.assertVerified("unknown_ace", False)

    def test_unknown_rights_token_fails_closed(self):
        self.assertVerified("unknown_right", False)

    def test_inherit_only_dangerous_ace_is_ignored(self):
        self.assertVerified("inherit_only", True,
                            "INHERIT_ONLY ACE bu nesneye uygulanmaz")

    def test_unreadable_acl_fails_closed(self):
        self.assertVerified("sddl_unreadable", False)

    def test_unreadable_reparse_state_fails_closed(self):
        self.assertVerified("reparse_unreadable", False)

    def test_junction_parent_directory_is_rejected(self):
        self.assertVerified("junction_parent", False,
                            "Program Files gorunumundeki junction kabul edildi")

    def test_reparse_point_exe_is_rejected(self):
        self.assertVerified("junction_exe", False)

    def test_canonicalisation_failure_fails_closed(self):
        self.assertVerified("canon_fails", False)

    def test_unreadable_program_files_roots_fails_closed(self):
        self.assertVerified("roots_unreadable", False)

    def test_rejection_reason_is_reported(self):
        for key in ("custom_dir", "loose_acl", "junction_parent",
                    "sddl_unreadable"):
            with self.subTest(case=key):
                self.assertTrue(self.results[key][1].strip(),
                                "reddetme gerekcesi bos")


# ═══════════════════════════════════════════════════════════════════════════
#  2) Gorev tanimi (XML) dogrulamasi
# ═══════════════════════════════════════════════════════════════════════════
class TestTaskDefinitionVerification(_HarnessCase):

    def test_production_security_reads_never_use_predictable_temp_files(self):
        with open(_ISS, encoding="utf-8", errors="ignore") as handle:
            source = handle.read()
        self.assertNotIn("{tmp}\\dport_sddl.txt", source)
        self.assertNotIn("{tmp}\\dport_task_query.xml", source)
        self.assertIn("ExecAndCaptureOutput", source)

    def test_task_query_does_not_use_cmd_redirection(self):
        with open(_ISS, encoding="utf-8", errors="ignore") as handle:
            source = handle.read()
        start = source.index("function TaskQueryXml")
        end = source.index("function TaskCreateLogon", start)
        query = source[start:end]
        self.assertIn("{sys}\\schtasks.exe", query)
        self.assertNotIn("ExpandConstant('{cmd}')", query)
        self.assertNotIn(' /XML > ', query)

    def test_single_correct_definition_is_accepted(self):
        self.assertVerified("xml_good", True)

    def test_second_exec_action_is_rejected(self):
        self.assertVerified("xml_two_exec", False,
                            "ikinci Exec eylemi olan gorev guvenli sayildi")

    def test_duplicate_command_is_rejected(self):
        self.assertVerified("xml_dup_command", False)

    def test_duplicate_arguments_is_rejected(self):
        self.assertVerified("xml_dup_args", False)

    def test_low_run_level_is_rejected(self):
        self.assertVerified("xml_low_runlevel", False)

    def test_missing_run_level_is_rejected(self):
        self.assertVerified("xml_no_runlevel", False)

    def test_non_logon_trigger_is_rejected(self):
        self.assertVerified("xml_time_trigger", False)

    def test_extra_trigger_is_rejected(self):
        self.assertVerified("xml_extra_trigger", False)

    def test_extra_arguments_are_rejected(self):
        self.assertVerified("xml_wrong_args", False)

    def test_different_command_is_rejected(self):
        self.assertVerified("xml_wrong_cmd", False)

    def test_numeric_entity_fails_closed(self):
        self.assertVerified("xml_numeric_entity", False,
                            "sayisal entity davranisi deterministik degil")

    def test_empty_or_unreadable_xml_fails_closed(self):
        self.assertVerified("xml_empty", False)


# ═══════════════════════════════════════════════════════════════════════════
#  3) Uctan uca: uzlastirma hedefi dogrulanmadan gorev kurmaz/korumaz
# ═══════════════════════════════════════════════════════════════════════════
class TestReconcileRequiresVerifiedTarget(_HarnessCase):

    def _row(self, key):
        ok, trace, problem = self.results[key]
        return ok == "1", trace, problem

    def test_verified_target_with_safe_task_is_preserved(self):
        ok, trace, _ = self._row("rec_safe_kept")
        self.assertTrue(ok)
        self.assertNotIn("create:", trace)
        self.assertNotIn("delete:DPortHostsFailsafe", trace)

    def test_user_writable_custom_dir_creates_no_task_and_fails(self):
        ok, trace, problem = self._row("rec_custom_dir")
        self.assertFalse(ok, "dogrulanmamis hedefle basari bildirildi")
        self.assertNotIn("create:", trace,
                         "dogrulanmamis EXE'ye HIGHEST gorev kuruldu")
        self.assertIn("delete:DPortHostsFailsafe", trace,
                      "dogrulanmamis hedefle gorev ayakta birakildi")
        self.assertTrue(problem.strip())

    def test_loose_acl_target_creates_no_task_and_fails(self):
        ok, trace, _ = self._row("rec_loose_acl")
        self.assertFalse(ok)
        self.assertNotIn("create:", trace)

    def test_tampered_definition_is_replaced_on_verified_target(self):
        ok, trace, _ = self._row("rec_two_exec")
        self.assertTrue(ok)
        self.assertIn("delete:DPortHostsFailsafe", trace)
        self.assertIn("create:DPortHostsFailsafe", trace)

    def test_read_back_runs_the_same_checks(self):
        ok, trace, problem = self._row("rec_readback_bad")
        self.assertFalse(ok, "geri okuma ayni kontrollerden gecmiyor")
        self.assertTrue(problem.strip())
        self.assertGreater(trace.rindex("delete:DPortHostsFailsafe"),
                           trace.index("create:DPortHostsFailsafe"),
                           "dogrulanamayan gorev ayakta birakildi")

    def test_wrong_arguments_task_is_replaced(self):
        ok, trace, _ = self._row("rec_bad_args")
        self.assertTrue(ok)
        self.assertIn("create:DPortHostsFailsafe", trace,
                      "yanlis argumanli gorev guvenli sayildi")

    def test_unreadable_task_is_replaced(self):
        ok, trace, _ = self._row("rec_unreadable_task")
        self.assertTrue(ok)
        self.assertIn("create:DPortHostsFailsafe", trace)

    def test_create_failure_fails_visibly_and_leaves_no_task(self):
        ok, trace, problem = self._row("rec_create_fails")
        self.assertFalse(ok)
        self.assertTrue(problem.strip())
        self.assertIn("delete:DPortHostsFailsafe", trace,
                      "guvensiz gorev ayakta birakildi")

    def test_legacy_task_is_always_deleted_first(self):
        for key in ("rec_safe_kept", "rec_custom_dir", "rec_loose_acl",
                    "rec_two_exec", "rec_bad_args", "rec_clean"):
            with self.subTest(scenario=key):
                trace = self.results[key][1]
                self.assertIn("delete:DiscordConnectHostsFailsafe", trace,
                              "eski ad her durumda silinmeye calisilmali")
                self.assertEqual(trace.split(",")[0],
                                 "delete:DiscordConnectHostsFailsafe",
                                 "eski ad ilk sirada kaldirilmiyor")

    def test_legacy_delete_failure_stops_everything(self):
        ok, _, problem = self._row("rec_legacy_delete_fails")
        self.assertFalse(ok)
        self.assertIn("DiscordConnectHostsFailsafe", problem)

    def test_clean_hosts_needs_no_target_verification(self):
        """hosts DOGRULANMIS bicimde temizse gorev zaten silinir; hedef
        dogrulamasi gereksizdir ve kurulumu bosuna basarisiz yapmamalidir."""
        ok, trace, _ = self._row("rec_clean")
        self.assertTrue(ok)
        self.assertIn("delete:DPortHostsFailsafe", trace)
        ok2, _, _ = self._row("rec_custom_dir_clean")
        self.assertTrue(ok2, "temiz sistemde custom dizin kurulumu bozuyor")


# ═══════════════════════════════════════════════════════════════════════════
#  4) Uretim akisi bu dogrulamaya BAGLANMIS mi
# ═══════════════════════════════════════════════════════════════════════════
class TestInstallerWiring(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(_ISS):
            raise unittest.SkipTest("packaging/DPort.iss yok")
        with open(_ISS, encoding="utf-8", errors="ignore") as f:
            cls.text = f.read()

    def test_file_exists_is_not_the_security_gate(self):
        proc = self.text[self.text.index(
            "procedure DropFailsafeTaskAfterHostsCleanup"):]
        proc = proc[:proc.index("procedure CurStepChanged")]
        self.assertNotIn("if not FileExists(SafeExe)", proc,
                         "FileExists hala guvenlik kapisi olarak kullaniliyor")

    def test_target_is_verified_inside_the_reconciler(self):
        block = self.text[self.text.index(_TASK_BEGIN):self.text.index(_TASK_END)]
        self.assertIn("PathIsVerifiedInstall(", block,
                      "gorev uzlastirmasi hedefi dogrulamiyor")

    def test_program_files_roots_do_not_come_from_environment(self):
        block = self.text[self.text.index(_TARGET_BEGIN):
                          self.text.index(_TARGET_END)]
        for env in ("GetEnv('ProgramFiles", "%ProgramFiles%", "ProgramW6432"):
            self.assertNotIn(env, block,
                             f"kok tespiti ortam degiskenine guveniyor: {env}")

    def test_installer_does_not_run_the_unverified_target(self):
        """Dogrulanmamis EXE yukseltilmis calistirilip 'guvenli misin' diye
        SORULMAZ; bu zaten yetki yukseltme acigi olurdu."""
        block = self.text[self.text.index(_TARGET_BEGIN):
                          self.text.index(_TARGET_END)]
        for forbidden in ("Exec(SafeExe", "ExecAsOriginalUser(SafeExe",
                          "ShellExec(SafeExe"):
            self.assertNotIn(forbidden, block)

    def test_directory_policy_is_explicit(self):
        for key in ("DisableDirPage", "UsePreviousAppDir"):
            self.assertIn(key, self.text,
                          f"{key} kurulum dizini politikasinda tanimlanmamis")

    def test_previous_custom_app_dir_is_not_silently_reused(self):
        self.assertIn("UsePreviousAppDir=no", self.text,
                      "onceki (belki guvensiz) kurulum dizini sessizce devralinir")

    # ── tasinan sozlesmeler (eski test_recovery_preflight harness'indan) ──
    def test_install_step_uses_the_reconciler_and_fails_loudly(self):
        proc = self.text[self.text.index(
            "procedure DropFailsafeTaskAfterHostsCleanup"):]
        proc = proc[:proc.index("procedure CurStepChanged")]
        self.assertIn("ReconcileFailsafeTask(", proc,
                      "kurulum adimi merkezi uzlastiriciyi kullanmiyor")
        self.assertIn("RaiseException", proc,
                      "guvenli gorev kurulamadiginda kurulum sessizce basarili "
                      "sayiliyor (silent upgrade dahil)")

    def test_reconciler_is_shared_by_silent_and_interactive_paths(self):
        proc = self.text[self.text.index(
            "procedure DropFailsafeTaskAfterHostsCleanup"):]
        proc = proc[:proc.index("procedure CurStepChanged")]
        decision = proc[:proc.index("ReconcileFailsafeTask(")]
        self.assertNotIn("WizardSilent", decision,
                         "guvenlik karari silent moda gore degisiyor")


# ═══════════════════════════════════════════════════════════════════════════
#  5) Packaging kaynagi Git'te izlenebilir olmali
# ═══════════════════════════════════════════════════════════════════════════
class TestPackagingSourceIsTrackable(unittest.TestCase):

    def test_iss_is_not_git_ignored(self):
        r = subprocess.run(["git", "check-ignore", "-v", "packaging/DPort.iss"],
                           capture_output=True, text=True, cwd=_ROOT)
        self.assertNotEqual(
            r.returncode, 0,
            f"packaging/DPort.iss hala ignored: {r.stdout.strip()}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
