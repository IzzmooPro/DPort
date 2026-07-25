"""
tests/test_security_invariants.py

F1, F4 ve F3 guvenlik denetimi bulgularinin duzeltmeleri icin hedefli testler.

KURAL: Bu testler GERCEK sistem durumunu DEGISTIRMEZ. DNS, hosts, registry ve
zamanlanmis gorev yollari mock'lanir; dosya sistemi islemleri yalnizca gecici
dizinde yapilir. Salt-okunur sistem sorgulari (explorer surec listesi,
%ProgramData% yolu) kullanilabilir.

Calistirma:
    python -m unittest discover -s tests -v
"""
import ctypes
import hashlib
import os
import re
import sys
import tempfile
import types
import unittest
from ctypes import wintypes
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import discord_manager, paths, secure_store, updater, user_launch  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
#  F1 — Discord surecleri DPort'un Administrator tokenini MIRAS ALMAMALI
# ═══════════════════════════════════════════════════════════════════════════
class TestF1DiscordLaunchDropsPrivilege(unittest.TestCase):

    def _popen_must_not_run(self, *a, **kw):
        raise AssertionError(
            "Discord yuksek yetkili subprocess.Popen ile baslatildi — F1 degismezi ihlal edildi")

    def test_update_exe_launched_through_user_token_path(self):
        """Update.exe yolu launch_as_user'a gider, dogrudan Popen'a GITMEZ."""
        calls = []
        with mock.patch.object(discord_manager, "find_discord_update",
                               return_value=r"C:\fake\Discord\Update.exe"), \
             mock.patch.object(discord_manager, "close_discord_processes",
                               return_value=(True, "")), \
             mock.patch.object(discord_manager, "launch_as_user",
                               side_effect=lambda a, cwd=None: (calls.append((a, cwd)), (True, ""))[1]), \
             mock.patch.object(discord_manager.subprocess, "Popen", self._popen_must_not_run), \
             mock.patch.object(discord_manager.time, "sleep", lambda *_: None):
            ok, msg = discord_manager.launch_discord(use_updater=True)

        self.assertTrue(ok)
        self.assertIn("Update.exe ile baslatildi", msg)   # mesaj davranisi korunuyor
        self.assertEqual(len(calls), 1)
        argv, cwd = calls[0]
        self.assertEqual(argv, [r"C:\fake\Discord\Update.exe", "--processStart", "Discord.exe"])
        self.assertEqual(cwd, r"C:\fake\Discord")

    def test_discord_exe_launched_through_user_token_path(self):
        calls = []
        with mock.patch.object(discord_manager, "find_discord_update", return_value=None), \
             mock.patch.object(discord_manager, "find_discord_exe",
                               return_value=r"C:\fake\Discord\app-1.0\Discord.exe"), \
             mock.patch.object(discord_manager, "launch_as_user",
                               side_effect=lambda a, cwd=None: (calls.append((a, cwd)), (True, ""))[1]), \
             mock.patch.object(discord_manager.subprocess, "Popen", self._popen_must_not_run):
            ok, msg = discord_manager.launch_discord_direct()

        self.assertTrue(ok)
        self.assertIn("Discord.exe dogrudan baslatildi", msg)
        self.assertEqual(calls[0][0], [r"C:\fake\Discord\app-1.0\Discord.exe"])

    def test_no_high_privilege_fallback_when_user_token_launch_fails(self):
        """Token yolu basarisiz olursa yuksek yetkili Popen'a GERI DUSULMEZ."""
        with mock.patch.object(discord_manager, "find_discord_update",
                               return_value=r"C:\fake\Discord\Update.exe"), \
             mock.patch.object(discord_manager, "close_discord_processes",
                               return_value=(True, "")), \
             mock.patch.object(discord_manager, "launch_as_user",
                               return_value=(False, "token alinamadi")), \
             mock.patch.object(discord_manager.subprocess, "Popen", self._popen_must_not_run), \
             mock.patch.object(discord_manager.time, "sleep", lambda *_: None):
            ok, msg = discord_manager.launch_discord(use_updater=True)

        self.assertFalse(ok)
        self.assertEqual(msg, "token alinamadi")

    def test_elevated_without_shell_token_refuses_instead_of_popen(self):
        """Yukseltilmisken kabuk tokeni yoksa launch_as_user Popen KULLANMAZ."""
        with mock.patch.object(user_launch, "is_elevated", return_value=True), \
             mock.patch.object(user_launch, "_open_desktop_user_token", return_value=None), \
             mock.patch.object(user_launch.subprocess, "Popen", self._popen_must_not_run):
            ok, err = user_launch.launch_as_user([r"C:\fake\x.exe"])

        self.assertFalse(ok)
        self.assertIn("token", err.lower())

    def test_elevated_launch_uses_create_process_with_token(self):
        """Yukseltilmisken surec acikca kabuk tokeniyle olusturulur."""
        seen = {}

        def _fake_create(token, argv, cwd):
            seen["token"] = token
            seen["argv"] = argv
            return True, ""

        with mock.patch.object(user_launch, "is_elevated", return_value=True), \
             mock.patch.object(user_launch, "_open_desktop_user_token", return_value=0xABCD), \
             mock.patch.object(user_launch, "_create_process_with_token", _fake_create), \
             mock.patch.object(user_launch.subprocess, "Popen", self._popen_must_not_run), \
             mock.patch.object(user_launch, "_close", lambda *_: None):
            ok, err = user_launch.launch_as_user([r"C:\fake\x.exe"])

        self.assertTrue(ok, err)
        self.assertEqual(seen["token"], 0xABCD)

    def test_elevated_shell_token_is_rejected(self):
        """Kabuk sureci YUKSELTILMIS ise tokeni kopyalanmaz (yetki dusmezdi)."""
        fake_advapi = mock.MagicMock()
        fake_advapi.OpenProcessToken.return_value = 1
        fake_kernel = mock.MagicMock()
        fake_kernel.OpenProcess.return_value = 0x1111

        with mock.patch.object(user_launch, "_iter_explorer_pids", return_value=[4242]), \
             mock.patch.object(user_launch, "_advapi32", fake_advapi), \
             mock.patch.object(user_launch, "_kernel32", fake_kernel), \
             mock.patch.object(user_launch, "_token_is_elevated", return_value=True), \
             mock.patch.object(user_launch, "_close", lambda *_: None):
            token = user_launch._open_desktop_user_token()

        self.assertIsNone(token)
        fake_advapi.DuplicateTokenEx.assert_not_called()

    def test_unknown_token_state_is_rejected(self):
        """Token durumu OKUNAMAZSA da kullanilmaz (belirsizlikte fail closed)."""
        fake_advapi = mock.MagicMock()
        fake_advapi.OpenProcessToken.return_value = 1
        fake_kernel = mock.MagicMock()
        fake_kernel.OpenProcess.return_value = 0x1111

        with mock.patch.object(user_launch, "_iter_explorer_pids", return_value=[4242]), \
             mock.patch.object(user_launch, "_advapi32", fake_advapi), \
             mock.patch.object(user_launch, "_kernel32", fake_kernel), \
             mock.patch.object(user_launch, "_token_is_elevated", return_value=None), \
             mock.patch.object(user_launch, "_close", lambda *_: None):
            self.assertIsNone(user_launch._open_desktop_user_token())
        fake_advapi.DuplicateTokenEx.assert_not_called()

    def test_non_elevated_process_keeps_plain_popen_behaviour(self):
        """Yukseltilmemisken dusurulecek ayricalik yok: davranis degismez."""
        popen = mock.MagicMock()
        with mock.patch.object(user_launch, "is_elevated", return_value=False), \
             mock.patch.object(user_launch.subprocess, "Popen", popen):
            ok, err = user_launch.launch_as_user([r"C:\fake\x.exe"], cwd=r"C:\fake")

        self.assertTrue(ok, err)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [r"C:\fake\x.exe"])

    def test_shell_lookup_verifies_real_explorer_image(self):
        """Adi 'explorer.exe' olan herhangi bir surec degil, GERCEK kabuk kabul
        edilir (salt-okunur sistem sorgusu)."""
        expected = user_launch._expected_explorer_path()
        self.assertTrue(expected.endswith("explorer.exe"))
        for pid in user_launch._iter_explorer_pids():
            image = user_launch._process_image_path(pid)
            self.assertIsNotNone(image)
            self.assertEqual(os.path.normcase(image), expected)


