"""
tests/test_failsafe_hardening.py

F2 duzeltmesi icin hedefli testler: HIGHEST yetkili logon gorevinin hedefi
yalnizca GERCEKTEN korumali bir kurulum yolu olabilir.

KURAL: Bu testler GERCEK zamanlanmis gorev, hosts, DNS veya registry ayari
DEGISTIRMEZ. `schtasks` cagrilari mock'lanir. ACL/sahiplik testleri yalnizca
SALT-OKUNUR sorgulardir (gercek `C:\\Program Files` ve gecici dizin uzerinde);
hicbir izin degistirilmez. Junction yalnizca gecici dizinde olusturulur.

Calistirma:
    python -m unittest discover -s tests -v
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import failsafe  # noqa: E402


def _make_junction(link, target):
    """Gecici dizinde junction olusturur (yonetici gerekmez)."""
    return subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                          capture_output=True, text=True).returncode == 0


class _SchtasksSim:
    """schtasks simulatoru — GERCEK gorev deposu CALISTIRILMAZ, modellenir.

    existing     : basta kayitli gorev adlari
    delete_rc    : /Delete donus kodu
    delete_works : /Delete gercekten siliyor mu (False = "sildim dedi ama duruyor")
    create_rc    : /Create donus kodu
    registered   : /Query /XML geri okumasinda dondurulecek <Command> (None =
                   gercekte yazilan hedef; uyusmazlik senaryosu icin zorlanabilir)
    query_raises : /Query patlasin mi (belirsizlik / fail-closed senaryosu)
    omit_command : /XML ciktisinda <Command> satiri hic olmasin (okunamaz hedef)
    """

    def __init__(self, existing=(), delete_rc=0, delete_works=True,
                 create_rc=0, registered=None, query_raises=False,
                 omit_command=False, sticky=()):
        self.existing = set(existing)
        self.sticky = set(sticky)          # silinemeyen (inatci) gorev adlari
        self.delete_rc = delete_rc
        self.delete_works = delete_works
        self.create_rc = create_rc
        self.registered = registered
        self.query_raises = query_raises
        self.omit_command = omit_command
        self.commands = {}
        self.calls = []

    @staticmethod
    def _exe_of(tr: str) -> str:
        return tr.split('"')[1] if tr.startswith('"') else tr.split(" ")[0]

    def __call__(self, cmd, *a, **kw):
        cmd = list(cmd)
        self.calls.append(cmd)
        name = cmd[cmd.index("/TN") + 1] if "/TN" in cmd else None

        if "/Query" in cmd:
            if self.query_raises:
                raise OSError("schtasks calistirilamadi")
            if name not in self.existing:
                return subprocess.CompletedProcess(cmd, 1, "", "bulunamadi")
            if "/XML" in cmd:
                if self.omit_command:
                    return subprocess.CompletedProcess(cmd, 0, "<Task/>", "")
                value = self.registered if self.registered is not None \
                    else self.commands.get(name, "")
                return subprocess.CompletedProcess(
                    cmd, 0, f"<Task>\n  <Command>{value}</Command>\n</Task>", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        if "/Delete" in cmd:
            if self.delete_works and name not in self.sticky:
                self.existing.discard(name)
            return subprocess.CompletedProcess(cmd, self.delete_rc, "", "hata")

        if "/Create" in cmd:
            if self.create_rc == 0:
                self.existing.add(name)
                self.commands[name] = self._exe_of(cmd[cmd.index("/TR") + 1])
            return subprocess.CompletedProcess(cmd, self.create_rc, "", "hata")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    def created(self):
        return [c for c in self.calls if "/Create" in c]

    def deleted(self):
        return [c for c in self.calls if "/Delete" in c]

    def deleted_names(self):
        return {c[c.index("/TN") + 1] for c in self.deleted()}


# ═══════════════════════════════════════════════════════════════════════════
#  Principal siniflandirmasi
# ═══════════════════════════════════════════════════════════════════════════
class TestPrincipalClassification(unittest.TestCase):

    def test_risky_principals_are_untrusted_writers(self):
        for sid, label in (
            ("S-1-1-0", "Everyone"),
            ("S-1-5-11", "Authenticated Users"),
            ("S-1-5-32-545", "BUILTIN\\Users"),
            ("S-1-5-32-546", "Guests"),
            ("S-1-5-32-547", "Power Users"),
            ("S-1-5-4", "INTERACTIVE"),
            ("S-1-5-21-2068301135-2316194410-456321829-1001", "normal kullanici"),
            ("S-1-5-21-1-2-3-1005", "baska normal hesap"),
        ):
            self.assertTrue(failsafe._is_untrusted_writer(sid),
                            f"{label} ({sid}) guvenilir yazar sayildi")

    def test_privileged_principals_may_hold_write(self):
        for sid, label in (
            ("S-1-5-18", "SYSTEM"),
            ("S-1-5-32-544", "Administrators"),
            ("S-1-3-0", "CREATOR OWNER"),
            ("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
             "TrustedInstaller"),
        ):
            self.assertFalse(failsafe._is_untrusted_writer(sid),
                             f"{label} gereksiz yere reddedildi")

    def test_dangerous_rights_cover_write_delete_and_acl_change(self):
        for right, label in (
            (failsafe.FILE_WRITE_DATA, "yazma"),
            (failsafe.FILE_APPEND_DATA, "ekleme"),
            (failsafe.FILE_DELETE_CHILD, "alt oge silme"),
            (failsafe.DELETE, "silme"),
            (failsafe.WRITE_DAC, "ACL degistirme"),
            (failsafe.WRITE_OWNER, "sahiplik alma"),
            (failsafe.GENERIC_WRITE, "generic write"),
            (failsafe.GENERIC_ALL, "generic all"),
        ):
            self.assertTrue(failsafe._DANGEROUS_RIGHTS & right,
                            f"{label} tehlikeli haklar kumesinde yok")

    def test_read_execute_is_not_dangerous(self):
        FILE_GENERIC_READ_EXECUTE = 0x1200A9
        self.assertEqual(failsafe._DANGEROUS_RIGHTS & FILE_GENERIC_READ_EXECUTE, 0)


# ═══════════════════════════════════════════════════════════════════════════
#  Gercek (salt-okunur) ACL / sahiplik / yol testleri — yonetici gerekmez
# ═══════════════════════════════════════════════════════════════════════════
class TestRealAclInspection(unittest.TestCase):

    def setUp(self):
        self.program_files = failsafe._known_folder(failsafe._FOLDERID_PROGRAM_FILES)
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_known_folder_returns_real_program_files(self):
        self.assertTrue(self.program_files)
        self.assertTrue(os.path.isdir(self.program_files))

    def test_program_files_is_acl_protected(self):
        """Gercek C:\\Program Files: yalnizca ayricalikli principal'lar yazabilir."""
        self.assertIs(failsafe.dacl_writers_are_trusted(self.program_files), True)
        self.assertIs(failsafe.owner_is_trusted(self.program_files), True)

    def test_user_temp_dir_is_not_acl_protected(self):
        """Kullanici gecici dizini: kullanici yazabilir -> reddedilmeli.

        NOT: sahiplik ORTAMA BAGLIDIR — dizin YUKSELTILMIS bir surec tarafindan
        olusturulursa sahibi Administrators olur. Guvenlik kararini veren asil
        kontrol DACL'dir; onu kesin olarak dogruluyoruz."""
        self.assertIs(failsafe.dacl_writers_are_trusted(self._tmp.name), False)
        self.assertFalse(failsafe._location_is_acl_protected(self._tmp.name))

    def test_user_writable_location_fails_protection_check(self):
        probe = os.path.join(self._tmp.name, "fake.exe")
        with open(probe, "wb") as f:
            f.write(b"MZ")
        self.assertFalse(failsafe._location_is_acl_protected(probe))

    def test_missing_path_is_fail_closed(self):
        ghost = os.path.join(self._tmp.name, "yok", "olmayan.exe")
        self.assertIsNone(failsafe.dacl_writers_are_trusted(ghost))
        self.assertIsNone(failsafe.owner_is_trusted(ghost))
        self.assertFalse(failsafe._location_is_acl_protected(ghost))

    def test_canonical_path_resolves_junction_to_real_target(self):
        target = os.path.join(self._tmp.name, "gercek")
        os.makedirs(target)
        probe = os.path.join(target, "x.bin")
        with open(probe, "wb") as f:
            f.write(b"x")
        link = os.path.join(self._tmp.name, "baglanti")
        if not _make_junction(link, target):
            self.skipTest("junction olusturulamadi")

        via_link = failsafe.canonical_path(os.path.join(link, "x.bin"))
        direct = failsafe.canonical_path(probe)
        self.assertIsNotNone(via_link)
        self.assertEqual(via_link, direct,
                         "junction uzerinden gelen yol gercek hedefe cozulmedi")

    def test_reparse_point_detected_in_chain(self):
        target = os.path.join(self._tmp.name, "hedef")
        os.makedirs(target)
        probe = os.path.join(target, "x.bin")
        with open(probe, "wb") as f:
            f.write(b"x")
        link = os.path.join(self._tmp.name, "link")
        if not _make_junction(link, target):
            self.skipTest("junction olusturulamadi")

        self.assertIs(failsafe._chain_has_reparse_point(os.path.join(link, "x.bin")), True)
        self.assertIs(failsafe._chain_has_reparse_point(probe), False)

    def test_unknown_reparse_state_is_fail_closed(self):
        ghost = os.path.join(self._tmp.name, "olmayan.exe")
        self.assertIsNone(failsafe._is_reparse_point(ghost))
        self.assertIsNone(failsafe._chain_has_reparse_point(ghost))

    def test_canonical_path_rejects_unc(self):
        self.assertIsNone(failsafe.canonical_path(r"\\127.0.0.1\C$\Windows\explorer.exe"))

    def test_program_files_roots_ignore_poisoned_environment(self):
        """ProgramFiles* ortam degiskenleri sahtelense de kokler DEGISMEZ."""
        clean = failsafe._program_files_roots()
        self.assertTrue(clean)
        poisoned = {
            "ProgramFiles": self._tmp.name,
            "ProgramFiles(x86)": self._tmp.name,
            "ProgramW6432": self._tmp.name,
        }
        with mock.patch.dict(os.environ, poisoned):
            self.assertEqual(failsafe._program_files_roots(), clean)
        self.assertTrue(all(os.path.normcase(self._tmp.name) not in r for r in clean))


