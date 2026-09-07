"""
tests/test_recovery_preflight.py

v3.13 oncesi son tur: iki bulgunun regresyon kalkani.

  1) INSTALLER GOREV GUVENLIGI
     hosts temizligi basarisiz oldugunda installer, ayakta olan HIGHEST yetkili
     gorevi KORLEMESINE korumamali. Legacy adlar her durumda kaldirilmali;
     guncel gorev okunup DOGRULANMALI; yalnizca korumali
     `{app}\\DPort.exe --cleanup-hosts` hedefiyle BIREBIR eslesen gorev
     korunabilir. Aksi halde gorev degistirilmeli, olusturma sonrasi GERI
     OKUNARAK dogrulanmali, dogrulanamazsa kurulum GORUNUR bicimde basarisiz
     olmali.

  2) MUTATION ONCESI RECOVERY-TARGET PREFLIGHT
     Kaynak modunda dogrulanmis kurulu recovery hedefi YOKKEN DNS'e, hosts'a,
     roleye, zamanlanmis goreve veya Discord'a HIC dokunulmamali. "DNS'i degistir
     sonra geri al" davranisi basari sayilmaz.

Installer tarafinin gorev/hedef guvenligi ayri bir dosyada, uretim `.iss`
kodunun kendisi calistirilarak dogrulanir:
tests/test_installer_target_verification.py

GUVENLIK: Gercek schtasks/hosts/DNS/registry cagrisi YOK.
"""
import inspect
import os
import sys
import types
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import discord_manager   # noqa: E402
from core.lang import L, TR, EN    # noqa: E402
from gui import app as gui_app     # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
#  Mutation oncesi preflight
# ═══════════════════════════════════════════════════════════════════════════
class _Widget:
    def __init__(self):
        self.calls = []

    def configure(self, **kw):
        self.calls.append(kw)


class _ConnectStub:
    """`_activate_connection_w` akisini calistirmak icin asgari self.

    Sistem durumunu DEGISTIREN her adim burada sayaca yazilir; testler bu
    sayaclarin SIFIR kaldigini dogrular."""

    def __init__(self):
        self._alive = True
        self._busy = True
        self._connecting = True
        self._status_generation = 0
        self.logged = []
        self.status = []
        self.mutations = []
        self.btn_open = _Widget()
        self.log_mgr = types.SimpleNamespace(
            write=self.logged.append,
            console=lambda m, level="INFO": self.logged.append(f"[{level}] {m}"))
        self._unblocker = types.SimpleNamespace(
            start=self._relay_start, stop=lambda: None, is_active=lambda: False)
        for helper in ("_preflight_failsafe_target",
                       "_install_failsafe_before_hosts"):
            setattr(self, helper, self.bind(helper))

    # ── mutasyon noktalari (hepsi kayit tutar) ──
    def _relay_start(self):
        self.mutations.append("relay.start")
        return True

    def _backup_dns(self, adapters):
        self.mutations.append("backup_dns")

    def _restore_dns(self):
        self.mutations.append("restore_dns")
        return True

    def _flushdns(self):
        self.mutations.append("flushdns")

    def _enable_discord_unblock(self):
        self.mutations.append("enable_unblock")
        return True

    def _restart_discord_for_new_path(self):
        self.mutations.append("restart_discord")
        return True, "ok"

    # ── zararsiz yardimcilar ──
    def _preflight_discord_unblock(self):
        self.logged.append("doh-preflight")
        return True

    def _discord_should_use_updater(self):
        return False

    def _set_discord_update_phase(self, phase):
        pass

    def _refresh_status_async(self):
        pass

    def _finish_connection_operation(self, can_retry=False):
        self._busy = self._connecting = False

    def _st(self, text, color=None):
        self.status.append(text)

    def after(self, _delay, func=None, *args):
        if func is not None:
            func(*args)

    def bind(self, name):
        return getattr(gui_app.DPortApp, name).__get__(self, gui_app.DPortApp)


