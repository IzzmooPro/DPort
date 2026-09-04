"""DoH fallback and DNS-before-preflight regression tests.

These tests never modify the real DNS, hosts file, registry, or processes.
"""
import io
import json
import os
import socket
import ssl
import sys
import unittest
import urllib.error
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core import discord_manager, discord_unblock  # noqa: E402
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


class _FakeUpstream:
    def __init__(self, ip, direct_hello, direct_success_ip):
        self.ip = ip
        self.direct_hello = direct_hello
        self.direct_success_ip = direct_success_ip
        self.sent = b""
        self.closed = False

    def setsockopt(self, *_args):
        pass

    def settimeout(self, *_args):
        pass

    def sendall(self, data):
        self.sent = data

    def recv(self, _size):
        if self.ip == self.direct_success_ip and self.sent == self.direct_hello:
            return b"\x16\x03\x03\x00\x02ok"
        raise socket.timeout("TLS strategy did not answer")

    def close(self):
        self.closed = True


class TestRelayTlsStrategyFallback(unittest.TestCase):
    def test_direct_tls_tries_alternate_ip_after_fragmented_tls_stalls(self):
        payload = bytes(range(100))
        hello = b"\x16\x03\x03" + len(payload).to_bytes(2, "big") + payload
        ips = ["104.18.32.47", "172.64.155.209"]
        calls = []

        def _connect(address, timeout):
            self.assertEqual(timeout, 8)
            calls.append(address[0])
            return _FakeUpstream(address[0], hello, ips[1])

        relay = discord_unblock.DiscordUnblocker()
        with mock.patch.object(
            discord_unblock.socket, "create_connection", side_effect=_connect
        ), mock.patch.object(discord_unblock.time, "sleep", return_value=None):
            server, first = relay._open_upstream(hello, ips, attempts=4)

        self.assertIsNotNone(server)
        self.assertEqual(first, b"\x16\x03\x03\x00\x02ok")
        self.assertEqual(calls, [ips[0], ips[1], ips[0], ips[1]])

    def test_fragmented_tls_remains_the_first_strategy(self):
        payload = bytes(range(100))
        hello = b"\x16\x03\x03" + len(payload).to_bytes(2, "big") + payload
        fragmented = discord_unblock.fragment_client_hello(hello)
        sent = []

        class _FragmentSuccess(_FakeUpstream):
            def sendall(self, data):
                sent.append(data)
                self.sent = data

            def recv(self, _size):
                return b"\x16\x03\x03\x00\x02ok"

        with mock.patch.object(
            discord_unblock.socket,
            "create_connection",
            return_value=_FragmentSuccess("192.0.2.1", hello, ""),
        ):
            server, _ = discord_unblock.DiscordUnblocker()._open_upstream(
                hello, ["192.0.2.1"]
            )

        self.assertIsNotNone(server)
        self.assertEqual(sent, [fragmented])

    def test_fragmented_sweep_is_bounded_so_direct_tls_starts_early(self):
        """DoH cok IP dondurdugunde dogrudan TLS'e gecis gecikmemeli.

        Parcali ClientHello yanitlanmadiginda her IP recv zaman asimina kadar
        bekletir. Sinir olmasaydi 5 IP'lik bir yanitta dogrudan TLS ancak 5
        zaman asimindan sonra denenirdi (canli olcumde ~20 sn)."""
        payload = bytes(range(100))
        hello = b"\x16\x03\x03" + len(payload).to_bytes(2, "big") + payload
        ips = [f"162.159.13{i}.232" for i in range(5)]
        order = []

        def _connect(address, timeout):
            order.append(address[0])
            return _FakeUpstream(address[0], hello, ips[0])

        relay = discord_unblock.DiscordUnblocker()
        with mock.patch.object(
            discord_unblock.socket, "create_connection", side_effect=_connect
        ), mock.patch.object(discord_unblock.time, "sleep", return_value=None):
            server, _ = relay._open_upstream(hello, ips)

        self.assertIsNotNone(server)
        # Parcali tarama sinirli: dogrudan TLS, sinir kadar denemeden sonra baslar.
        cap = discord_unblock._FRAG_SWEEP_IPS
        self.assertEqual(order[:cap], ips[:cap], "parcali tarama ilk sirada degil")
        self.assertEqual(
            len(order), cap + 1,
            "dogrudan TLS parcali taramanin hemen ardindan denenmeliydi")

    def test_empty_ip_list_fails_safely_without_connecting(self):
        """DoH hicbir IP dondurmediyse hicbir baglanti denenmeden vazgecilir."""
        hello = b"\x16\x03\x03\x00\x01a"
        with mock.patch.object(
            discord_unblock.socket, "create_connection"
        ) as connect:
            server, first = discord_unblock.DiscordUnblocker()._open_upstream(
                hello, []
            )

        self.assertIsNone(server)
        self.assertIsNone(first)
        connect.assert_not_called()

    def test_non_positive_attempts_fails_safely_without_connecting(self):
        """Deneme butcesi sifir/negatifse de guvenli sekilde basarisiz olunur."""
        hello = b"\x16\x03\x03\x00\x01a"
        for attempts in (0, -1):
            with self.subTest(attempts=attempts):
                with mock.patch.object(
                    discord_unblock.socket, "create_connection"
                ) as connect:
                    server, first = discord_unblock.DiscordUnblocker()._open_upstream(
                        hello, ["192.0.2.1"], attempts=attempts
                    )

                self.assertIsNone(server)
                self.assertIsNone(first)
                connect.assert_not_called()


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

    def _preflight_failsafe_target(self):
        # Bu test DoH on-kontrolunun SIRASINI dogrular; kurtarma hedefi
        # on-kontrolu (ondan once calisir) burada bilerek gecirilir.
        return True

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

        with mock.patch.object(gui_app, "get_active_adapters", forbidden), \
             mock.patch.object(gui_app, "set_dns", forbidden), \
             mock.patch.object(gui_app, "add_hosts_redirect", forbidden), \
             mock.patch.object(discord_manager, "launch_discord", forbidden):
            gui_app.DPortApp._activate_connection_w(fake)

        forbidden.assert_not_called()
        self.assertFalse(fake._busy)
        self.assertFalse(fake._connecting)


if __name__ == "__main__":
    unittest.main()