# ═══════════════════════════════════════════════════════════════════════════
#  F4 — DNS kurtarma verisi kullanici-yazilabilir config'ten AYRI olmali
# ═══════════════════════════════════════════════════════════════════════════
class _ForbiddenConfig:
    """`dns_backup` config'ten okunur/yazilirsa testi dusuren sahte config."""

    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        if key == "dns_backup":
            raise AssertionError("dns_backup KULLANICI CONFIG'INDEN okundu — F4 ihlali")
        return self.data.get(key, default)

    def set(self, key, value):
        if key == "dns_backup" and value is not None:
            raise AssertionError("dns_backup KULLANICI CONFIG'INE yazildi — F4 ihlali")
        self.data[key] = value


class _StubLog:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)

    def console(self, message, level="INFO", ts=None):
        self.lines.append(message)


class TestF4DnsRecoveryState(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from gui import app as gui_app  # customtkinter gerektirir
        cls.gui_app = gui_app
        cls.DPortApp = gui_app.DPortApp

    def setUp(self):
        # GUVENLIK AGI: bu siniftaki hicbir test GERCEK ayricalikli DNS state
        # dosyasini yazmamali. (Yonetici yetkisiyle kosarken secure_store
        # gercekten %ProgramData%'ya yazabilir; oraya birakilan bir yedek, DPort'un
        # bir sonraki acilisinda GERCEK sistem DNS'ine uygulanirdi.)
        self._real_state = secure_store._dns_state_path()
        self._state_existed = bool(self._real_state and os.path.isfile(self._real_state))

    def tearDown(self):
        if self._real_state and not self._state_existed and os.path.isfile(self._real_state):
            try:
                os.remove(self._real_state)
            except OSError:
                pass
            self.fail("Test GERCEK ayricalikli DNS state dosyasi yazdi — "
                      "secure_store mock'lanmali")

    def _stub(self):
        app = types.SimpleNamespace()
        app.cfg = _ForbiddenConfig()
        app.log_mgr = _StubLog()
        app._dns_backup_mem = {}
        app._alive = True
        app._legacy_dns_backup = None
        cls = self.DPortApp
        for name in ("_get_dns_backup", "_set_dns_backup", "_restore_dns",
                     "_backup_dns", "_offer_legacy_dns_restore"):
            setattr(app, name, getattr(cls, name).__get__(app, cls))
        app._sanitize_dns_snapshot = cls._sanitize_dns_snapshot
        app._live_adapter_names = cls._live_adapter_names
        app._describe_dns_backup = cls._describe_dns_backup
        return app

    # ── konum ayrimi ────────────────────────────────────────────────────────
    def test_recovery_state_lives_outside_user_writable_config(self):
        program_data = secure_store._program_data_dir()
        self.assertIsNotNone(program_data, "%ProgramData% cozulemedi")
        secure_root = os.path.normcase(os.path.join(program_data, secure_store.APP_DIR_NAME))
        user_dir = os.path.normcase(paths.user_data_dir())

        self.assertNotEqual(secure_root, user_dir)
        self.assertFalse(secure_root.startswith(user_dir + os.sep),
                         "kurtarma durumu kullanici-yazilabilir dizinin altinda")
        self.assertNotEqual(secure_store.DNS_STATE_FILE, "config.json")

    def test_program_data_path_not_taken_from_environment(self):
        """Konum ortam degiskeninden DEGIL, bilinen klasor API'sinden alinir."""
        with mock.patch.dict(os.environ, {"ProgramData": r"C:\Users\attacker\fake"}):
            self.assertNotEqual(
                os.path.normcase(secure_store._program_data_dir() or ""),
                os.path.normcase(r"C:\Users\attacker\fake"))

    def test_secure_root_fails_closed_when_acl_cannot_be_applied(self):
        """ACL uygulanamiyorsa korumasiz bir konuma DUSULMEZ."""
        with mock.patch.object(secure_store, "apply_protected_acl", return_value=False):
            self.assertIsNone(secure_store.secure_root(refresh=True))
        secure_store.secure_root(refresh=True)  # onbellegi geri al

    def test_secure_root_rejects_reparse_point(self):
        with mock.patch.object(secure_store, "is_reparse_point", return_value=True):
            self.assertIsNone(secure_store.secure_root(refresh=True))
        secure_store.secure_root(refresh=True)

    def test_users_ace_grants_no_write_access(self):
        """Korumali DACL: Users yalnizca oku/calistir; D:P ile kalitim kapali."""
        sddl = secure_store._PROTECTED_SDDL
        self.assertIn("D:P", sddl)
        self.assertTrue(sddl.startswith("O:BA"))

        match = re.search(r"\(A;OICI;(0x[0-9a-fA-F]+);;;BU\)", sddl)
        self.assertIsNotNone(match, "Users (BU) ACE bulunamadi")
        mask = int(match.group(1), 16)

        FILE_WRITE_DATA, FILE_APPEND_DATA, FILE_WRITE_EA = 0x0002, 0x0004, 0x0010
        FILE_WRITE_ATTRIBUTES, DELETE = 0x0100, 0x10000
        WRITE_DAC, WRITE_OWNER = 0x40000, 0x80000
        write_bits = (FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA
                      | FILE_WRITE_ATTRIBUTES | DELETE | WRITE_DAC | WRITE_OWNER)
        self.assertEqual(mask & write_bits, 0,
                         f"Users ACE yazma hakki iceriyor: 0x{mask:x}")

        # SDDL gercekten gecerli mi (Windows tarafindan ayristirilabiliyor mu)
        psd = ctypes.c_void_p()
        ok = secure_store._advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(psd), None)
        self.assertTrue(bool(ok), "korumali SDDL ayristirilamadi")
        secure_store._kernel32.LocalFree(psd)

    # ── state okuma/yazma ───────────────────────────────────────────────────
    def test_state_round_trip_and_untrusted_owner_is_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(secure_store, "secure_root", return_value=tmp), \
                 mock.patch.object(secure_store, "apply_protected_acl", return_value=True), \
                 mock.patch.object(secure_store, "is_reparse_point", return_value=False):

                payload = {"Ethernet": {"ipv4": {"primary": "192.168.1.1", "dhcp": False}}}
                with mock.patch.object(secure_store, "written_by_privileged_process",
                                       return_value=True):
                    self.assertTrue(secure_store.save_dns_backup(payload))
                    self.assertEqual(secure_store.load_dns_backup(), payload)

                state_file = os.path.join(tmp, secure_store.DNS_STATE_FILE)
                self.assertTrue(os.path.isfile(state_file))

                # Sahibi ayricalikli DEGILSE veri guvenilmez sayilir ve SILINIR.
                with mock.patch.object(secure_store, "written_by_privileged_process",
                                       return_value=False):
                    self.assertEqual(secure_store.load_dns_backup(), {})
                self.assertFalse(os.path.isfile(state_file))

    def test_set_backup_never_touches_user_config(self):
        app = self._stub()
        # secure_store MOCK'LANIR: aksi halde yonetici yetkisiyle kosarken GERCEK
        # %ProgramData%\DPort\dns_state.json yazilir ve DPort'un bir sonraki
        # acilisi bu sahte yedegi GERCEK sistem DNS'ine uygular.
        with mock.patch.object(self.gui_app.secure_store, "save_dns_backup",
                               return_value=True), \
             mock.patch.object(self.gui_app.secure_store, "load_dns_backup",
                               return_value={}):
            app._set_dns_backup({"Ethernet": {"ipv4": {"primary": "1.2.3.4", "dhcp": False}}})
            self.assertIn("Ethernet", app._get_dns_backup())   # _ForbiddenConfig patlamadi

    def test_backup_falls_back_to_memory_not_to_user_file(self):
        """Korumali store yoksa yedek BELLEKTE tutulur; config'e yazilmaz."""
        app = self._stub()
        with mock.patch.object(self.gui_app.secure_store, "save_dns_backup", return_value=False), \
             mock.patch.object(self.gui_app.secure_store, "load_dns_backup", return_value={}), \
             mock.patch.object(self.gui_app, "get_dns",
                               return_value={"ipv4": {"primary": "9.9.9.9", "dhcp": False},
                                             "ipv6": {"primary": None, "dhcp": True}}):
            app._backup_dns([{"name": "Ethernet"}])

        self.assertEqual(list(app._dns_backup_mem), ["Ethernet"])
        self.assertNotIn("dns_backup", app.cfg.data)

    # ── geri yukleme dogrulamalari ──────────────────────────────────────────
    def _restore_with(self, backup, adapters, restore_result=(True, "OK")):
        app = self._stub()
        app._dns_backup_mem = dict(backup)
        seen = []

        def _restore(name, snap):
            seen.append((name, snap))
            return restore_result

        with mock.patch.object(self.gui_app.secure_store, "load_dns_backup", return_value={}), \
             mock.patch.object(self.gui_app.secure_store, "save_dns_backup", return_value=False), \
             mock.patch.object(self.gui_app, "get_all_adapters",
                               return_value=[{"name": n} for n in adapters]), \
             mock.patch.object(self.gui_app, "restore_dns", _restore):
            app._restore_dns()
        return app, seen

    def test_adapter_missing_from_live_list_is_never_sent_to_netsh(self):
        backup = {
            "Ethernet": {"ipv4": {"primary": "192.168.1.1", "dhcp": False}},
            "HayaletAdaptor": {"ipv4": {"primary": "185.10.10.10", "dhcp": False}},
        }
        app, seen = self._restore_with(backup, adapters=["Ethernet", "Wi-Fi"])

        self.assertEqual([n for n, _ in seen], ["Ethernet"])
        # Yok sayilan adaptor yedekte KALIR (geri takilirsa tekrar denenir).
        self.assertIn("HayaletAdaptor", app._dns_backup_mem)
        self.assertNotIn("Ethernet", app._dns_backup_mem)

    def test_malformed_values_are_sanitised_before_netsh(self):
        backup = {"Ethernet": {"ipv4": {"primary": "8.8.8.8 & calc.exe", "dhcp": False},
                               "ipv6": {"primary": "not-an-ip", "dhcp": False}}}
        _, seen = self._restore_with(backup, adapters=["Ethernet"])

        self.assertEqual(len(seen), 1)
        snap = seen[0][1]
        self.assertIsNone(snap["ipv4"]["primary"])
        self.assertIsNone(snap["ipv6"]["primary"])

    def test_valid_values_survive_sanitisation(self):
        backup = {"Ethernet": {"ipv4": {"primary": "192.168.1.1", "secondary": "9.9.9.9",
                                        "dhcp": False},
                               "ipv6": {"primary": "2606:4700:4700::1111", "dhcp": False}}}
        _, seen = self._restore_with(backup, adapters=["Ethernet"])
        snap = seen[0][1]
        self.assertEqual(snap["ipv4"]["primary"], "192.168.1.1")
        self.assertEqual(snap["ipv4"]["secondary"], "9.9.9.9")
        self.assertEqual(snap["ipv6"]["primary"], "2606:4700:4700::1111")

    def test_failed_adapter_is_kept_for_retry(self):
        backup = {"Ethernet": {"ipv4": {"primary": "192.168.1.1", "dhcp": False}}}
        app, seen = self._restore_with(backup, adapters=["Ethernet"],
                                       restore_result=(False, "netsh hatasi"))
        self.assertEqual(len(seen), 1)
        self.assertIn("Ethernet", app._dns_backup_mem)   # tekrar deneme korundu

    def test_empty_adapter_name_is_dropped(self):
        backup = {"": {"ipv4": {"primary": "1.1.1.1", "dhcp": False}}}
        app, seen = self._restore_with(backup, adapters=["Ethernet"])
        self.assertEqual(seen, [])
        self.assertEqual(app._dns_backup_mem, {})

    # ── eski (guvenilmeyen) config yedegi ───────────────────────────────────
    def test_legacy_backup_is_not_applied_without_consent(self):
        app = self._stub()
        app._legacy_dns_backup = {"Ethernet": {"ipv4": {"primary": "185.10.10.10",
                                                        "dhcp": False}}}
        app._ask = lambda *a: False       # kullanici "Hayir" diyor
        started = []
        with mock.patch.object(self.gui_app.threading, "Thread",
                               side_effect=lambda **kw: started.append(kw) or mock.MagicMock()):
            app._offer_legacy_dns_restore()

        self.assertEqual(started, [])
        self.assertEqual(app._dns_backup_mem, {})
        self.assertIsNone(app._legacy_dns_backup)

    def test_legacy_backup_is_applied_only_after_consent(self):
        app = self._stub()
        app._legacy_dns_backup = {"Ethernet": {"ipv4": {"primary": "192.168.1.1",
                                                        "dhcp": False}}}
        asked = []
        app._ask = lambda t, m: (asked.append(m), True)[1]
        # Onay verilince _set_dns_backup cagrilir; secure_store MOCK'LANMAZSA
        # gercek ayricalikli state dosyasi yazilirdi (bkz. tearDown guvenlik agi).
        with mock.patch.object(self.gui_app.threading, "Thread", return_value=mock.MagicMock()), \
             mock.patch.object(self.gui_app.secure_store, "save_dns_backup", return_value=True), \
             mock.patch.object(self.gui_app.secure_store, "load_dns_backup", return_value={}):
            app._offer_legacy_dns_restore()

        self.assertEqual(len(asked), 1)
        self.assertIn("192.168.1.1", asked[0])   # kullaniciya gercek deger gosterildi
        self.assertIn("Ethernet", app._dns_backup_mem)