class TestRecoveryPreflightBlocksMutations(unittest.TestCase):

    def _run_connect(self, target, **extra):
        stub = _ConnectStub()
        patches = {
            "verified_failsafe_target": {"return_value": target},
            "get_active_adapters": {"return_value": [{"name": "Wi-Fi"}]},
            "set_dns": {"return_value": (True, "ok")},
            "install_logon_failsafe": {"return_value": True},
            "add_hosts_redirect": {"return_value": True},
        }
        patches.update(extra)
        ctx = [mock.patch.object(gui_app, name, **kw)
               for name, kw in patches.items()]
        started = {name: p.start() for name, p in zip(patches, ctx)}
        launch_patch = mock.patch.object(
            discord_manager, "launch_discord", return_value=(True, "ok"))
        started["launch_discord"] = launch_patch.start()
        try:
            stub.bind("_activate_connection_w")()
        finally:
            mock.patch.stopall()
        return stub, started

    def test_no_recovery_target_touches_nothing(self):
        stub, _ = self._run_connect(target=None)
        self.assertEqual(stub.mutations, [],
                         f"preflight basarisizken sistem degistirildi: "
                         f"{stub.mutations}")

    def test_no_recovery_target_never_calls_system_mutators(self):
        stub = _ConnectStub()
        with mock.patch.object(gui_app, "verified_failsafe_target",
                               return_value=None), \
             mock.patch.object(gui_app, "get_active_adapters") as adapters, \
             mock.patch.object(gui_app, "set_dns") as set_dns, \
             mock.patch.object(gui_app, "add_hosts_redirect") as add_hosts, \
             mock.patch.object(gui_app, "install_logon_failsafe") as install, \
             mock.patch.object(discord_manager, "launch_discord") as launch:
            stub.bind("_activate_connection_w")()

        adapters.assert_not_called()
        set_dns.assert_not_called()
        add_hosts.assert_not_called()
        install.assert_not_called()
        launch.assert_not_called()

    def test_doh_preflight_is_not_even_reached(self):
        """Salt-okunur recovery kontrolu EN BASTA calisir; agsiz makinede bile
        kullaniciya dogru neden gosterilir."""
        stub, _ = self._run_connect(target=None)
        self.assertNotIn("doh-preflight", stub.logged)

    def test_user_message_is_short_and_specific(self):
        stub, _ = self._run_connect(target=None)
        self.assertIn(L["st_fail_no_recovery"], stub.status)
        self.assertNotIn(L["st_fail_failsafe"], stub.status)

    def test_message_exists_in_both_languages_and_fits(self):
        for table in (TR, EN):
            self.assertIn("st_fail_no_recovery", table)
            self.assertLessEqual(len(table["st_fail_no_recovery"]), 70,
                                 "durum satiri pencereye sigmayacak kadar uzun")
        self.assertIn("dport", TR["st_fail_no_recovery"].lower())
        self.assertIn("yeniden kur", TR["st_fail_no_recovery"].lower())

    def test_status_label_reserves_wrapped_error_space(self):
        source = inspect.getsource(gui_app.DPortApp._build)
        status_source = source[source.index("self.status_lbl ="):]
        self.assertIn("width=286", status_source)
        self.assertIn("height=38", status_source)
        self.assertIn("wraplength=286", status_source)
        self.assertIn('justify="left"', status_source)

    def test_technical_reason_stays_in_the_log(self):
        stub, _ = self._run_connect(target=None)
        self.assertTrue(any("FAILSAFE" in m for m in stub.logged),
                        f"teknik neden loglanmadi: {stub.logged}")

    def test_verified_target_lets_the_flow_continue(self):
        stub, _ = self._run_connect(target=r"c:\program files\dport\dport.exe")
        self.assertIn("enable_unblock", stub.mutations,
                      f"dogrulanmis hedefle akis durdu: {stub.mutations}")
        self.assertNotIn(L["st_fail_no_recovery"], stub.status)

    def test_explicit_source_dev_mode_can_test_current_source(self):
        with mock.patch.object(gui_app, "_source_dev_mode", return_value=True):
            stub, _ = self._run_connect(target=None)

        self.assertIn("enable_unblock", stub.mutations)
        self.assertNotIn(L["st_fail_no_recovery"], stub.status)
        self.assertTrue(any("GELISTIRICI MODU" in m for m in stub.logged))

    def test_source_dev_flag_is_ignored_by_packaged_app(self):
        with mock.patch.object(sys, "argv", ["DPort.exe", "--source-dev"]), \
             mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(gui_app._source_dev_mode())

    def test_calistir_explicitly_selects_source_dev_mode(self):
        launcher = os.path.join(_ROOT, "scripts", "Calistir.bat")
        with open(launcher, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('python "app\\main.py" --source-dev', source)

    def test_activation_never_launches_or_restarts_discord(self):
        """DPort yalnizca yolu acar; Discord kullanicinin kendi uygulamasidir."""
        stub, patches = self._run_connect(target=r"c:\program files\dport\dport.exe")
        self.assertIn("enable_unblock", stub.mutations)
        self.assertNotIn("restart_discord", stub.mutations)
        patches["launch_discord"].assert_not_called()
        self.assertIn(L["st_activated"], stub.status)

    def test_preflight_exception_is_treated_as_failure(self):
        stub, _ = self._run_connect(
            target=None,
            verified_failsafe_target={"side_effect": OSError("api patladi")})
        self.assertEqual(stub.mutations, [])
        self.assertIn(L["st_fail_no_recovery"], stub.status)

    def test_preflight_itself_mutates_nothing(self):
        """On-kontrol SALT-OKUNUR olmali: gorev kurmaz/silmez."""
        stub = _ConnectStub()
        with mock.patch.object(gui_app, "verified_failsafe_target",
                               return_value=None), \
             mock.patch.object(gui_app, "install_logon_failsafe") as install, \
             mock.patch.object(gui_app, "reconcile_failsafe_task") as reconcile:
            self.assertFalse(stub._preflight_failsafe_target())
        install.assert_not_called()
        reconcile.assert_not_called()


class TestPreflightIsNotTheFinalGuard(unittest.TestCase):
    """TOCTOU: on-kontrol ile gorev kurulumu arasinda hedef bozulabilir."""

    def test_target_lost_after_preflight_still_blocks_hosts(self):
        stub = _ConnectStub()
        with mock.patch.object(gui_app, "verified_failsafe_target",
                               return_value=r"c:\program files\dport\dport.exe"), \
             mock.patch.object(gui_app, "get_active_adapters",
                               return_value=[{"name": "Wi-Fi"}]), \
             mock.patch.object(gui_app, "set_dns", return_value=(True, "ok")), \
             mock.patch.object(discord_manager, "launch_discord",
                               return_value=(True, "ok")), \
             mock.patch.object(gui_app, "install_logon_failsafe",
                               return_value=False) as install, \
             mock.patch.object(gui_app, "last_failsafe_error",
                               return_value="hedef artik dogrulanamiyor"), \
             mock.patch.object(gui_app, "add_hosts_redirect") as add_hosts, \
             mock.patch.object(gui_app, "remove_hosts_redirect",
                               return_value=True), \
             mock.patch.object(gui_app, "reconcile_failsafe_task",
                               return_value=True):
            # _enable_discord_unblock URETIM surumu calissin (stub'unki degil)
            for name in ("_enable_discord_unblock", "_disable_discord_unblock",
                         "_reconcile_failsafe_task",
                         "_rollback_after_enable_failure"):
                setattr(stub, name, stub.bind(name))
            stub.bind("_activate_connection_w")()

        install.assert_called_once()
        add_hosts.assert_not_called()
        self.assertIn("restore_dns", stub.mutations,
                      "son kontrol basarisizken DNS geri alinmadi")
# ═══════════════════════════════════════════════════════════════════════════
#  NOT: Bu dosyada bulunan installer gorev-guvenligi harness'i
#  tests/test_installer_target_verification.py icine TASINDI. Orada ayni
#  senaryolar (guvenli gorev korunur / degistirilmis gorev degistirilir /
#  okunamayan gorev / legacy her zaman silinir / geri okuma uyusmazligi /
#  olusturma hatasi / temiz sistem) GERCEK uretim kodunun HEDEF DOGRULAMASI
#  ile birlikte calistirilir. Senaryolar silinmedi, kapsamlari genisletildi.
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    unittest.main(verbosity=2)