# ═══════════════════════════════════════════════════════════════════════════
#  verified_failsafe_target() — her kontrol tek tek
# ═══════════════════════════════════════════════════════════════════════════
class TestVerifiedTarget(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_exe = os.path.join(self._tmp.name, "DPort.exe")
        with open(self.fake_exe, "wb") as f:
            f.write(b"MZ")

    def tearDown(self):
        self._tmp.cleanup()

    def _all_checks_pass(self, exe=r"c:\program files\dport\dport.exe"):
        """Tum kontrolleri gecen bir dunya kurar; testler tek tek bozar."""
        return [
            mock.patch.object(failsafe.sys, "frozen", True, create=True),
            mock.patch.object(failsafe, "canonical_path", lambda p: exe),
            mock.patch.object(failsafe.os.path, "isfile", lambda p: True),
            mock.patch.object(failsafe, "_chain_has_reparse_point", lambda p: False),
            mock.patch.object(failsafe, "_program_files_roots",
                              lambda: [r"c:\program files"]),
            mock.patch.object(failsafe, "_location_is_acl_protected", lambda p: True),
        ]

    def _run(self, patches):
        for p in patches:
            p.start()
        try:
            return failsafe.verified_failsafe_target()
        finally:
            for p in reversed(patches):
                p.stop()

    def test_happy_path_returns_canonical_exe(self):
        self.assertEqual(self._run(self._all_checks_pass()),
                         r"c:\program files\dport\dport.exe")

    def test_not_frozen_never_targets_the_running_script(self):
        """Kaynak modunda hedef ASLA calisan (kullanici-yazilabilir) betik
        olamaz. Yalnizca BAGIMSIZ kesfedilmis, dogrulanmis KURULU DPort.exe
        kabul edilir; o da yoksa hedef yoktur."""
        patches = self._all_checks_pass()
        patches[0] = mock.patch.object(failsafe.sys, "frozen", False, create=True)
        patches.append(mock.patch.object(failsafe.sys, "executable",
                                         r"c:\repo\dport\app\main.py"))
        # Kurulu exe VAR: yalnizca o kullanilir, betik degil.
        self.assertEqual(self._run(patches), r"c:\program files\dport\dport.exe")

    def test_not_frozen_without_installed_exe_has_no_target(self):
        patches = self._all_checks_pass()
        patches[0] = mock.patch.object(failsafe.sys, "frozen", False, create=True)
        patches[5] = mock.patch.object(failsafe, "_location_is_acl_protected",
                                       lambda p: False)
        patches.append(mock.patch.object(failsafe, "_task_command",
                                         lambda name=None: None))
        self.assertIsNone(self._run(patches))

    def test_reparse_point_in_chain_is_rejected(self):
        patches = self._all_checks_pass()
        patches[3] = mock.patch.object(failsafe, "_chain_has_reparse_point",
                                       lambda p: True)
        self.assertIsNone(self._run(patches))

    def test_unknown_reparse_state_is_rejected(self):
        patches = self._all_checks_pass()
        patches[3] = mock.patch.object(failsafe, "_chain_has_reparse_point",
                                       lambda p: None)
        self.assertIsNone(self._run(patches))

    def test_path_outside_program_files_is_rejected(self):
        patches = self._all_checks_pass(exe=r"c:\users\kurban\appdata\local\dport.exe")
        self.assertIsNone(self._run(patches))

    def test_no_program_files_root_is_rejected(self):
        patches = self._all_checks_pass()
        patches[4] = mock.patch.object(failsafe, "_program_files_roots", lambda: [])
        self.assertIsNone(self._run(patches))

    def test_loose_acl_is_rejected_even_inside_program_files(self):
        patches = self._all_checks_pass()
        patches[5] = mock.patch.object(failsafe, "_location_is_acl_protected",
                                       lambda p: False)
        self.assertIsNone(self._run(patches))

    def test_canonicalisation_failure_is_rejected(self):
        patches = self._all_checks_pass()
        patches[1] = mock.patch.object(failsafe, "canonical_path", lambda p: None)
        self.assertIsNone(self._run(patches))

    def test_prefix_confusion_is_rejected(self):
        """'c:\\program filesX\\...' , 'c:\\program files' kokunu TASIMAZ."""
        patches = self._all_checks_pass(exe=r"c:\program files evil\dport\dport.exe")
        self.assertIsNone(self._run(patches))

    def test_environment_poisoning_does_not_grant_protection(self):
        """Sahte ProgramFiles + yazilabilir klasordeki gercek exe -> REDDEDILIR."""
        with mock.patch.object(failsafe.sys, "frozen", True, create=True), \
             mock.patch.object(failsafe.sys, "executable", self.fake_exe), \
             mock.patch.dict(os.environ, {"ProgramFiles": self._tmp.name,
                                          "ProgramW6432": self._tmp.name,
                                          "ProgramFiles(x86)": self._tmp.name}):
            self.assertIsNone(failsafe.verified_failsafe_target())
            self.assertFalse(failsafe._exe_in_protected_location())

    def test_source_mode_never_uses_the_running_script_on_this_machine(self):
        """Kaynak modunda yalnizca bagimsiz, dogrulanmis kurulum hedef olabilir.

        Bu makinede kurulu bir DPort.exe bulunabilir; o durum kaynak modunu
        reddetmek degil, `sys.executable`/calisan betigi HIGHEST gorev hedefi
        yapmamaktir. Test, kurulu uygulamanin varligina gore yanlis negatif
        uretmeden bu siniri dogrular.
        """
        target = failsafe.verified_failsafe_target()
        self.assertEqual(failsafe._exe_in_protected_location(), target is not None)
        if target is not None:
            self.assertEqual(os.path.basename(target).casefold(), "dport.exe")
            self.assertNotEqual(
                os.path.normcase(target), os.path.normcase(sys.executable))
            self.assertTrue(any(
                os.path.normcase(target).startswith(root + os.sep)
                for root in failsafe._program_files_roots()))


# ═══════════════════════════════════════════════════════════════════════════
#  Gorev yasam dongusu (schtasks CALISTIRILMAZ)
# ═══════════════════════════════════════════════════════════════════════════
class TestTaskLifecycle(unittest.TestCase):

    def test_unsafe_location_creates_no_task_and_removes_stale_one(self):
        all_names = [failsafe.TASK_NAME] + list(failsafe._LEGACY_TASKS)
        sim = _SchtasksSim(existing=all_names)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())

        self.assertEqual(sim.created(), [], "guvensiz konumda gorev OLUSTURULDU")
        self.assertIn(failsafe.TASK_NAME, sim.deleted_names(),
                      "eski/guvensiz gorev SILINMEDI")
        for legacy in failsafe._LEGACY_TASKS:
            self.assertIn(legacy, sim.deleted_names())
        self.assertEqual(sim.existing, set(), "gorevler gercekte kaldirilmadi")

    def test_safe_location_creates_task_with_verified_path_only(self):
        verified = r"c:\program files\dport\dport.exe"
        sim = _SchtasksSim()
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=verified), \
             mock.patch.object(failsafe.sys, "executable",
                               r"C:\Users\kurban\AppData\Local\evil.exe"), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertTrue(failsafe.install_logon_failsafe())

        created = sim.created()
        self.assertEqual(len(created), 1)
        cmd = created[0]
        target = cmd[cmd.index("/TR") + 1]
        self.assertEqual(target, f'"{verified}" --cleanup-hosts')
        # Ham sys.executable ASLA goreve yazilmamali
        self.assertNotIn("evil.exe", target.lower())
        self.assertEqual(cmd[cmd.index("/RL") + 1], "HIGHEST")
        self.assertEqual(cmd[cmd.index("/SC") + 1], "ONLOGON")
        self.assertEqual(cmd[cmd.index("/TN") + 1], failsafe.TASK_NAME)
        # Kayitli hedef geri okunup dogrulanmis olmali
        self.assertEqual(sim.commands[failsafe.TASK_NAME], verified)

    def test_remove_also_clears_legacy_task_names(self):
        all_names = [failsafe.TASK_NAME] + list(failsafe._LEGACY_TASKS)
        sim = _SchtasksSim(existing=all_names)
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertTrue(failsafe.remove_logon_failsafe())
        for name in all_names:
            self.assertIn(name, sim.deleted_names())
        self.assertEqual(sim.existing, set())

    def test_schtasks_failure_is_reported_as_false(self):
        def _fail(cmd, *a, **kw):
            if "/Create" in cmd:
                return subprocess.CompletedProcess(list(cmd), 1, "", "erisim reddedildi")
            return subprocess.CompletedProcess(list(cmd), 0, "", "")

        with mock.patch.object(failsafe, "verified_failsafe_target",
                               return_value=r"c:\program files\dport\dport.exe"), \
             mock.patch.object(failsafe.subprocess, "run", _fail):
            self.assertFalse(failsafe.install_logon_failsafe())

    def test_exception_during_create_is_fail_closed(self):
        def _boom(cmd, *a, **kw):
            if "/Create" in cmd:
                raise OSError("schtasks yok")
            return subprocess.CompletedProcess(list(cmd), 0, "", "")

        with mock.patch.object(failsafe, "verified_failsafe_target",
                               return_value=r"c:\program files\dport\dport.exe"), \
             mock.patch.object(failsafe.subprocess, "run", _boom):
            self.assertFalse(failsafe.install_logon_failsafe())


