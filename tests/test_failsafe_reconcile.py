"""
tests/test_failsafe_reconcile.py

Codex incelemesinden cikan regresyonlarin kalkani.

Kapsanan bulgular:
  1) hosts temizligi BASARISIZ iken bile GUVENSIZ/OKUNAMAYAN gorev kaldirilmali;
     yalnizca BAGIMSIZ olarak dogrulanmis hedefi olan gorev korunmali.
  2) Installer hosts blogunu temizleyemediginde gorev(ler) SILINMEMELI.
  3) "Normale Don" yalnizca hosts + gorev + DNS ucu birden basariliysa tam
     basari gostermeli.
  4) Watchdog yalnizca gercekten temizlediginde basari loglamali.
  5) Kaynak modunda gorev hedefi ASLA .py betigi olamaz; yalnizca BAGIMSIZ
     kesfedilmis ve dogrulanmis kurulu DPort.exe kullanilabilir.
  6) Gorev kurulduktan sonraki her istisna yolunda role durmali ve guvenli
     rollback denenmelidir.
  7) --cleanup-hosts cikis kodlari belgelenen sozlesmeyle BIREBIR ayni olmali.

GUVENLIK: Bu testler GERCEK schtasks, hosts, DNS, registry veya Discord
surecine DOKUNMAZ. Sistem cagrilari mock'lanir; installer testleri yalnizca
GECICI klasordeki fixture dosyalari uzerinde calisir ve uretilen deneme
kurulumu InitializeSetup icinde IPTAL edilir (hicbir sey kurulmaz).
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import failsafe          # noqa: E402
from core.lang import L            # noqa: E402
from gui import app as gui_app     # noqa: E402

_ISS = os.path.join(_ROOT, "packaging", "DPort.iss")


# ═══════════════════════════════════════════════════════════════════════════
#  Ortak yardimcilar
# ═══════════════════════════════════════════════════════════════════════════
class _TaskLayer:
    """schtasks katmanini tamamen degistiren sahte kayit defteri."""

    def __init__(self, tasks=None, delete_ok=True):
        # {gorev adi: kayitli <Command> degeri veya None (okunamiyor)}
        self.tasks = dict(tasks or {})
        self.delete_ok = delete_ok
        self.deleted = []

    def exists(self, name):
        return name in self.tasks

    def command(self, name):
        return self.tasks.get(name)

    def delete(self, name):
        self.deleted.append(name)
        if name not in self.tasks:
            return True
        if not self.delete_ok:
            failsafe._set_error(f"GUVENLIK: '{name}' gorevi SILINEMEDI")
            return False
        del self.tasks[name]
        return True

    def patches(self):
        return [
            mock.patch.object(failsafe, "_task_exists", self.exists),
            mock.patch.object(failsafe, "_task_command", self.command),
            mock.patch.object(failsafe, "_delete_task", self.delete),
        ]


_SAFE_TARGET = r"C:\Program Files\DPort\DPort.exe"
_UNSAFE_TARGET = r"C:\Users\kurban\AppData\Local\DPort\DPort.exe"


def _verifier(safe_paths):
    safe = {os.path.normcase(p) for p in safe_paths}

    def _check(path):
        if not path:
            return None
        key = os.path.normcase(path)
        return key if key in safe else None
    return _check


class _AppStub:
    """DPortApp metotlarini gercek sinif uzerinden baglamak icin asgari self."""

    def __init__(self):
        self._alive = True
        self._busy = False
        self.logged = []
        self.status = []
        self.applied = []
        self.after_calls = []
        self.log_mgr = types.SimpleNamespace(
            write=self.logged.append,
            console=lambda m, level="INFO": self.logged.append(f"[{level}] {m}"))
        self.unblocker_stopped = 0
        self._unblocker = types.SimpleNamespace(
            start=lambda: True, stop=self._stop, is_active=lambda: False)
        for helper in ("_install_failsafe_before_hosts",
                       "_reconcile_failsafe_task",
                       "_rollback_after_enable_failure"):
            setattr(self, helper, self.bind(helper))

    def _stop(self):
        self.unblocker_stopped += 1

    def _st(self, text, color=None):
        self.status.append(text)

    def _flushdns(self):
        pass

    def _restore_dns(self):
        return True

    def _current_dns_text(self):
        return "1.1.1.1"

    def _refresh_status_async(self):
        pass

    def _apply_restored_status(self, dns_txt, can_retry=False):
        self.applied.append((dns_txt, can_retry))

    def after(self, _delay, func=None, *args):
        if func is not None:
            self.after_calls.append(func)
            func(*args)

    @staticmethod
    def _is_admin():
        return True

    def bind(self, name):
        return getattr(gui_app.DPortApp, name).__get__(self, gui_app.DPortApp)


# ═══════════════════════════════════════════════════════════════════════════
#  1) Merkezi gorev uzlasmasi (core.failsafe.reconcile_failsafe_task)
# ═══════════════════════════════════════════════════════════════════════════
class TestReconcileClassification(unittest.TestCase):
    """hosts temizligi BASARISIZ olsa bile gorev hedefi SINIFLANDIRILMALI."""

    def _run(self, layer, hosts_cleared, safe_paths=()):
        patches = layer.patches() + [
            mock.patch.object(failsafe, "path_is_verified_install",
                              _verifier(safe_paths))]
        for p in patches:
            p.start()
        try:
            return failsafe.reconcile_failsafe_task(hosts_cleared)
        finally:
            mock.patch.stopall()

    def test_no_task_is_already_safe(self):
        layer = _TaskLayer({})
        self.assertTrue(self._run(layer, hosts_cleared=False))
        self.assertNotIn(failsafe.TASK_NAME, layer.tasks)

    def test_hosts_failure_preserves_independently_verified_task(self):
        layer = _TaskLayer({failsafe.TASK_NAME: f'"{_SAFE_TARGET}"'})
        ok = self._run(layer, hosts_cleared=False, safe_paths=[_SAFE_TARGET])
        self.assertTrue(ok)
        self.assertIn(failsafe.TASK_NAME, layer.tasks,
                      "dogrulanmis kurtarma gorevi hosts hatasinda silinmemeli")

    def test_hosts_failure_removes_user_writable_target(self):
        layer = _TaskLayer({failsafe.TASK_NAME: f'"{_UNSAFE_TARGET}"'})
        ok = self._run(layer, hosts_cleared=False, safe_paths=[_SAFE_TARGET])
        self.assertTrue(ok)
        self.assertNotIn(failsafe.TASK_NAME, layer.tasks,
                         "kullanici-yazilabilir hedefli HIGHEST gorev korundu")

    def test_hosts_failure_removes_unreadable_target(self):
        layer = _TaskLayer({failsafe.TASK_NAME: None})
        ok = self._run(layer, hosts_cleared=False, safe_paths=[_SAFE_TARGET])
        self.assertTrue(ok)
        self.assertNotIn(failsafe.TASK_NAME, layer.tasks,
                         "hedefi okunamayan gorev korundu")

    def test_unsafe_task_removal_failure_is_visible(self):
        layer = _TaskLayer({failsafe.TASK_NAME: f'"{_UNSAFE_TARGET}"'},
                           delete_ok=False)
        failsafe._set_error("")
        ok = self._run(layer, hosts_cleared=False, safe_paths=[_SAFE_TARGET])
        self.assertFalse(ok, "guvensiz gorev kaldirilamadi ama basari bildirildi")
        self.assertIn("SILINEMEDI", failsafe.last_failsafe_error())

    def test_legacy_task_is_removed_even_when_hosts_not_cleared(self):
        legacy = failsafe._LEGACY_TASKS[0]
        layer = _TaskLayer({failsafe.TASK_NAME: f'"{_SAFE_TARGET}"',
                            legacy: f'"{_SAFE_TARGET}"'})
        ok = self._run(layer, hosts_cleared=False, safe_paths=[_SAFE_TARGET])
        self.assertTrue(ok)
        self.assertNotIn(legacy, layer.tasks,
                         "eski ad her durumda kaldirilmali")
        self.assertIn(failsafe.TASK_NAME, layer.tasks)

    def test_successful_cleanup_removes_every_task(self):
        legacy = failsafe._LEGACY_TASKS[0]
        layer = _TaskLayer({failsafe.TASK_NAME: f'"{_SAFE_TARGET}"',
                            legacy: f'"{_SAFE_TARGET}"'})
        ok = self._run(layer, hosts_cleared=True, safe_paths=[_SAFE_TARGET])
        self.assertTrue(ok)
        self.assertEqual(layer.tasks, {})


class TestGuiUsesCentralReconciler(unittest.TestCase):
    """Acilis / kapanis / watchdog ayni siniflandirmayi kullanmali."""

    def test_helper_delegates_to_core_and_reports_result(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as rec:
            self.assertTrue(stub._reconcile_failsafe_task(False, "acilis"))
        rec.assert_called_once_with(False)

    def test_helper_surfaces_failure(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=False), \
             mock.patch.object(gui_app, "last_failsafe_error",
                               return_value="gorev silinemedi"):
            self.assertFalse(stub._reconcile_failsafe_task(False, "acilis"))
        self.assertTrue(any("gorev silinemedi" in m for m in stub.logged),
                        f"uzlasma hatasi loglanmadi: {stub.logged}")

    def test_helper_exception_is_not_reported_as_success(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "reconcile_failsafe_task",
                               side_effect=OSError("schtasks patladi")):
            self.assertFalse(stub._reconcile_failsafe_task(True, "kapanis"))


# ═══════════════════════════════════════════════════════════════════════════
#  3) "Normale Don" yanlis basari gostermemeli
# ═══════════════════════════════════════════════════════════════════════════
class TestRestoreNormalTruthfulness(unittest.TestCase):

    def _disable(self, stub, hosts_ok, task_ok):
        with mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=hosts_ok), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=task_ok), \
             mock.patch.object(gui_app, "last_failsafe_error", return_value=""):
            return stub.bind("_disable_discord_unblock")()

    def test_disable_returns_true_only_on_full_success(self):
        stub = _AppStub()
        self.assertTrue(self._disable(stub, True, True))

    def test_disable_reports_hosts_failure(self):
        stub = _AppStub()
        self.assertFalse(self._disable(stub, False, True),
                         "hosts temizlenemedigi halde basari bildirildi")
        self.assertEqual(stub.unblocker_stopped, 1)

    def test_disable_reports_task_reconcile_failure(self):
        stub = _AppStub()
        self.assertFalse(self._disable(stub, True, False),
                         "gorev uzlasmasi basarisiz ama basari bildirildi")

    def test_disable_reports_exception(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "remove_hosts_redirect",
                               side_effect=OSError("hosts kilitli")), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True):
            self.assertFalse(stub.bind("_disable_discord_unblock")())

    def _restore(self, stub, unblock_ok, dns_ok):
        stub._disable_discord_unblock = lambda: unblock_ok
        stub._restore_dns = lambda: dns_ok
        stub.bind("_restore_normal_w")()

    def test_hosts_residue_is_not_shown_as_restored(self):
        stub = _AppStub()
        self._restore(stub, unblock_ok=False, dns_ok=True)
        self.assertNotIn(L["st_restored"], stub.status,
                         "hosts kalintisi varken 'Normale donuldu' gosterildi")
        self.assertIn(L["st_restore_partial"], stub.status)
        self.assertEqual(stub.applied[-1][1], True, "tekrar deneme kapatildi")

    def test_task_failure_is_not_shown_as_restored(self):
        stub = _AppStub()
        self._restore(stub, unblock_ok=False, dns_ok=True)
        self.assertNotIn(L["st_restored"], stub.status)

    def test_full_success_still_shows_restored(self):
        stub = _AppStub()
        self._restore(stub, unblock_ok=True, dns_ok=True)
        self.assertIn(L["st_restored"], stub.status)
        self.assertEqual(stub.applied[-1][1], False)


# ═══════════════════════════════════════════════════════════════════════════
#  4) Watchdog yanlis basari loglamamali
# ═══════════════════════════════════════════════════════════════════════════
class TestWatchdogHonesty(unittest.TestCase):

    def _run_once(self, **patches):
        stub = _AppStub()

        def _sleep(_s):
            stub._alive = False

        ctx = [mock.patch.object(gui_app.time, "sleep", _sleep),
               mock.patch.object(gui_app, "is_hosts_redirect_active",
                                 return_value=True)]
        for name, kwargs in patches.items():
            ctx.append(mock.patch.object(gui_app, name, **kwargs))
        for p in ctx:
            p.start()
        try:
            stub.bind("_watchdog_loop")()
        finally:
            mock.patch.stopall()
        return stub

    def test_success_log_only_when_hosts_really_cleared(self):
        stub = self._run_once(
            remove_hosts_redirect={"return_value": False},
            reconcile_failsafe_task={"return_value": True})
        joined = " | ".join(stub.logged)
        self.assertNotIn("yonlendirmesi temizlendi", joined,
                         f"temizlenmedigi halde basari loglandi: {joined}")
        self.assertIn("TEMIZLENEMEDI", joined.upper(),
                      f"basarisizlik gorunur degil: {joined}")

    def test_success_is_logged_when_cleared(self):
        stub = self._run_once(
            remove_hosts_redirect={"return_value": True},
            reconcile_failsafe_task={"return_value": True})
        self.assertIn("yonlendirmesi temizlendi", " | ".join(stub.logged))

    def test_exception_is_logged_not_swallowed(self):
        stub = self._run_once(
            remove_hosts_redirect={"side_effect": OSError("hosts kilitli")},
            reconcile_failsafe_task={"return_value": True})
        joined = " | ".join(stub.logged)
        self.assertIn("hosts kilitli", joined,
                      f"watchdog istisnasi tamamen yutuldu: {joined}")


# ═══════════════════════════════════════════════════════════════════════════
#  5) Kaynak modu: yalnizca BAGIMSIZ dogrulanmis kurulu exe hedef olabilir
# ═══════════════════════════════════════════════════════════════════════════
class TestSourceModeRecoveryTarget(unittest.TestCase):
    """Kaynaktan calisirken gorev hedefi ASLA .py olamaz; ama Program Files'ta
    dogrulanmis bir DPort.exe varsa kurtarma yolu acilabilmelidir."""

    def setUp(self):
        self.assertFalse(getattr(sys, "frozen", False),
                         "test kaynak modunda calismali")

    def test_verified_installed_exe_is_used(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[r"c:\program files"]), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([_SAFE_TARGET])):
            self.assertEqual(failsafe.verified_failsafe_target(),
                             os.path.normcase(_SAFE_TARGET))

    def test_no_installed_exe_means_no_target(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[r"c:\program files"]), \
             mock.patch.object(failsafe, "_task_command", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([])):
            self.assertIsNone(failsafe.verified_failsafe_target())

    def test_user_writable_fake_exe_is_rejected(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[r"c:\program files"]), \
             mock.patch.object(failsafe, "_task_command", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([_UNSAFE_TARGET])):
            self.assertIsNone(failsafe.verified_failsafe_target())

    def test_never_targets_a_python_script(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[r"c:\program files"]), \
             mock.patch.object(failsafe, "_task_command", return_value=None), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               lambda p: os.path.normcase(p)):
            target = failsafe.verified_failsafe_target()
        self.assertTrue(target is None or target.endswith("dport.exe"),
                        f"gorev hedefi calistirilabilir kurulum degil: {target}")

    def test_poisoned_program_files_environment_grants_nothing(self):
        fake_root = tempfile.mkdtemp()
        exe_dir = os.path.join(fake_root, "DPort")
        os.makedirs(exe_dir, exist_ok=True)
        fake_exe = os.path.join(exe_dir, "DPort.exe")
        with open(fake_exe, "wb") as f:
            f.write(b"MZ")
        env = {"ProgramFiles": fake_root, "ProgramFiles(x86)": fake_root,
               "ProgramW6432": fake_root, "PATH": exe_dir}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(failsafe, "_task_command", return_value=None):
            target = failsafe.verified_failsafe_target()
        self.assertNotEqual(
            os.path.normcase(target or ""), os.path.normcase(fake_exe),
            "ortam degiskeniyle uydurulan yol dogrulanmis sayildi")

    def test_existing_verified_task_target_is_reused(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[]), \
             mock.patch.object(failsafe, "_task_command",
                               return_value=f'"{_SAFE_TARGET}"'), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([_SAFE_TARGET])):
            self.assertEqual(failsafe.verified_failsafe_target(),
                             os.path.normcase(_SAFE_TARGET))

    def test_existing_unsafe_task_target_is_not_reused(self):
        with mock.patch.object(failsafe, "_program_files_roots",
                               return_value=[]), \
             mock.patch.object(failsafe, "_task_command",
                               return_value=f'"{_UNSAFE_TARGET}"'), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([_SAFE_TARGET])):
            self.assertIsNone(failsafe.verified_failsafe_target())

    def test_frozen_process_still_verifies_running_exe(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", _UNSAFE_TARGET), \
             mock.patch.object(failsafe, "path_is_verified_install",
                               _verifier([_SAFE_TARGET])):
            self.assertIsNone(failsafe.verified_failsafe_target())

    def test_missing_target_reason_names_source_mode(self):
        with mock.patch.object(failsafe, "verified_failsafe_target",
                               return_value=None), \
             mock.patch.object(failsafe, "_ensure_no_unsafe_task",
                               return_value=True):
            self.assertFalse(failsafe.install_logon_failsafe())
        self.assertIn("kaynak", failsafe.last_failsafe_error().lower(),
                      f"kaynak modu gerekcesi acik degil: "
                      f"{failsafe.last_failsafe_error()!r}")


# ═══════════════════════════════════════════════════════════════════════════
#  6) Baglanti acma akisi: gorev kurulduktan sonraki istisnalarda rollback
# ═══════════════════════════════════════════════════════════════════════════
class TestEnableRollback(unittest.TestCase):

    def test_exception_after_task_install_stops_relay(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               side_effect=OSError("hosts patladi")), \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=True), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as rec:
            ok = stub.bind("_enable_discord_unblock")()
        self.assertFalse(ok)
        self.assertEqual(stub.unblocker_stopped, 1, "role acik kaldi")
        rec.assert_called_once_with(True)

    def test_exception_after_hosts_write_attempts_hosts_cleanup(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               return_value=True), \
             mock.patch.object(gui_app, "last_hosts_retry_info",
                               side_effect=RuntimeError("teshis patladi")), \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=True) as rm, \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True):
            ok = stub.bind("_enable_discord_unblock")()
        self.assertFalse(ok)
        rm.assert_called_once()
        self.assertEqual(stub.unblocker_stopped, 1)

    def test_rollback_hosts_failure_preserves_verified_task(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               side_effect=OSError("hosts patladi")), \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=False), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as rec:
            stub.bind("_enable_discord_unblock")()
        rec.assert_called_once_with(False)

    def test_rollback_failure_keeps_original_error_visible(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               side_effect=OSError("ozgun hata")), \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               side_effect=OSError("rollback hatasi")), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True):
            stub.bind("_enable_discord_unblock")()
        joined = " | ".join(stub.logged)
        self.assertIn("ozgun hata", joined)
        self.assertIn("rollback hatasi", joined)

    def test_relay_start_failure_does_not_touch_task(self):
        stub = _AppStub()
        stub._unblocker.start = lambda: False
        with mock.patch.object(gui_app, "install_logon_failsafe") as install, \
             mock.patch.object(gui_app, "reconcile_failsafe_task") as rec:
            ok = stub.bind("_enable_discord_unblock")()
        self.assertFalse(ok)
        install.assert_not_called()
        rec.assert_not_called()

    def test_hosts_write_failure_rolls_back_and_stops_relay(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               return_value=False), \
             mock.patch.object(gui_app, "last_hosts_error", return_value="kilit"), \
             mock.patch.object(gui_app, "last_hosts_winerror", return_value=32), \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=True) as rm, \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as rec:
            ok = stub.bind("_enable_discord_unblock")()
        self.assertFalse(ok)
        self.assertEqual(stub.unblocker_stopped, 1)
        rm.assert_called_once()
        rec.assert_called_once_with(True)


# ═══════════════════════════════════════════════════════════════════════════
#  7) --cleanup-hosts cikis kodu sozlesmesi (TAM kod dogrulamasi)
# ═══════════════════════════════════════════════════════════════════════════
_HARNESS = r'''
import os, sys, types, runpy

APP, HOSTS, TASK = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, APP)
import core

unblock = types.ModuleType("core.discord_unblock")
if HOSTS == "raise":
    def _remove():
        raise OSError("hosts okunamadi")
else:
    def _remove():
        return HOSTS == "1"
unblock.remove_hosts_redirect = _remove
sys.modules["core.discord_unblock"] = unblock

if TASK == "import-raise":
    class _Boom:
        def find_module(self, *a, **k):
            return None
    sys.modules["core.failsafe"] = None      # import -> ImportError
else:
    fs = types.ModuleType("core.failsafe")
    if TASK == "raise":
        def _rec(hosts_cleared):
            raise OSError("schtasks patladi")
    else:
        def _rec(hosts_cleared):
            return TASK == "1"
    fs.reconcile_failsafe_task = _rec
    fs.remove_logon_failsafe = lambda: TASK == "1"
    fs.last_failsafe_error = lambda: "" if TASK == "1" else "gorev silinemedi"
    sys.modules["core.failsafe"] = fs

sys.argv = ["main.py", "--cleanup-hosts"]
runpy.run_path(os.path.join(APP, "main.py"), run_name="__main__")
'''


class TestCleanupExitCodeContract(unittest.TestCase):
    """app/main.py'de BELGELENEN kodlar birebir dogrulanir (nonzero yetmez)."""

    @classmethod
    def setUpClass(cls):
        cls.harness = os.path.join(tempfile.mkdtemp(), "exitcode_harness.py")
        with open(cls.harness, "w", encoding="utf-8") as f:
            f.write(_HARNESS)

    def _code(self, hosts, task):
        r = subprocess.run([sys.executable, self.harness, _APP, hosts, task],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def test_full_success_is_zero(self):
        code, out = self._code("1", "1")
        self.assertEqual(code, 0, out)

    def test_hosts_failure_is_one(self):
        code, out = self._code("0", "1")
        self.assertEqual(code, 1, out)
        self.assertIn("TASK_NOT_TOUCHED", out)

    def test_hosts_exception_is_one(self):
        code, out = self._code("raise", "1")
        self.assertEqual(code, 1, out)
        self.assertIn("TASK_NOT_TOUCHED", out)

    def test_controlled_task_failure_is_two(self):
        code, out = self._code("1", "0")
        self.assertEqual(code, 2, out)

    def test_unexpected_task_exception_is_three(self):
        code, out = self._code("1", "raise")
        self.assertEqual(code, 3, out)

    def test_unexpected_import_failure_is_three(self):
        code, out = self._code("1", "import-raise")
        self.assertEqual(code, 3, out)

    def test_documented_codes_match_implementation(self):
        with open(os.path.join(_APP, "main.py"), encoding="utf-8") as f:
            text = f.read()
        block = text[text.index("Çıkış kodları:"):text.index('if "--cleanup-hosts"')]
        for code in ("0 =", "1 =", "2 =", "3 ="):
            self.assertIn(code, block, f"{code} belgelenmemis")


# ═══════════════════════════════════════════════════════════════════════════
#  2) Installer: hosts temizligi DOGRULANMADAN gorev SILINMEMELI
# ═══════════════════════════════════════════════════════════════════════════
_CLEANER_BEGIN = "{ ===== DPORT HOSTS CLEANER BEGIN ===== }"
_CLEANER_END = "{ ===== DPORT HOSTS CLEANER END ===== }"

_ISCC = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Programs", "Inno Setup 6", "ISCC.exe")

_HARNESS_ISS = """
[Setup]
AppName=DPort Hosts Cleaner Test
AppVersion=1.0
DefaultDirName={{tmp}}\\dport_cleaner_test
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableStartupPrompt=yes
OutputDir=%(out)s
OutputBaseFilename=cleaner_test

[Code]
%(cleaner)s

function InitializeSetup(): Boolean;
var
  Fixtures, Results: TArrayOfString;
  I: Integer;
begin
  LoadStringsFromFile(ExpandConstant('{param:List}'), Fixtures);
  SetArrayLength(Results, GetArrayLength(Fixtures));
  for I := 0 to GetArrayLength(Fixtures) - 1 do begin
    if CleanHostsBlock(Trim(Fixtures[I])) then
      Results[I] := '1'
    else
      Results[I] := '0';
  end;
  SaveStringsToFile(ExpandConstant('{param:Out}'), Results, False);
  { Kurulumu BASLATMADAN iptal et: hicbir dosya/gorev/kayit degismez. }
  Result := False;
end;
"""

_CLEAN_FIXTURE = """# Copyright (c) 1993-2009 Microsoft Corp.
127.0.0.1 localhost
0.0.0.0 ads.example.com
"""

_BLOCK_FIXTURE = """127.0.0.1 localhost
0.0.0.0 ads.example.com
# >>> DPort Discord unblock >>>
127.0.0.1 discord.com
127.0.0.1 gateway.discord.gg
# <<< DPort Discord unblock <<<
0.0.0.0 tracker.example.net
"""

_MALFORMED_FIXTURE = """127.0.0.1 localhost
# >>> DPort Discord unblock >>>
127.0.0.1 discord.com
0.0.0.0 tracker.example.net
0.0.0.0 ads.example.com
"""

_LEGACY_FIXTURE = """127.0.0.1 localhost
# >>> DNSGuardian Discord unblock >>>
127.0.0.1 cdn.discordapp.com
# <<< DNSGuardian Discord unblock <<<
0.0.0.0 keep.example.com
"""


class _InnoHarness:
    """packaging/DPort.iss icindeki GERCEK temizleyici kodunu ayiklayip
    derler ve gecici fixture'lar uzerinde CALISTIRIR."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.exe = None

    def build(self, cleaner_src):
        script = os.path.join(self.tmp, "cleaner_test.iss")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_HARNESS_ISS % {"out": self.tmp, "cleaner": cleaner_src})
        r = subprocess.run([_ISCC, "/Q", script], capture_output=True,
                           text=True, timeout=300, cwd=self.tmp)
        if r.returncode != 0:
            raise AssertionError(
                f"harness derlenemedi:\n{r.stdout}\n{r.stderr}")
        self.exe = os.path.join(self.tmp, "cleaner_test.exe")
        return self

    def run(self, fixture_paths):
        listing = os.path.join(self.tmp, "list.txt")
        out = os.path.join(self.tmp, "out.txt")
        with open(listing, "w", encoding="utf-8") as f:
            f.write("\n".join(fixture_paths))
        if os.path.exists(out):
            os.remove(out)
        subprocess.run([self.exe, "/VERYSILENT", f"/List={listing}",
                        f"/Out={out}"], capture_output=True, timeout=300)
        with open(out, encoding="utf-8", errors="ignore") as f:
            return [line.strip() for line in f if line.strip()]


class TestInstallerHostsCleanupContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(_ISS):
            raise unittest.SkipTest("packaging/DPort.iss yok (gitignore'lu)")
        with open(_ISS, encoding="utf-8", errors="ignore") as f:
            cls.text = f.read()
        if _CLEANER_BEGIN not in cls.text or _CLEANER_END not in cls.text:
            cls.cleaner = None
            return
        start = cls.text.index(_CLEANER_BEGIN) + len(_CLEANER_BEGIN)
        cls.cleaner = cls.text[start:cls.text.index(_CLEANER_END)]

    def setUp(self):
        if self.cleaner is None:
            self.fail("packaging/DPort.iss icinde isaretli temizleyici blok yok "
                      "(hosts temizligi bagimsiz olarak test EDILEMIYOR)")

    # ── sozlesme: gorev karari hosts sonucuna BAGLI ────────────────────────
    def test_task_decision_receives_the_hosts_result(self):
        """Gorev kararini hosts sonucu belirler; ama karar KORLEMESINE
        "koru"/"sil" degildir: hedef dogrulamasiyla birlikte merkezi
        uzlastiriciya (ReconcileFailsafeTask) verilir. Siniflandirmanin
        davranisi tests/test_recovery_preflight.py icinde calistirilarak
        dogrulanir."""
        proc = self.text[self.text.index(
            "procedure DropFailsafeTaskAfterHostsCleanup"):]
        proc = proc[:proc.index("procedure CurStepChanged")]
        self.assertIn("CleanHostsBlock(", proc)
        clean = proc.index("CleanHostsBlock(")
        reconcile = proc.index("ReconcileFailsafeTask(")
        self.assertLess(clean, reconcile,
                        "gorev karari hosts sonucundan ONCE veriliyor")
        self.assertIn("HostsCleaned",
                      proc[reconcile:reconcile + 120],
                      "hosts sonucu gorev kararina iletilmiyor")

    def test_clean_hosts_block_returns_boolean(self):
        self.assertIn("function CleanHostsBlock(", self.cleaner,
                      "CleanHostsBlock hala procedure (sonuc dondurmuyor)")
        self.assertIn("Boolean", self.cleaner.split("function CleanHostsBlock(")[1]
                      .split("\n")[0])

    # ── davranis: gercek Inno kodu, gecici fixture'lar ─────────────────────
    def test_behaviour_against_fixtures(self):
        if not os.path.isfile(_ISCC):
            self.skipTest("Inno Setup 6 ISCC.exe bulunamadi")
        import msvcrt
        tmp = tempfile.mkdtemp()
        paths, expect = [], []

        def _fixture(name, body):
            p = os.path.join(tmp, name)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            paths.append(p)
            return p

        missing = os.path.join(tmp, "yok.txt")
        paths.append(missing)
        expect.append("1")                              # dosya yok -> temiz

        clean = _fixture("clean.txt", _CLEAN_FIXTURE)
        expect.append("1")                              # blok yok -> temiz
        block = _fixture("block.txt", _BLOCK_FIXTURE)
        expect.append("1")
        malformed = _fixture("malformed.txt", _MALFORMED_FIXTURE)
        expect.append("1")
        legacy = _fixture("legacy.txt", _LEGACY_FIXTURE)
        expect.append("1")
        locked = _fixture("locked.txt", _BLOCK_FIXTURE)
        expect.append("0")                              # yazilamaz -> BASARISIZ

        harness = _InnoHarness(tmp).build(self.cleaner)
        lock_fh = open(locked, "r+b")
        try:
            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK,
                           os.path.getsize(locked))
            try:
                results = harness.run(paths)
            finally:
                lock_fh.seek(0)
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK,
                               os.path.getsize(locked))
        finally:
            lock_fh.close()

        self.assertEqual(results, expect, f"sonuclar: {results}")

        def _read(p):
            with open(p, encoding="utf-8", errors="ignore") as f:
                return f.read()

        self.assertEqual(_read(clean), _CLEAN_FIXTURE,
                         "temiz dosya gereksiz yere degistirildi")

        after_block = _read(block)
        self.assertNotIn("DPort Discord unblock", after_block)
        self.assertNotIn("127.0.0.1 discord.com", after_block)
        self.assertIn("0.0.0.0 ads.example.com", after_block)
        self.assertIn("0.0.0.0 tracker.example.net", after_block)
        self.assertIn("127.0.0.1 localhost", after_block)

        after_malformed = _read(malformed)
        self.assertNotIn("DPort Discord unblock", after_malformed)
        self.assertNotIn("127.0.0.1 discord.com", after_malformed)
        self.assertIn("0.0.0.0 tracker.example.net", after_malformed,
                      "bitis isareti eksikken yabanci satirlar silindi")
        self.assertIn("0.0.0.0 ads.example.com", after_malformed,
                      "bitis isareti eksikken yabanci satirlar silindi")

        after_legacy = _read(legacy)
        self.assertNotIn("DNSGuardian", after_legacy)
        self.assertNotIn("cdn.discordapp.com", after_legacy)
        self.assertIn("0.0.0.0 keep.example.com", after_legacy)

        self.assertIn("127.0.0.1 discord.com", _read(locked),
                      "yazilamayan dosya sessizce bozuldu")


class TestInstallerScriptCompiles(unittest.TestCase):
    """packaging/DPort.iss GERCEKTEN derleniyor mu (yalniz gecici cikti)."""

    def test_compiles_to_temporary_output(self):
        # Tam derleme dakikalar surer (lzma2/max + tum dist). Normal kosuda
        # atlanir; elle dogrulama icin DPORT_ISCC_COMPILE=1 ile calistirilir.
        if os.environ.get("DPORT_ISCC_COMPILE") != "1":
            self.skipTest("DPORT_ISCC_COMPILE=1 degil (tam derleme atlandi)")
        if not os.path.isfile(_ISS):
            self.skipTest("packaging/DPort.iss yok (gitignore'lu)")
        if not os.path.isfile(_ISCC):
            self.skipTest("Inno Setup 6 ISCC.exe bulunamadi")
        dist = os.path.join(_ROOT, "dist", "DPort", "DPort.exe")
        if not os.path.isfile(dist):
            self.skipTest("dist\\DPort build yok; [Files] kaynagi cozulemez")
        tmp = tempfile.mkdtemp()
        r = subprocess.run(
            [_ISCC, "/Q", f"/O{tmp}", "/FDPort-Setup-compilecheck", _ISS],
            capture_output=True, text=True, timeout=900, cwd=_ROOT)
        self.assertEqual(r.returncode, 0,
                         f"ISCC derlemesi basarisiz:\n{r.stdout}\n{r.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
