"""
tests/test_failsafe_lifecycle.py

DPortHostsFailsafe gorevinin YASAM DONGUSU.

Kural: gorev YALNIZCA DPort'un isaretli hosts yonlendirmesinin aktif
olabilecegi zaman araliginda var olmalidir. Temiz bir acilistan, fresh
install'dan veya normal geri donusten sonra gorev KALMAMALIDIR.

GUVENLIK: Bu testler GERCEK schtasks, hosts, DNS, registry veya Discord
surecine DOKUNMAZ. Tum sistem cagrilari mock'lanir; alt surec testleri
sahte modullerle calisir.
"""
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import failsafe          # noqa: E402
from gui import app as gui_app     # noqa: E402

_ISS = os.path.join(_ROOT, "packaging", "DPort.iss")


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


class _AppStub:
    """DPortApp metotlarini baglamak icin asgari self."""

    def __init__(self):
        self._alive = True
        self.logged = []
        self.status = []
        self.log_mgr = types.SimpleNamespace(
            write=self.logged.append,
            console=lambda m, level="INFO": self.logged.append(m))
        self.unblocker_stopped = 0
        self._unblocker = types.SimpleNamespace(
            start=lambda: True,
            stop=self._stop,
            is_active=lambda: False)
        # Gorev yasam dongusu yardimcilari URETIM sinifindan baglanir:
        # stub taklit etmez, gercek mantigi calistirir.
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

    @staticmethod
    def _is_admin():
        return True

    def bind(self, name):
        return getattr(gui_app.DPortApp, name).__get__(self, gui_app.DPortApp)


# ═══════════════════════════════════════════════════════════════════════════
#  1) Baglanti yolu: gorev hosts YAZILMADAN ONCE kurulur
# ═══════════════════════════════════════════════════════════════════════════
class TestConnectPathInstallsBeforeHosts(unittest.TestCase):

    def test_source_dev_mode_skips_persistent_task_but_opens_path(self):
        order = []
        stub = _AppStub()
        with mock.patch.object(gui_app, "_source_dev_mode", return_value=True), \
             mock.patch.object(gui_app, "install_logon_failsafe") as install, \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               side_effect=lambda: order.append("hosts") or True), \
             mock.patch.object(gui_app, "last_hosts_retry_info",
                               return_value=(1, None, None)):
            ok = stub.bind("_enable_discord_unblock")()

        self.assertTrue(ok)
        install.assert_not_called()
        self.assertEqual(order, ["hosts"])

    def test_task_is_installed_before_add_hosts_redirect(self):
        order = []
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe",
                               side_effect=lambda: order.append("task") or True), \
             mock.patch.object(gui_app, "add_hosts_redirect",
                               side_effect=lambda: order.append("hosts") or True), \
             mock.patch.object(gui_app, "last_hosts_retry_info",
                               return_value=(1, None, None)), \
             mock.patch.object(gui_app, "reconcile_failsafe_task", return_value=True):
            ok = stub.bind("_enable_discord_unblock")()

        self.assertTrue(ok)
        self.assertEqual(order, ["task", "hosts"],
                         "gorev hosts'tan ONCE kurulmadi")

    def test_task_failure_means_hosts_is_never_written_and_relay_stops(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe", return_value=False), \
             mock.patch.object(gui_app, "last_failsafe_error",
                               return_value="dogrulanamadi"), \
             mock.patch.object(gui_app, "add_hosts_redirect") as add_hosts, \
             mock.patch.object(gui_app, "reconcile_failsafe_task", return_value=True):
            ok = stub.bind("_enable_discord_unblock")()

        self.assertFalse(ok, "gorev kurulamadigi halde yol acildi")
        add_hosts.assert_not_called()
        self.assertEqual(stub.unblocker_stopped, 1, "role durdurulmadi")

    def test_hosts_failure_stops_relay_and_reconciles_task(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe", return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect", return_value=False), \
             mock.patch.object(gui_app, "last_hosts_error", return_value="kilitli"), \
             mock.patch.object(gui_app, "last_hosts_winerror", return_value=32), \
             mock.patch.object(gui_app, "remove_hosts_redirect", return_value=True), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as reconcile:
            ok = stub.bind("_enable_discord_unblock")()

        self.assertFalse(ok)
        self.assertEqual(stub.unblocker_stopped, 1, "role durdurulmadi")
        reconcile.assert_called_once_with(True)

    def test_task_removal_failure_after_hosts_error_is_logged(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "install_logon_failsafe", return_value=True), \
             mock.patch.object(gui_app, "add_hosts_redirect", return_value=False), \
             mock.patch.object(gui_app, "last_hosts_error", return_value="kilitli"), \
             mock.patch.object(gui_app, "last_hosts_winerror", return_value=32), \
             mock.patch.object(gui_app, "remove_hosts_redirect", return_value=True), \
             mock.patch.object(gui_app, "reconcile_failsafe_task", return_value=False), \
             mock.patch.object(gui_app, "last_failsafe_error",
                               return_value="gorev silinemedi"):
            stub.bind("_enable_discord_unblock")()

        self.assertTrue(any("gorev silinemedi" in m for m in stub.logged),
                        f"gorev kaldirma hatasi loglanmadi: {stub.logged}")


