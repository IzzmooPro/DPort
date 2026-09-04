"""
tests/test_reliability_fixes.py

v3.12 guvenilirlik duzeltmeleri icin regresyon testleri.

KURAL: Bu testler GERCEK DNS, hosts, registry, zamanlanmis gorev veya Discord
surecine DOKUNMAZ. Ag kullanimi yalnizca 127.0.0.1 uzerinde, testin kendi
actigi gecici soketlerledir. Zaman gecisi sahte saatle taklit edilir; gercek
time.sleep KULLANILMAZ.
"""
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import types
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)


def _load_main():
    """app/main.py'yi modul olarak yukler (__main__ blogu calismaz)."""
    spec = importlib.util.spec_from_file_location(
        "dport_main_under_test", os.path.join(_APP, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main = _load_main()
from core import startup_manager  # noqa: E402
from gui import app as gui_app    # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
#  1) IPC tek-ornek handshake
# ═══════════════════════════════════════════════════════════════════════════
class _Listener:
    """Gecici 127.0.0.1 dinleyicisi. handler(conn) -> None."""

    def __init__(self, handler):
        self.handler = handler
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(2)
        self.port = self.srv.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            try:
                self.handler(conn)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        try:
            self.srv.close()
        except OSError:
            pass


class TestIpcHandshake(unittest.TestCase):

    def test_unrelated_listener_that_never_acks_is_not_dport(self):
        """(a) Baglanti kabul eden ILGISIZ bir servis DPort sayilmamali."""
        listener = _Listener(lambda conn: conn.recv(64))   # okur, ACK YOK
        self.addCleanup(listener.close)
        with mock.patch.object(main, "IPC_PORT", listener.port):
            self.assertFalse(main.signal_existing())

    def test_listener_sending_garbage_is_not_dport(self):
        """Yanlis ACK gonderen bir servis de DPort sayilmamali."""
        def _garbage(conn):
            conn.recv(64)
            conn.sendall(b"HTTP/1.1 200 OK\r\n\r\n")

        listener = _Listener(_garbage)
        self.addCleanup(listener.close)
        with mock.patch.object(main, "IPC_PORT", listener.port):
            self.assertFalse(main.signal_existing())

    def test_correct_dport_handshake_is_detected(self):
        """(b) Gercek DPort sunucusu -> True."""
        received = []

        def _dport(conn):
            data = conn.recv(len(gui_app.IPC_REQUEST))
            received.append(data)
            if data == gui_app.IPC_REQUEST:
                conn.sendall(gui_app.IPC_ACK)

        listener = _Listener(_dport)
        self.addCleanup(listener.close)
        with mock.patch.object(main, "IPC_PORT", listener.port):
            self.assertTrue(main.signal_existing())
        self.assertEqual(received, [gui_app.IPC_REQUEST])

    def test_no_listener_at_all_returns_false(self):
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with mock.patch.object(main, "IPC_PORT", port):
            self.assertFalse(main.signal_existing())

    def test_server_accepts_only_the_exact_show_request(self):
        """(c) Yanlis payload alan sunucu pencereyi GOSTERMEZ ve ACK VERMEZ."""
        for payload in (b"SHOW", b"", b"DPORT-IPC-1 SHOW",
                        b"DPORT-IPC-1 QUIT\n", b"x" * 200):
            with self.subTest(payload=payload):
                a, b = socket.socketpair()
                self.addCleanup(a.close)
                self.addCleanup(b.close)
                a.sendall(payload)
                a.shutdown(socket.SHUT_WR)
                self.assertFalse(gui_app.serve_ipc_connection(b),
                                 f"gecersiz istek kabul edildi: {payload!r}")
                a.settimeout(0.5)
                try:
                    self.assertEqual(a.recv(64), b"", "gecersiz isteğe ACK gonderildi")
                except socket.timeout:
                    pass

    def test_server_acks_and_reports_valid_request(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.sendall(gui_app.IPC_REQUEST)
        a.shutdown(socket.SHUT_WR)          # mesaj cercevesi: yazma tarafi kapanir
        self.assertTrue(gui_app.serve_ipc_connection(b))
        a.settimeout(1)
        self.assertEqual(a.recv(len(gui_app.IPC_ACK)), gui_app.IPC_ACK)

    def test_valid_prefix_followed_by_extra_bytes_is_rejected(self):
        """Gecerli istek + FAZLADAN veri kabul EDILMEMELI.

        Sunucu yalnizca len(IPC_REQUEST) kadar okuyup onek karsilastirdiginda
        `IPC_REQUEST + b"JUNK"` gecerli sayiliyor, ACK aliyor ve pencereyi one
        getiriyordu."""
        for extra in (b"JUNK", b"\n", b" ", gui_app.IPC_REQUEST, b"A" * 100):
            with self.subTest(extra=extra):
                a, b = socket.socketpair()
                self.addCleanup(a.close)
                self.addCleanup(b.close)
                a.sendall(gui_app.IPC_REQUEST + extra)
                a.shutdown(socket.SHUT_WR)

                self.assertFalse(gui_app.serve_ipc_connection(b),
                                 f"fazla payload kabul edildi: {extra!r}")
                a.settimeout(0.5)
                try:
                    self.assertEqual(a.recv(64), b"",
                                     f"fazla payload'a ACK gonderildi: {extra!r}")
                except OSError:
                    pass          # timeout veya RST: ACK yok demektir

    def test_extra_payload_does_not_reach_the_show_window_path(self):
        """Fazla payload gonderen istemci pencereyi one getirtemez."""
        listener = _Listener(lambda conn: None)
        self.addCleanup(listener.close)
        decisions = []

        def _server(conn):
            decisions.append(gui_app.serve_ipc_connection(conn))

        listener.handler = _server
        c = socket.create_connection(("127.0.0.1", listener.port), timeout=2)
        c.sendall(gui_app.IPC_REQUEST + b"JUNK")
        c.shutdown(socket.SHUT_WR)
        c.settimeout(1)
        try:
            ack = c.recv(64)
        except OSError:
            # Zaman asimi ya da RST (sunucu okunmamis fazla veriyle kapatti):
            # ikisi de "ACK GELMEDI" demektir.
            ack = b""
        c.close()
        for _ in range(50):
            if decisions:
                break
            threading.Event().wait(0.02)
        self.assertEqual(ack, b"", "fazla payload'a ACK gonderildi")
        self.assertEqual(decisions, [False], "pencere gosterme karari True cikti")

    def test_client_and_server_agree_on_port_and_protocol(self):
        self.assertEqual(main.IPC_PORT, gui_app.IPC_PORT)
        self.assertEqual(main.IPC_HOST, gui_app.IPC_HOST)
        self.assertEqual(main.IPC_REQUEST, gui_app.IPC_REQUEST)
        self.assertEqual(main.IPC_ACK, gui_app.IPC_ACK)

    def test_silent_listener_does_not_hang_the_client(self):
        """Hic cevap vermeyen servis istemciyi SINIRSIZ bekletmemeli."""
        listener = _Listener(lambda conn: threading.Event().wait(5))
        self.addCleanup(listener.close)
        import time as _t
        with mock.patch.object(main, "IPC_PORT", listener.port):
            t0 = _t.time()
            result = main.signal_existing()
            elapsed = _t.time() - t0
        self.assertFalse(result)
        self.assertLess(elapsed, 4.0, f"istemci {elapsed:.1f} sn askida kaldi")


# ═══════════════════════════════════════════════════════════════════════════
#  2) Baslangic komutunun tirnaklanmasi
# ═══════════════════════════════════════════════════════════════════════════
SPACED_EXE = r"C:\Program Files\DPort\DPort.exe"


class TestStartupCommandQuoting(unittest.TestCase):

    def test_frozen_path_with_spaces_is_quoted(self):
        with mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", SPACED_EXE):
            self.assertEqual(startup_manager._get_exe_path(),
                             f'"{SPACED_EXE}"')

    def test_frozen_path_without_spaces_needs_no_quotes(self):
        plain = r"C:\DPort\DPort.exe"
        with mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", plain):
            self.assertEqual(startup_manager._get_exe_path(), plain)

    def test_source_mode_quotes_both_interpreter_and_script(self):
        py = r"C:\Program Files\Python\python.exe"
        script = r"C:\Program Files\DPort\app\main.py"
        with mock.patch.object(startup_manager.sys, "frozen", False, create=True), \
             mock.patch.object(startup_manager.sys, "executable", py), \
             mock.patch.object(startup_manager.sys, "argv", [script]), \
             mock.patch.object(startup_manager.os.path, "abspath", lambda p: p):
            cmd = startup_manager._get_exe_path()
        self.assertEqual(cmd, f'"{py}" "{script}"')

    def test_command_round_trips_through_windows_argument_parser(self):
        """Uretilen komut satiri, Windows kurallarina gore geri ayristirilinca
        ORIJINAL yolu vermeli."""
        with mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", SPACED_EXE):
            cmd = startup_manager._get_exe_path()
        self.assertEqual(cmd, subprocess.list2cmdline([SPACED_EXE]))

    def test_enable_startup_writes_the_quoted_command(self):
        written = {}

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(startup_manager, "_HAS_WINREG", True), \
             mock.patch.object(startup_manager, "winreg", create=True) as reg, \
             mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", SPACED_EXE):
            reg.OpenKey.return_value = _Key()
            reg.SetValueEx.side_effect = (
                lambda key, name, r, typ, val: written.update(value=val))
            self.assertTrue(startup_manager.enable_startup())

        self.assertEqual(written.get("value"), f'"{SPACED_EXE}"')

    def test_stale_registry_value_is_not_reported_as_enabled(self):
        """Eski/yanlis kayit (or. tirnaksiz) ETKIN gorunmemeli."""
        stale = SPACED_EXE   # tirnaksiz: eski surumun yazdigi bozuk deger

        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(startup_manager, "_HAS_WINREG", True), \
             mock.patch.object(startup_manager, "winreg", create=True) as reg, \
             mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", SPACED_EXE):
            reg.OpenKey.return_value = _Key()
            reg.QueryValueEx.return_value = (stale, 1)
            self.assertFalse(startup_manager.is_startup_enabled())

            reg.QueryValueEx.return_value = (f'"{SPACED_EXE}"', 1)
            self.assertTrue(startup_manager.is_startup_enabled())

    def test_startup_enabled_ignores_surrounding_whitespace_and_case(self):
        class _Key:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(startup_manager, "_HAS_WINREG", True), \
             mock.patch.object(startup_manager, "winreg", create=True) as reg, \
             mock.patch.object(startup_manager.sys, "frozen", True, create=True), \
             mock.patch.object(startup_manager.sys, "executable", SPACED_EXE):
            reg.OpenKey.return_value = _Key()
            reg.QueryValueEx.return_value = (f'  "{SPACED_EXE.upper()}"  ', 1)
            self.assertTrue(startup_manager.is_startup_enabled())


# ═══════════════════════════════════════════════════════════════════════════
#  3) UAC yukseltme hatasi sessiz kalmamali
# ═══════════════════════════════════════════════════════════════════════════
class TestElevateReportsFailure(unittest.TestCase):

    def _fake_ctypes(self, shell_execute_result):
        fake = mock.MagicMock()
        fake.windll.shell32.ShellExecuteW.return_value = shell_execute_result
        return fake

    def test_successful_elevation_returns_true(self):
        fake = self._fake_ctypes(42)          # > 32 = basarili
        with mock.patch.object(main, "ctypes", fake):
            self.assertTrue(main.elevate())
        fake.windll.shell32.ShellExecuteW.assert_called_once()
        args = fake.windll.shell32.ShellExecuteW.call_args.args
        self.assertEqual(args[1], "runas")

    def test_failed_elevation_returns_false(self):
        for code in (0, 5, 32):               # <= 32 = basarisiz (5 = ERROR_ACCESS_DENIED)
            with self.subTest(code=code):
                fake = self._fake_ctypes(code)
                with mock.patch.object(main, "ctypes", fake):
                    self.assertFalse(main.elevate())

    def test_exception_during_elevation_is_failure(self):
        fake = mock.MagicMock()
        fake.windll.shell32.ShellExecuteW.side_effect = OSError("bom")
        with mock.patch.object(main, "ctypes", fake):
            self.assertFalse(main.elevate())


# ═══════════════════════════════════════════════════════════════════════════
#  4) Gecikmeli callback icinde silinmis exception degiskeni
# ═══════════════════════════════════════════════════════════════════════════
class _UpdateStub:
    """Update delivery / download icin asgari self."""

    def __init__(self):
        self.VERSION = "3.12"
        self.scheduled = []
        self.notified = []
        self.status = []
        self.log_mgr = types.SimpleNamespace(
            write=lambda m: None, console=lambda m, level="INFO": None)
        self._alive = True
        self._busy = False
        self._update_download_active = False

    def after(self, delay, func=None):
        if func is not None:
            self.scheduled.append(func)

    def _notify(self, title, message):
        self.notified.append((title, message))

    def _st(self, text, color=None):
        self.status.append(text)

    def _ask(self, *a):
        return False

    def _update_connection_is_active(self):
        return False

    def run_scheduled(self):
        """Tk'nin sonradan calistirmasini taklit eder — burada NameError patlardi."""
        for func in list(self.scheduled):
            func()


class TestDeferredCallbacksDoNotUseDeletedException(unittest.TestCase):

    def _bind(self, stub, name):
        return getattr(gui_app.DPortApp, name).__get__(stub, gui_app.DPortApp)

    def test_update_check_failure_callback_runs_without_nameerror(self):
        stub = _UpdateStub()
        # Queue retains the exception object; UI delivery occurs after except.
        results = []
        try:
            raise gui_app.UpdateError("ag yok")
        except gui_app.UpdateError as exc:
            results.append(exc)
        self._bind(stub, "_deliver_update_check")(None, results.pop(), True)
        self.assertTrue(stub.notified, "kullaniciya hata gosterilmedi")
        self.assertIn("ag yok", stub.notified[0][1])

    def test_download_failure_callback_runs_without_nameerror(self):
        stub = _UpdateStub()
        with mock.patch.object(gui_app.secure_store, "update_staging_dir",
                               return_value=r"C:\ProgramData\DPort\updates"), \
             mock.patch.object(gui_app, "download_update",
                               side_effect=gui_app.UpdateError("indirme koptu")):
            self._bind(stub, "_download_and_launch_update")({"version": "3.12"})

        self.assertTrue(stub.scheduled, "indirme hatasinda callback planlanmadi")
        stub.run_scheduled()          # <-- duzeltme oncesi NameError
        self.assertTrue(stub.notified, "kullaniciya indirme hatasi gosterilmedi")
        self.assertIn("indirme koptu", stub.notified[0][1])


# ═══════════════════════════════════════════════════════════════════════════
#  5) Discord updater izleme mantigi
# ═══════════════════════════════════════════════════════════════════════════
class _FakeClock:
    """Gercek beklemesiz sahte saat: sleep() saati ILERLETIR."""

    def __init__(self):
        self.now = 1_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _MonitorStub:
    # Uretim sinifindaki mevcut asama->metin haritasi (stub'a aynen alinir).
    _UPD_STAGE_KEYS = gui_app.DPortApp._UPD_STAGE_KEYS

    def __init__(self):
        self._alive = True
        self.status_lines = []
        self.phases = []
        self.cfg_writes = {}
        self.console = []
        self.log_mgr = types.SimpleNamespace(
            write=lambda m: None,
            console=lambda m, level="INFO": self.console.append((level, m)))
        self.cfg = types.SimpleNamespace(
            set=lambda k, v: self.cfg_writes.__setitem__(k, v))
        self.relay_stopped = False

    def after(self, delay, func=None):
        if func is not None:
            func()

    def _st(self, text, color=None):
        self.status_lines.append(text)

    def _set_discord_update_phase(self, phase):
        self.phases.append(phase)


class TestDiscordUpdateMonitor(unittest.TestCase):

    def _run(self, statuses, stub=None, clock=None):
        """statuses: (status, msg, stage) dizisi; biten sonra son eleman tekrarlanir."""
        stub = stub or _MonitorStub()
        clock = clock or _FakeClock()
        seq = list(statuses)
        calls = {"n": 0}

        def _status(max_age_seconds=120, since_epoch=None):
            i = min(calls["n"], len(seq) - 1)
            calls["n"] += 1
            return seq[i]

        with mock.patch.object(gui_app, "time", clock), \
             mock.patch.object(gui_app, "get_discord_update_status", _status), \
             mock.patch.object(gui_app, "installed_discord_version",
                               return_value="1.0.9251"), \
             mock.patch.object(gui_app, "running_discord_version",
                               return_value="1.0.9251"), \
             mock.patch.object(gui_app, "discord_restart_required",
                               return_value=False):
            bound = gui_app.DPortApp._discord_update_result_w.__get__(
                stub, gui_app.DPortApp)
            bound(clock.time())
        return stub, clock, calls["n"]

    def test_error_then_new_progress_then_ok_is_success(self):
        """(a) error -> yeni attempt/progress -> ok  =>  BASARILI"""
        stub, _, _ = self._run([
            ("error", "ERROR [updater_client] gecici", ""),
            ("progress", "Discord update kontrol ediyor.", "checking"),
            ("progress", "Discord update indiriyor.", "downloading"),
            ("ok", "Discord update kontrolu tamamlandi.", ""),
        ])
        self.assertIn(gui_app.L["st_update_ok"], stub.status_lines)
        self.assertNotIn(gui_app.L["st_update_fail"], stub.status_lines)
        self.assertIn("discord_last_update_ok_at", stub.cfg_writes)

    def test_stale_error_does_not_cause_false_failure(self):
        """(b) error -> yeni progress (sonra sessizlik) => ESKI hata FAIL uretmemeli"""
        stub, _, _ = self._run([
            ("error", "ERROR [updater_client] gecici", ""),
            ("progress", "Discord update indiriyor.", "downloading"),
            ("unknown", "Discord updater sonucu henuz net degil.", ""),
        ])
        self.assertNotIn(gui_app.L["st_update_fail"], stub.status_lines,
                         "bayat hata yuzunden yanlis basarisizlik uretildi")

    def test_long_download_reporting_the_same_state_still_reaches_ok(self):
        """(c) GERCEKCI senaryo: uzun bir indirme boyunca updater AYNI durumu
        dondurur. 20 tur boyunca birebir ayni 'downloading' state, ardindan ok.

        Mesaj her turda degismedigi icin 'sadece degisiklikte aktiflik' olcutu
        90 sn'de idle timeout uretip basariyi KACIRIYORDU."""
        same = ("progress", "Discord update indiriyor.", "downloading")
        stub, clock, polls = self._run([same] * 20 + [("ok", "tamam", "")])
        elapsed = clock.now - 1000.0
        self.assertGreater(elapsed, 90,
                           "senaryo 90 sn'yi asmadi, test anlamsiz")
        self.assertIn(gui_app.L["st_update_ok"], stub.status_lines,
                      f"ok sonucuna ulasilamadi (elapsed={elapsed:.0f}, polls={polls})")
        self.assertNotIn(gui_app.L["st_update_fail"], stub.status_lines)

    def test_changing_progress_messages_also_reach_ok(self):
        """Mesaji degisen uzun ilerleme de basariya ulasmali."""
        active = [("progress", f"Discord modul {i} yukleniyor.", "installing")
                  for i in range(40)]          # 40 x 5 sn = 200 sn
        stub, clock, _ = self._run(active + [("ok", "tamam", "")])
        self.assertGreater(clock.now - 1000.0, 90)
        self.assertIn(gui_app.L["st_update_ok"], stub.status_lines)
        self.assertNotIn(gui_app.L["st_update_fail"], stub.status_lines)

    def test_endless_identical_progress_stops_at_hard_limit(self):
        """Sonsuza kadar ayni progress: HARD limitte cikilmali (sonsuz bekleme yok)."""
        stub, clock, _ = self._run([("progress", "Discord update indiriyor.",
                                     "downloading")])
        elapsed = clock.now - 1000.0
        self.assertGreaterEqual(elapsed, gui_app.UPD_HARD_LIMIT,
                                "ilerleme sururken erken birakildi")
        self.assertLessEqual(elapsed, gui_app.UPD_HARD_LIMIT + gui_app.UPD_POLL * 2,
                             f"hard limit asildi: {elapsed:.0f} sn")
        self.assertNotIn(gui_app.L["st_update_ok"], stub.status_lines)

    def test_motionless_updater_times_out_in_bounded_time(self):
        """(d) Hic degismeyen updater SINIRLI surede birakilmali."""
        stub, clock, polls = self._run([
            ("unknown", "Discord updater logu bulunamadi.", ""),
        ])
        elapsed = clock.now - 1000.0
        self.assertLess(elapsed, 400, f"hareketsiz updater {elapsed:.0f} sn beklendi")
        self.assertNotIn(gui_app.L["st_update_ok"], stub.status_lines)
        self.assertNotIn(gui_app.L["st_update_fail"], stub.status_lines,
                         "belirsizlik BASARISIZLIK olarak raporlanmamali")

    def test_worker_exits_immediately_when_app_closes(self):
        """(e) Uygulama kapaninca worker Tk/config'e DOKUNMADAN cikar."""
        stub = _MonitorStub()
        stub._alive = False
        stub, clock, polls = self._run(
            [("progress", "devam", "downloading")], stub=stub)
        self.assertEqual(stub.status_lines, [])
        self.assertEqual(stub.phases, [])
        self.assertEqual(stub.cfg_writes, {})
        self.assertEqual(clock.now, 1000.0, "kapaliyken bekleme yapildi")

    def test_monitor_never_closes_the_relay_or_touches_dns_hosts(self):
        """Monitor relay/hosts/DNS yolunu KAPATMAMALI."""
        import inspect
        src = inspect.getsource(gui_app.DPortApp._discord_update_result_w)
        for forbidden in ("_disable_discord_unblock", "remove_hosts_redirect",
                          "_restore_dns", "reset_to_dhcp", "set_dns"):
            self.assertNotIn(forbidden, src,
                             f"monitor '{forbidden}' cagiriyor")

    def test_total_wait_is_bounded_even_with_endless_progress(self):
        """Sonsuz ilerleme bile SONSUZ beklemeye donusmemeli."""
        stub, clock, polls = self._run([("progress", "hep ayni", "installing")])
        elapsed = clock.now - 1000.0
        self.assertLess(elapsed, 900, f"ust sinir yok gibi: {elapsed:.0f} sn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
