"""Privacy-safe persistent diagnostics for ISP/DPI failures."""
import os
import socket
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from core import discord_unblock  # noqa: E402


def _hello():
    payload = bytes(range(100))
    return b"\x16\x03\x03" + len(payload).to_bytes(2, "big") + payload


class _FakeSocket:
    def __init__(self, result):
        self.result = result

    def setsockopt(self, *_args):
        pass

    def settimeout(self, *_args):
        pass

    def sendall(self, _data):
        pass

    def recv(self, _size):
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def close(self):
        pass


class DiagnosticLoggingTests(unittest.TestCase):
    def test_tls_attempt_records_host_strategy_result_target_and_duration(self):
        logs = []
        results = [
            _FakeSocket(socket.timeout("private operating system text")),
            _FakeSocket(b"\x16\x03\x03\x00\x02ok"),
        ]
        relay = discord_unblock.DiscordUnblocker(log=logs.append)
        with mock.patch.object(
            discord_unblock.socket, "create_connection", side_effect=results
        ):
            server, first = relay._open_upstream(
                _hello(), ["192.0.2.1"], attempts=2, host="discord.com"
            )

        self.assertIsNotNone(server)
        self.assertTrue(first.startswith(b"\x16"))
        joined = "\n".join(logs)
        self.assertIn("host=discord.com", joined)
        self.assertIn("yol=parcali", joined)
        self.assertIn("sonuc=timeout", joined)
        self.assertIn("yol=dogrudan", joined)
        self.assertIn("sonuc=ilk_tls_yaniti", joined)
        self.assertIn("hedef=192.0.2.1:443", joined)
        self.assertIn("sure_ms=", joined)
        self.assertNotIn("private operating system text", joined)

    def test_all_failed_attempts_end_with_bounded_summary(self):
        logs = []
        relay = discord_unblock.DiscordUnblocker(log=logs.append)
        with mock.patch.object(
            discord_unblock.socket,
            "create_connection",
            side_effect=ConnectionResetError(10054, "sensitive free text"),
        ), mock.patch.object(discord_unblock.time, "sleep", return_value=None):
            server, first = relay._open_upstream(
                _hello(), ["192.0.2.1"], attempts=3, host="gateway.discord.gg"
            )

        self.assertIsNone(server)
        self.assertIsNone(first)
        self.assertEqual(sum("sonuc=reset" in line for line in logs), 3)
        self.assertIn("tum_denemeler_bitti=3", logs[-1])
        self.assertNotIn("sensitive free text", "\n".join(logs))

    def test_gui_persists_session_and_relay_diagnostics(self):
        with open(os.path.join(APP, "gui", "app.py"), encoding="utf-8") as source_file:
            source = source_file.read()
        self.assertIn('log=lambda m: self.log_mgr.write(f"unblock: {m}")', source)
        self.assertIn('f"SESSION | {L[\'title\']} v{self.VERSION} baslatildi | "', source)


if __name__ == "__main__":
    unittest.main()