# ═══════════════════════════════════════════════════════════════════════════
#  _delete_task — silme GERCEKTEN dogrulanmali
# ═══════════════════════════════════════════════════════════════════════════
class TestDeleteTaskVerification(unittest.TestCase):

    def setUp(self):
        failsafe._set_error("")

    def test_absent_task_needs_no_delete(self):
        sim = _SchtasksSim()
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertTrue(failsafe._delete_task("X"))
        self.assertEqual(sim.deleted(), [], "olmayan gorev icin /Delete cagrildi")

    def test_successful_delete_is_verified(self):
        sim = _SchtasksSim(existing=["X"])
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertTrue(failsafe._delete_task("X"))
        self.assertTrue(sim.deleted())
        self.assertNotIn("X", sim.existing)
        self.assertEqual(failsafe.last_failsafe_error(), "")

    def test_nonzero_return_code_is_failure(self):
        """Komut CALISTI ama returncode != 0 -> basarili SAYILMAZ."""
        sim = _SchtasksSim(existing=["X"], delete_rc=1, delete_works=True)
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe._delete_task("X"))
        self.assertIn("rc=1", failsafe.last_failsafe_error())

    def test_delete_reports_success_but_task_still_exists(self):
        """/Delete 0 dondu FAKAT gorev hala kayitli -> GUVENLIK hatasi."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], delete_rc=0,
                           delete_works=False)
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe._delete_task(failsafe.TASK_NAME))
        err = failsafe.last_failsafe_error()
        self.assertIn("GUVENLIK", err)
        self.assertIn("SILINEMEDI", err)

    def test_unreadable_task_state_is_fail_closed(self):
        sim = _SchtasksSim(existing=["X"], query_raises=True)
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe._delete_task("X"))
        self.assertTrue(failsafe.last_failsafe_error())

    def test_remove_reports_failure_if_any_name_survives(self):
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], delete_works=False)
        with mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.remove_logon_failsafe())
        self.assertTrue(failsafe.last_failsafe_error())


class TestInstallSurfacesFailures(unittest.TestCase):

    SAFE = r"c:\program files\dport\dport.exe"

    def setUp(self):
        failsafe._set_error("")

    def test_unsafe_target_failing_removal_is_not_swallowed(self):
        """Guvensiz hedefte eski gorev SILINEMEZSE sessizce yutulmaz."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], delete_works=False)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertTrue(failsafe.last_failsafe_error(),
                        "kaldirma hatasi gorunur degil")
        self.assertEqual(sim.created(), [])

    def test_unsafe_target_successful_removal_reports_reason_not_failure(self):
        """Kurulum yapilamadiginda GEREKCE gorunur olmali, ama bu bir KALDIRMA
        hatasi gibi raporlanmamalidir (gorev gercekten silindi)."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME],
                           registered=r"C:\Users\kurban\AppData\Local\DPort.exe")
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        err = failsafe.last_failsafe_error()
        self.assertTrue(err, "kurulmama gerekcesi hic bildirilmedi")
        self.assertNotIn("kaldirilamadi", err)
        self.assertNotIn(failsafe.TASK_NAME, sim.existing)

    def test_unsafe_current_exe_removes_task_pointing_at_writable_path(self):
        """Kayitli hedef YAZILABILIR bir yolsa gorev KALDIRILIR."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME],
                           registered=r"C:\Users\kurban\AppData\Local\DPort.exe")
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn(failsafe.TASK_NAME, sim.deleted_names())

    def test_unsafe_current_exe_keeps_task_pointing_at_verified_install(self):
        """Kaynaktan calismak, kurulu surumun MESRU gorevini YOK ETMEZ."""
        safe = r"c:\program files\dport\dport.exe"
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], registered=safe)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               side_effect=lambda p: safe if p.lower() == safe else None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertEqual(sim.deleted(), [], "mesru gorev gereksiz yere silindi")
        self.assertIn(failsafe.TASK_NAME, sim.existing)
        self.assertNotIn("kaldirilamadi", failsafe.last_failsafe_error())

    def test_create_failure_is_reported(self):
        sim = _SchtasksSim(create_rc=1)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn("rc=1", failsafe.last_failsafe_error())

    def test_successful_create_is_read_back_and_verified(self):
        sim = _SchtasksSim()
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertTrue(failsafe.install_logon_failsafe())
        self.assertEqual(failsafe.last_failsafe_error(), "")
        self.assertTrue(any("/XML" in c for c in sim.calls), "geri okuma yapilmadi")

    def test_registered_target_mismatch_removes_task(self):
        """Kayitli hedef beklenenden farkliysa gorev SILINIR ve False donulur."""
        sim = _SchtasksSim(registered=r"C:\Users\kurban\AppData\Local\evil.exe")
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn("GUVENLIK", failsafe.last_failsafe_error())
        self.assertIn(failsafe.TASK_NAME, sim.deleted_names(),
                      "uyusmayan gorev silinmedi")

    def test_unreadable_registered_target_is_not_claimed_successful(self):
        sim = _SchtasksSim(omit_command=True)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn("dogrulanmadi", failsafe.last_failsafe_error())

    def test_legacy_task_that_cannot_be_removed_blocks_creation(self):
        legacy = failsafe._LEGACY_TASKS[0]
        sim = _SchtasksSim(existing=[legacy], sticky=[legacy])
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertEqual(sim.created(), [], "eski gorev dururken yeni gorev kuruldu")
        self.assertIn("SILINEMEDI", failsafe.last_failsafe_error())