# ═══════════════════════════════════════════════════════════════════════════
#  2) Temizlik yollari: her yol MERKEZI uzlastiriciyi hosts sonucuyla cagirir
#
#  NOT: "hosts temizlenemedi -> goreve HIC dokunma" kurali BILEREK KALDIRILDI.
#  Gorev hedefinin guvenli olup olmadigi kararini artik tek bir yer verir
#  (core.failsafe.reconcile_failsafe_task); cagiranlarin isi ona DOGRU hosts
#  sonucunu iletmektir. Siniflandirmanin kendisi test_failsafe_reconcile.py
#  icinde dogrulanir.
# ═══════════════════════════════════════════════════════════════════════════
class TestCleanupPathsReconcileTask(unittest.TestCase):

    def test_normal_cleanup_success_reconciles_with_true(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "remove_hosts_redirect", return_value=True), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as reconcile:
            self.assertTrue(stub.bind("_disable_discord_unblock")())
        reconcile.assert_called_once_with(True)
        self.assertEqual(stub.unblocker_stopped, 1)

    def test_normal_cleanup_hosts_failure_reconciles_with_false(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "remove_hosts_redirect", return_value=False), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as reconcile:
            self.assertFalse(stub.bind("_disable_discord_unblock")())
        reconcile.assert_called_once_with(False)
        self.assertEqual(stub.unblocker_stopped, 1, "role yine de durmali")

    def test_cleanup_exception_reconciles_with_false(self):
        stub = _AppStub()
        with mock.patch.object(gui_app, "remove_hosts_redirect",
                               side_effect=OSError("hosts kilitli")), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as reconcile:
            self.assertFalse(stub.bind("_disable_discord_unblock")())
        reconcile.assert_called_once_with(False)
        self.assertEqual(stub.unblocker_stopped, 1)

    def _watchdog_once(self, hosts_result):
        stub = _AppStub()
        stub._alive = True

        def _sleep(_s):
            stub._alive = False

        kwargs = ({"side_effect": hosts_result}
                  if isinstance(hosts_result, Exception)
                  else {"return_value": hosts_result})
        with mock.patch.object(gui_app.time, "sleep", _sleep), \
             mock.patch.object(gui_app, "is_hosts_redirect_active", return_value=True), \
             mock.patch.object(gui_app, "remove_hosts_redirect", **kwargs), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True) as reconcile:
            stub.bind("_watchdog_loop")()
        return stub, reconcile

    def test_watchdog_reconciles_with_true_after_cleaning_hosts(self):
        _, reconcile = self._watchdog_once(True)
        reconcile.assert_called_once_with(True)

    def test_watchdog_reconciles_with_false_when_hosts_cleanup_fails(self):
        _, reconcile = self._watchdog_once(False)
        reconcile.assert_called_once_with(False)

    def test_watchdog_reconciles_with_false_on_exception(self):
        _, reconcile = self._watchdog_once(OSError("hosts kilitli"))
        reconcile.assert_called_once_with(False)


