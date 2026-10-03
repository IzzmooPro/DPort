"""Kapanis-baglanti yarisi, ozel port kullanimi, mutex ve netsh dogrulama.

Gercek DNS/hosts/gorev/443 portuna dokunulmaz: sistem cagrilari mock'lanir,
soket testleri yalniz gecici 127.0.0.1 portlarini kullanir.
"""
import importlib.util
import os
import socket
import subprocess
import sys
import types
import unittest
import uuid
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import discord_unblock, dns_manager  # noqa: E402
from gui import app as gui_app                 # noqa: E402


def _load_main():
    spec = importlib.util.spec_from_file_location(
        "dport_main_close_test", os.path.join(_APP, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _closing_app(busy=True):
    """Tk baslatmadan destroy yolunu calistirmak icin asgari DPortApp."""
    app = gui_app.DPortApp.__new__(gui_app.DPortApp)
    # Tk baslatilmadi: tkinter.__getattr__ eksik alanlarda self.tk'ye gider.
    app.tk = mock.Mock()
    app._update_checks = mock.Mock()
    app._ipc_srv = None
    app._alive = True
    app._busy = busy
    app._close_pending = False
    app._destroyed = False
    app._status_timer_id = None
    app.log_mgr = mock.Mock()
    app._stop_tray = mock.Mock()
    app.withdraw = mock.Mock()
    app.after = mock.Mock()
    app.after_cancel = mock.Mock()
    app._disable_discord_unblock = mock.Mock(return_value=True)
    app._restore_dns = mock.Mock(return_value=True)
    return app


class CloseDuringOperation(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(gui_app.ctk.CTk, "destroy")
        self.tk_destroy = patcher.start()
        self.addCleanup(patcher.stop)

    def test_close_while_busy_defers_cleanup(self):
        app = _closing_app(busy=True)
        app.destroy()
        app._disable_discord_unblock.assert_not_called()
        app._restore_dns.assert_not_called()
        self.tk_destroy.assert_not_called()
        self.assertTrue(app._close_pending)
        self.assertTrue(app._alive)
        app.withdraw.assert_called_once()
        app._stop_tray.assert_called_once()
        app.after.assert_called_once_with(gui_app.CLOSE_WAIT_MS, app._force_close)

    def test_repeated_close_requests_schedule_one_fallback(self):
        app = _closing_app(busy=True)
        app.destroy()
        app.destroy()
        self.assertEqual(app.after.call_count, 1)

    def test_operation_end_runs_deferred_cleanup_once(self):
        app = _closing_app(busy=True)
        app.destroy()
        app._finish_connection_operation()
        app._disable_discord_unblock.assert_called_once()
        app._restore_dns.assert_called_once()
        self.tk_destroy.assert_called_once()
        self.assertFalse(app._alive)
        self.assertFalse(app._busy)
        # Zorlama zamanlayicisi sonradan tetiklense de temizlik tekrarlanmaz.
        app._force_close()
        app.destroy()
        app._disable_discord_unblock.assert_called_once()
        self.tk_destroy.assert_called_once()

    def test_restore_completion_also_runs_deferred_cleanup(self):
        app = _closing_app(busy=True)
        app.destroy()
        app._finish_connection_operation(can_retry=True)
        app._disable_discord_unblock.assert_called_once()
        app._restore_dns.assert_called_once()

    def test_stuck_operation_is_force_closed(self):
        app = _closing_app(busy=True)
        app.destroy()
        app._force_close()
        app._disable_discord_unblock.assert_called_once()
        app._restore_dns.assert_called_once()
        self.tk_destroy.assert_called_once()

    def test_idle_close_is_immediate(self):
        app = _closing_app(busy=False)
        app.destroy()
        app._disable_discord_unblock.assert_called_once()
        app._restore_dns.assert_called_once()
        self.tk_destroy.assert_called_once()
        app.after.assert_not_called()

    def test_cleanup_failure_does_not_block_exit(self):
        app = _closing_app(busy=False)
        app._restore_dns.side_effect = OSError("netsh")
        app.destroy()
        self.tk_destroy.assert_called_once()

    def test_hidden_closing_window_is_not_shown_again(self):
        app = _closing_app(busy=True)
        app.deiconify = mock.Mock()
        app.destroy()
        app._show_window()
        app.deiconify.assert_not_called()


class _Worker:
    """_activate_connection_w icin asgari self; mutasyonlari kaydeder."""

    def __init__(self, close_at):
        self.close_at = close_at
        self._alive = True
        self._busy = True
        self._close_pending = False
        self.events = []
        self.log_mgr = types.SimpleNamespace(write=self.events.append,
                                             console=lambda *a, **k: None)

    def _close_if(self, step):
        if step == self.close_at:
            self._close_pending = True

    def _preflight_failsafe_target(self):
        return True

    def _preflight_discord_unblock(self):
        self._close_if("preflight")
        return True

    def _backup_dns(self, adapters):
        self.events.append("backup_dns")

    def _restore_dns(self):
        self.events.append("restore_dns")
        return True

    def _flushdns(self):
        self.events.append("flushdns")

    def _enable_discord_unblock(self):
        self.events.append("enable_unblock")
        return True

    def _disable_discord_unblock(self):
        self.events.append("disable_unblock")
        return True

    def _st(self, *_args):
        pass

    def after(self, _delay, callback):
        callback()

    def _finish_connection_operation(self, can_retry=False):
        self.events.append("finish")


class WorkerStopsWhenCloseRequested(unittest.TestCase):
    def run_worker(self, close_at):
        worker = _Worker(close_at)

        def set_dns(*_args):
            worker.events.append("set_dns")
            worker._close_if("set_dns")
            return True, "OK"

        with mock.patch.object(gui_app, "_source_dev_mode", return_value=False), \
             mock.patch.object(gui_app, "get_active_adapters",
                               return_value=[{"name": "Ethernet"}]), \
             mock.patch.object(gui_app, "set_dns", side_effect=set_dns):
            gui_app.DPortApp._activate_connection_w(worker)
        return worker.events

    def test_close_before_dns_changes_nothing(self):
        events = self.run_worker("preflight")
        for step in ("backup_dns", "set_dns", "enable_unblock"):
            self.assertNotIn(step, events)
        self.assertEqual(events[-1], "finish")

    def test_close_after_dns_does_not_open_relay_or_hosts(self):
        events = self.run_worker("set_dns")
        self.assertIn("set_dns", events)
        self.assertNotIn("enable_unblock", events)
        self.assertEqual(events[-1], "finish")

    def test_without_close_the_path_still_opens(self):
        events = self.run_worker(None)
        self.assertIn("enable_unblock", events)
        self.assertEqual(events[-1], "finish")


class ExclusivePorts(unittest.TestCase):
    def _second_bind_refused(self, port):
        other = socket.socket()
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            other.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True
        finally:
            other.close()

    @unittest.skipUnless(hasattr(socket, "SO_EXCLUSIVEADDRUSE"), "Windows")
    def test_ipc_listener_cannot_be_shared(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        srv = gui_app._exclusive_listener("127.0.0.1", port)
        try:
            self.assertTrue(self._second_bind_refused(port))
        finally:
            srv.close()
        # Kapandiktan sonra ayni port yeniden acilabilir (yeniden baslatma).
        gui_app._exclusive_listener("127.0.0.1", port).close()

    def test_relay_uses_exclusive_option_and_never_reuseaddr(self):
        options = []
        closed = []

        class FakeSocket:
            def __init__(self, *_a):
                pass

            def setsockopt(self, _level, name, _value):
                options.append(name)

            def bind(self, _addr):
                pass

            def listen(self, _n):
                pass

            def accept(self):
                raise OSError("closed")

            def close(self):
                closed.append(True)

        unblocker = discord_unblock.DiscordUnblocker()
        with mock.patch.object(discord_unblock.socket, "socket", FakeSocket):
            self.assertTrue(unblocker.start())
            unblocker.stop()
        self.assertNotIn(socket.SO_REUSEADDR, options)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.assertIn(socket.SO_EXCLUSIVEADDRUSE, options)

    def test_relay_bind_failure_closes_socket_and_reports_busy(self):
        closed = []

        class BusySocket:
            def __init__(self, *_a):
                pass

            def setsockopt(self, *_a):
                pass

            def bind(self, _addr):
                raise OSError(10013, "busy")

            def close(self):
                closed.append(True)

        unblocker = discord_unblock.DiscordUnblocker()
        with mock.patch.object(discord_unblock.socket, "socket", BusySocket):
            self.assertFalse(unblocker.start())
        self.assertEqual(closed, [True])
        self.assertFalse(unblocker.is_active())


@unittest.skipUnless(os.name == "nt", "Windows")
class SingleInstanceMutex(unittest.TestCase):
    def test_second_acquire_reports_existing_instance(self):
        main = _load_main()
        main.MUTEX_NAME = f"DPort_Test_{uuid.uuid4().hex}"
        first, h1 = main.acquire_mutex()
        second, h2 = main.acquire_mutex()
        try:
            self.assertFalse(first)
            self.assertTrue(h1)
            self.assertTrue(second)
        finally:
            import ctypes
            for handle in (h1, h2):
                if handle:
                    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))


class NetshValidation(unittest.TestCase):
    def test_all_set_dns_commands_skip_slow_validation(self):
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(dns_manager.subprocess, "run", side_effect=run):
            ok, _ = dns_manager.set_dns("Ethernet", "1.1.1.1", "1.0.0.1",
                                        "2606:4700:4700::1111", "2606:4700:4700::1001")
        self.assertTrue(ok)
        self.assertEqual(len(commands), 4)
        for command in commands:
            self.assertEqual(command[-1], "validate=no", command)


if __name__ == "__main__":
    unittest.main()
