"""DoH fallback and DNS-before-preflight regression tests.

These tests never modify the real DNS, hosts file, registry, or processes.
"""
import io
import json
import os
import ssl
import sys
import unittest
import urllib.error
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import discord_unblock  # noqa: E402
from gui import app as gui_app  # noqa: E402


class _JsonResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _answer(*ips):
    return {
        "Status": 0,
        "Answer": [{"type": 1, "data": ip} for ip in ips],
    }


class TestStrictDohFallback(unittest.TestCase):
    def test_certificate_failure_falls_back_to_next_strict_https_provider(self):
        cert_error = ssl.SSLCertVerificationError(
            1, "certificate verify failed: unable to get local issuer certificate"
        )
        calls = []

        def _urlopen(req, timeout):
            calls.append((req.full_url, timeout))
            if len(calls) == 1:
                raise urllib.error.URLError(cert_error)
            return _JsonResponse(_answer("162.159.136.232"))

        logs = []
        with mock.patch.object(discord_unblock.urllib.request, "urlopen", _urlopen):
            ips = discord_unblock.doh_resolve("discord.com", timeout=3, log=logs.append)

        self.assertEqual(ips, ["162.159.136.232"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].startswith("https://1.1.1.1/dns-query?"))
        self.assertTrue(calls[1][0].startswith("https://cloudflare-dns.com/dns-query?"))
        self.assertTrue(all(timeout == 3 for _, timeout in calls))
        self.assertTrue(any("sertifika" in line.lower() for line in logs))

    def test_invalid_or_non_public_answers_do_not_reach_the_relay(self):
        replies = [
            _JsonResponse(_answer("127.0.0.1", "10.0.0.5", "not-an-ip")),
            _JsonResponse({"Status": 2, "Answer": []}),
            _JsonResponse(_answer("162.159.128.233", "162.159.128.233")),
        ]

        with mock.patch.object(
            discord_unblock.urllib.request, "urlopen", side_effect=replies
        ) as urlopen:
            ips = discord_unblock.doh_resolve("discord.com")

        self.assertEqual(ips, ["162.159.128.233"])
        self.assertEqual(urlopen.call_count, 3)

    def test_all_providers_fail_closed_with_bounded_diagnostics(self):
        failure = urllib.error.URLError(
            ssl.SSLCertVerificationError(1, "certificate verify failed")
        )
        logs = []
        with mock.patch.object(
            discord_unblock.urllib.request,
            "urlopen",
            side_effect=[failure, failure, failure],
        ):
            with self.assertRaises(discord_unblock.DohResolutionError) as raised:
                discord_unblock.doh_resolve("discord.com", log=logs.append)

        self.assertIn("3/3", str(raised.exception))
        self.assertEqual(len(logs), 3)

    def test_source_contains_no_tls_verification_bypass(self):
        with open(discord_unblock.__file__, "r", encoding="utf-8") as source_file:
            source = source_file.read()
        forbidden = (
            "_create_unverified_context",
            "CERT_NONE",
            "check_hostname = False",
            "http://",
        )
        for marker in forbidden:
            self.assertNotIn(marker, source)


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


class _Button:
    def configure(self, **_kwargs):
        pass


class _PreflightFailureApp:
    def __init__(self):
        self.log_mgr = _Log()
        self.btn_open = _Button()
        self._busy = True
        self._connecting = True
        self.statuses = []

    def _st(self, text, color):
        self.statuses.append((text, color))

    def _preflight_discord_unblock(self):
        return False

    def after(self, _delay, callback):
        callback()

    def _refresh_status_async(self):
        pass


class TestDohPreflightOrdering(unittest.TestCase):
    def test_failed_preflight_does_not_touch_dns_hosts_or_discord(self):
        fake = _PreflightFailureApp()
        forbidden = mock.Mock(side_effect=AssertionError("system mutation attempted"))

        with mock.patch.object(gui_app, "is_discord_running", return_value=False), \
             mock.patch.object(gui_app, "get_active_adapters", forbidden), \
             mock.patch.object(gui_app, "set_dns", forbidden), \
             mock.patch.object(gui_app, "add_hosts_redirect", forbidden), \
             mock.patch.object(gui_app, "launch_discord", forbidden):
            gui_app.DPortApp._open_discord_w(fake)

        forbidden.assert_not_called()
        self.assertFalse(fake._busy)
        self.assertFalse(fake._connecting)


if __name__ == "__main__":
    unittest.main()