# ═══════════════════════════════════════════════════════════════════════════
#  3) Uygulama acilisi: yeni gorev KURULMAZ, stale gorev kalkar
# ═══════════════════════════════════════════════════════════════════════════
class TestStartupDoesNotCreateTask(unittest.TestCase):

    def _startup_patches(self, hosts_cleaned, install_probe, reconcile_probe):
        g = gui_app
        return [
            mock.patch.object(g, "remove_hosts_redirect", return_value=hosts_cleaned),
            mock.patch.object(g, "install_logon_failsafe", install_probe),
            mock.patch.object(g, "reconcile_failsafe_task", reconcile_probe),
            mock.patch.object(g.secure_store, "load_dns_backup", return_value={}),
            mock.patch.object(g.secure_store, "save_dns_backup", return_value=True),
            mock.patch.object(g.DPortApp, "_flushdns", lambda self: None),
            mock.patch.object(g.DPortApp, "_apply_icon", lambda self: None),
            mock.patch.object(g.DPortApp, "_start_ipc", lambda self: None),
            mock.patch.object(g.DPortApp, "_watchdog_loop", lambda self: None),
            mock.patch.object(g.DPortApp, "_status_tick", lambda self: None),
            mock.patch.object(g.DPortApp, "_uptime_tick", lambda self: None),
            mock.patch.object(g.DPortApp, "_check_updates_on_start", lambda self: None),
            mock.patch.object(g.DPortApp, "_purge_legacy_downloads", lambda self: None),
            mock.patch.object(g.DPortApp, "_offer_legacy_dns_restore", lambda self: None),
        ]

    def _boot(self, hosts_cleaned):
        install = mock.MagicMock(return_value=True)
        reconcile = mock.MagicMock(return_value=True)
        for p in self._startup_patches(hosts_cleaned, install, reconcile):
            p.start()
        app = None
        try:
            app = gui_app.DPortApp()
        finally:
            if app is not None:
                try:
                    for aid in app.tk.splitlist(app.tk.call("after", "info")):
                        try:
                            app.after_cancel(aid)
                        except Exception:
                            pass
                    app.update_idletasks()
                    app.destroy()
                    app.update()
                except Exception:
                    pass
            mock.patch.stopall()
        return install, reconcile

    def test_clean_startup_installs_no_task(self):
        install, _ = self._boot(hosts_cleaned=True)
        install.assert_not_called()

    @staticmethod
    def _first_call(reconcile):
        """ACILIS cagrisi. (Ikinci cagri testin kendi destroy()'undan gelir.)"""
        assert reconcile.call_args_list, "gorev hic uzlastirilmadi"
        return reconcile.call_args_list[0]

    def test_startup_removes_stale_task_after_successful_hosts_cleanup(self):
        _, reconcile = self._boot(hosts_cleaned=True)
        self.assertEqual(self._first_call(reconcile), mock.call(True))

    def test_startup_reconciles_task_even_when_hosts_cleanup_fails(self):
        """Eskiden bu yol goreve HIC dokunmuyordu; boylece hedefi okunamayan
        veya kullanici-yazilabilir bir HIGHEST gorev acilista ayakta kaliyordu."""
        install, reconcile = self._boot(hosts_cleaned=False)
        install.assert_not_called()
        self.assertEqual(self._first_call(reconcile), mock.call(False))


# ═══════════════════════════════════════════════════════════════════════════
#  4) --cleanup-hosts modu: hosts + gorev, belgelenmis cikis kodlari
# ═══════════════════════════════════════════════════════════════════════════
_HARNESS = r'''
import os, sys, types, runpy

APP, HOSTS_OK, TASK_OK, FLAG = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, APP)

BANNED = ("customtkinter", "tkinter", "gui.app", "gui",
          "core.dns_manager", "core.adapter_manager", "core.discord_manager",
          "core.updater", "core.secure_store")


class _Guard:
    def find_spec(self, name, path=None, target=None):
        if name in BANNED:
            raise AssertionError("YASAK MODUL YUKLENDI: " + name)
        return None


sys.meta_path.insert(0, _Guard())
import core

unblock = types.ModuleType("core.discord_unblock")
if HOSTS_OK == "raise":
    def _remove():
        raise OSError("hosts okunamadi")
else:
    def _remove():
        return HOSTS_OK == "1"
unblock.remove_hosts_redirect = _remove
sys.modules["core.discord_unblock"] = unblock

fs = types.ModuleType("core.failsafe")
if TASK_OK == "raise":
    def _rec(hosts_cleared):
        raise OSError("schtasks patladi")
else:
    def _rec(hosts_cleared):
        return TASK_OK == "1"
fs.reconcile_failsafe_task = _rec
fs.remove_logon_failsafe = lambda: TASK_OK == "1"
fs.last_failsafe_error = lambda: "" if TASK_OK == "1" else "gorev silinemedi"
sys.modules["core.failsafe"] = fs

sys.argv = ["main.py", FLAG]
runpy.run_path(os.path.join(APP, "main.py"), run_name="__main__")
'''