# NOT: Eski "TestStartupSynchronisation" sinifi KALDIRILDI. Acilista
# kosulsuz gorev kurulmasini bekliyordu; yeni yasam dongusunde acilis
# gorev KURMAZ (yalnizca hosts temizligi dogrulanirsa KALDIRIR).
# Yerine: tests/test_failsafe_lifecycle.py :: TestStartupDoesNotCreateTask


# ═══════════════════════════════════════════════════════════════════════════
#  Olusturma basarisiz olsa bile GUVENSIZ gorev ayakta kalmamali
# ═══════════════════════════════════════════════════════════════════════════
class TestNoUnsafeTaskSurvivesFailure(unittest.TestCase):

    SAFE = r"c:\program files\dport\dport.exe"
    UNSAFE = r"C:\Users\kurban\AppData\Local\DPort.exe"

    def setUp(self):
        failsafe._set_error("")

    def test_create_failure_removes_pre_existing_unsafe_task(self):
        """/Create basarisiz -> onceki surumden kalan GUVENSIZ tanim SILINIR."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], create_rc=1,
                           registered=self.UNSAFE)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe, "path_is_verified_install", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())

        self.assertIn(failsafe.TASK_NAME, sim.deleted_names())
        self.assertNotIn(failsafe.TASK_NAME, sim.existing,
                         "olusturma basarisizken guvensiz gorev AYAKTA KALDI")
        self.assertIn("rc=1", failsafe.last_failsafe_error())

    def test_create_failure_keeps_pre_existing_verified_task(self):
        """/Create basarisiz ama kayitli hedef DOGRULANABILIR -> korunur."""
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], create_rc=1,
                           registered=self.SAFE)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               side_effect=lambda p: self.SAFE if p.lower() == self.SAFE else None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())

        self.assertIn(failsafe.TASK_NAME, sim.existing)
        self.assertEqual(sim.deleted_names() & {failsafe.TASK_NAME}, set())

    def test_unreadable_target_after_create_removes_task(self):
        """Hedef geri okunamiyorsa guvenli sayilmaz -> gorev kaldirilir."""
        sim = _SchtasksSim(omit_command=True)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertNotIn(failsafe.TASK_NAME, sim.existing)

    def test_guard_reports_when_unsafe_task_cannot_be_removed(self):
        sim = _SchtasksSim(existing=[failsafe.TASK_NAME], create_rc=1,
                           registered=self.UNSAFE, delete_works=False)
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=self.SAFE), \
             mock.patch.object(failsafe, "path_is_verified_install", return_value=None), \
             mock.patch.object(failsafe.subprocess, "run", sim):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn("GUVENLIK", failsafe.last_failsafe_error())


# NOT: "--sync-failsafe" BAKIM MODU testleri KALDIRILDI. Bayrak ve onu
# calistiran installer adimi tamamen silindi (gorev artik kurulum
# tarafindan olusturulmuyor). Ayni koruma — bakim modunun GUI/DNS/relay
# yuklememesi — artik gecerli olan mod icin dogrulaniyor:
# tests/test_failsafe_lifecycle.py :: TestCleanupHostsMode


if __name__ == "__main__":
    unittest.main(verbosity=2)