# ═══════════════════════════════════════════════════════════════════════════
#  F3 — Dogrulanan bayt ile calisan bayt AYNI olmali
# ═══════════════════════════════════════════════════════════════════════════
class TestF3UpdateStagingAndToctou(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "DPort-Setup-9.9.exe")
        self.payload = os.urandom(200_000)
        with open(self.path, "wb") as f:
            f.write(self.payload)
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.digest = f"sha256:{self.sha}"

    def tearDown(self):
        self._tmp.cleanup()

    # ── staging konumu ──────────────────────────────────────────────────────
    def test_staging_dir_is_not_user_appdata(self):
        program_data = secure_store._program_data_dir()
        self.assertIsNotNone(program_data)
        staging = os.path.normcase(os.path.join(
            program_data, secure_store.APP_DIR_NAME, secure_store.UPDATE_STAGING_DIR))
        legacy = os.path.normcase(paths.user_data_path("updates"))
        self.assertNotEqual(staging, legacy)
        self.assertFalse(staging.startswith(os.path.normcase(paths.user_data_dir()) + os.sep))

    def test_staging_unavailable_blocks_download(self):
        """Korumali dizin yoksa indirme yapilmaz (guvensiz konuma dusulmez)."""
        with self.assertRaises(updater.UpdateError):
            updater.download_update({"download_url": "https://example/x.exe"}, "")

    # ── kilit semantigi (gercek dosya sistemi, gecici dizin) ─────────────────
    def test_guard_blocks_write_delete_and_rename(self):
        guard = secure_store.GuardedFile(self.path)
        self.assertTrue(guard.open())
        try:
            with self.assertRaises(OSError):
                open(self.path, "wb").close()
            with self.assertRaises(OSError):
                os.remove(self.path)
            with self.assertRaises(OSError):
                os.replace(self.path, self.path + ".swapped")
        finally:
            guard.close()

    def test_guard_still_allows_image_execution_open(self):
        """CreateProcess'in imaj acilisi (READ_DATA|EXECUTE, SHARE_READ|DELETE)
        kilit tutulurken CALISMAYA devam etmeli; aksi halde guncelleme kirilirdi."""
        guard = secure_store.GuardedFile(self.path)
        self.assertTrue(guard.open())
        try:
            handle = secure_store._kernel32.CreateFileW(
                self.path,
                secure_store.FILE_READ_DATA | secure_store.FILE_EXECUTE,
                secure_store.FILE_SHARE_READ | secure_store.FILE_SHARE_DELETE,
                None, secure_store.OPEN_EXISTING, secure_store.FILE_ATTRIBUTE_NORMAL, None)
            self.assertTrue(handle and handle != secure_store.INVALID_HANDLE_VALUE,
                            "kilit altinda imaj acilamadi — guncelleme calistirilamazdi")
            secure_store._kernel32.CloseHandle(wintypes.HANDLE(handle))
        finally:
            guard.close()

    def test_guard_hash_matches_and_is_repeatable(self):
        with secure_store.GuardedFile(self.path) as guard:
            self.assertTrue(guard.ok)
            self.assertEqual(guard.sha256_hex(), self.sha)
            self.assertEqual(guard.sha256_hex(), self.sha)   # handle basa sariliyor

    def test_guard_refuses_reparse_point(self):
        with mock.patch.object(secure_store, "is_reparse_point", return_value=True):
            self.assertFalse(secure_store.GuardedFile(self.path).open())

    # ── launch_verified ─────────────────────────────────────────────────────
    def test_hash_mismatch_blocks_execution(self):
        popen = mock.MagicMock()
        bad = "sha256:" + ("0" * 64)
        with mock.patch.object(updater.subprocess, "Popen", popen):
            ok, err = updater.launch_verified(self.path, bad)
        self.assertFalse(ok)
        self.assertIn("SHA256", err)
        popen.assert_not_called()

    def test_missing_or_invalid_digest_blocks_execution(self):
        popen = mock.MagicMock()
        with mock.patch.object(updater.subprocess, "Popen", popen):
            for digest in (None, "", "md5:abc", "sha256:", "sha256:xyz", self.sha):
                ok, _ = updater.launch_verified(self.path, digest)
                self.assertFalse(ok, f"digest kabul edildi: {digest!r}")
        popen.assert_not_called()

    def test_tampered_file_blocks_execution(self):
        with open(self.path, "wb") as f:
            f.write(b"KOTU AMACLI ICERIK")
        popen = mock.MagicMock()
        with mock.patch.object(updater.subprocess, "Popen", popen):
            ok, _ = updater.launch_verified(self.path, self.digest)
        self.assertFalse(ok)
        popen.assert_not_called()

    def test_matching_hash_launches_once(self):
        popen = mock.MagicMock()
        with mock.patch.object(updater.subprocess, "Popen", popen):
            ok, err = updater.launch_verified(self.path, self.digest)
        self.assertTrue(ok, err)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [self.path])

    def test_file_is_still_locked_at_create_process_time(self):
        """TOCTOU degismezi: CreateProcess ANINDA dosya hala kilitli olmali."""
        observed = {}

        def _popen(argv, **kw):
            try:
                open(argv[0], "wb").close()
                observed["writable"] = True
            except OSError:
                observed["writable"] = False
            return mock.MagicMock()

        with mock.patch.object(updater.subprocess, "Popen", _popen):
            ok, err = updater.launch_verified(self.path, self.digest)

        self.assertTrue(ok, err)
        self.assertIs(observed.get("writable"), False,
                      "dogrulama ile calistirma arasinda dosya degistirilebiliyordu")

    def test_expected_sha256_parser(self):
        self.assertEqual(updater.expected_sha256(f"sha256:{self.sha.upper()}"), self.sha)
        for bad in (None, "", "sha256", "sha1:" + "a" * 40, "sha256:" + "z" * 64,
                    "sha256:" + "a" * 63):
            self.assertIsNone(updater.expected_sha256(bad), bad)

    # ── eski installer temizligi ────────────────────────────────────────────
    def test_purge_removes_only_own_setup_files(self):
        keep_me = os.path.join(self.dir, "kullanici-belgesi.exe")
        partial = os.path.join(self.dir, "DPort-Setup-9.8.exe.download")
        old = os.path.join(self.dir, "DPort-Setup-3.5.exe")
        for p in (keep_me, partial, old):
            with open(p, "wb") as f:
                f.write(b"x")

        removed = updater.purge_setup_dir(self.dir, keep=self.path)

        self.assertEqual(removed, 2)
        self.assertTrue(os.path.isfile(self.path))    # keep korundu
        self.assertTrue(os.path.isfile(keep_me))      # yabanci dosyaya dokunulmadi
        self.assertFalse(os.path.isfile(partial))
        self.assertFalse(os.path.isfile(old))

    def test_purge_handles_missing_directory(self):
        self.assertEqual(updater.purge_setup_dir(os.path.join(self.dir, "yok")), 0)


@unittest.skipUnless(user_launch.is_elevated(),
                     "gercek ACL dogrulamasi yonetici yetkisi ister")
class TestSecureRootRealAcl(unittest.TestCase):
    """Yalnizca yukseltilmis calistirildiginda: korumali dizin gercekten
    olusuyor ve sahibi ayricalikli mi?"""

    def test_real_secure_root_is_privileged(self):
        root = secure_store.secure_root(refresh=True)
        self.assertIsNotNone(root, "korumali kok olusturulamadi")
        self.assertTrue(secure_store.written_by_privileged_process(root))
        self.assertFalse(secure_store.is_reparse_point(root))
        staging = secure_store.update_staging_dir()
        self.assertIsNotNone(staging)
        self.assertTrue(secure_store.written_by_privileged_process(staging))


if __name__ == "__main__":
    unittest.main(verbosity=2)