class TestCleanupHostsMode(unittest.TestCase):
    """`DPort.exe --cleanup-hosts` — logon gorevinin calistirdigi mod."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.harness = os.path.join(tempfile.mkdtemp(), "cleanup_harness.py")
        with open(cls.harness, "w", encoding="utf-8") as f:
            f.write(_HARNESS)

    def _run(self, hosts_ok, task_ok, flag="--cleanup-hosts"):
        return subprocess.run(
            [sys.executable, self.harness, _APP, hosts_ok, task_ok, flag],
            capture_output=True, text=True, timeout=60)

    def test_success_cleans_hosts_and_task_and_exits_zero(self):
        r = self._run("1", "1")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_hosts_failure_does_not_delete_task_and_exits_nonzero(self):
        r = self._run("0", "1")
        self.assertNotEqual(r.returncode, 0, "hosts temizlenemedigi halde 0 donuldu")
        self.assertIn("TASK_NOT_TOUCHED", r.stdout + r.stderr,
                      "hosts hatasinda gorev silme denenmis olabilir")

    def test_hosts_exception_does_not_delete_task_and_exits_nonzero(self):
        r = self._run("raise", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("TASK_NOT_TOUCHED", r.stdout + r.stderr)

    def test_task_removal_failure_exits_nonzero(self):
        r = self._run("1", "0")
        self.assertNotEqual(r.returncode, 0,
                            "gorev silinemedigi halde 0 donuldu")

    def test_task_removal_exception_exits_nonzero(self):
        r = self._run("1", "raise")
        self.assertNotEqual(r.returncode, 0)

    def test_no_gui_dns_relay_or_ipc_module_is_loaded(self):
        for hosts_ok, task_ok in (("1", "1"), ("0", "1"), ("1", "0")):
            with self.subTest(hosts=hosts_ok, task=task_ok):
                r = self._run(hosts_ok, task_ok)
                self.assertNotIn("YASAK MODUL", r.stderr,
                                 f"cleanup modu yasak modul yukledi\n{r.stderr}")


# ═══════════════════════════════════════════════════════════════════════════
#  5) Installer: temiz kurulumda gorev BIRAKMAZ
#
#  NOT: Kurulum, hosts kalintisi DOGRULANMIS bicimde temizlendiginde gorev
#  olusturmaz. Yonlendirme temizlenemediyse GUVENLI bir kurtarma gorevi kurar
#  (aksi halde temizleyicisi olmayan bir yonlendirme kalirdi); bunun davranisi
#  tests/test_recovery_preflight.py icinde calistirilarak dogrulanir.
# ═══════════════════════════════════════════════════════════════════════════
class TestInstallerLeavesNoTaskOnCleanSystem(unittest.TestCase):

    def setUp(self):
        if not os.path.isfile(_ISS):
            self.skipTest("packaging/DPort.iss yok (gitignore'lu yerel dosya)")
        self.text = _read(_ISS)

    def test_installer_does_not_run_sync_failsafe_maintenance_mode(self):
        self.assertNotIn("--sync-failsafe", self.text,
                         "installer hala gorev olusturan bakim modunu calistiriyor")

    def test_installer_still_removes_legacy_and_current_tasks(self):
        self.assertIn("TaskDeleteVerified", self.text)
        self.assertIn("LEGACY_TASK", self.text)

    def test_installer_cleans_hosts_before_dropping_the_task(self):
        """Upgrade'de kalan hosts blogu temizlenmeden gorev korlemesine silinmemeli."""
        self.assertIn("CleanHostsBlock", self.text)
        install_proc = self.text[self.text.index("procedure DropFailsafeTaskAfterHostsCleanup"):]
        install_proc = install_proc[:install_proc.index("procedure CurStepChanged")]
        self.assertIn("CleanHostsBlock", install_proc,
                      "kurulum yolunda hosts temizligi yapilmadan gorev siliniyor")

    def test_uninstall_still_cleans_hosts_and_task(self):
        block = self.text[self.text.index("procedure CurUninstallStepChanged"):]
        self.assertIn("CleanHostsBlock", block)
        self.assertIn("DPortHostsFailsafe", block)


# ═══════════════════════════════════════════════════════════════════════════
#  6) Guvenlik sertlestirmeleri KORUNUYOR (regresyon kalkani)
# ═══════════════════════════════════════════════════════════════════════════
class TestHardeningStillPresent(unittest.TestCase):

    def test_install_still_requires_verified_target(self):
        with mock.patch.object(failsafe, "verified_failsafe_target", return_value=None), \
             mock.patch.object(failsafe, "_ensure_no_unsafe_task", return_value=True), \
             mock.patch.object(failsafe.subprocess, "run") as run:
            self.assertFalse(failsafe.install_logon_failsafe())
        for call in run.call_args_list:
            self.assertNotIn("/Create", call.args[0])

    def test_public_helpers_still_exist(self):
        for name in ("install_logon_failsafe", "remove_logon_failsafe",
                     "reconcile_failsafe_task",
                     "path_is_verified_install", "verified_failsafe_target",
                     "dacl_writers_are_trusted", "owner_is_trusted",
                     "canonical_path", "last_failsafe_error"):
            self.assertTrue(hasattr(failsafe, name), f"{name} kayboldu")

    def test_dead_sync_helper_is_gone(self):
        self.assertFalse(hasattr(failsafe, "sync_logon_failsafe"),
                         "olu sync_logon_failsafe hala duruyor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
