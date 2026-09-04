"""Real ClientHello regression cases; no Discord or system network mutation."""
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))
from core import discord_unblock as d
from core.log_manager import LogManager


def hello(host):
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = ssl.create_default_context().wrap_bio(
        incoming, outgoing, server_side=False, server_hostname=host)
    try:
        client.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return outgoing.read()


class RealTlsTests(unittest.TestCase):
    def test_all_allowed_hosts_parse_and_route_to_own_target(self):
        for host in d.ALLOWED_HOSTS:
            with self.subTest(host=host):
                data = hello(host)
                self.assertEqual(d.parse_sni(data), host)
                relay = d.DiscordUnblocker()
                relay._resolve = Mock(return_value=['162.159.135.232'])
                relay._open_upstream = Mock(return_value=(None, None))
                with patch.object(d, '_recv_full_client_hello', return_value=data):
                    relay._handle(Mock())
                self.assertEqual(relay._resolve.call_args.args[0], host)

    def test_fragmented_records_and_one_byte_tcp_reads(self):
        data = d.fragment_client_hello(hello('gateway.discord.gg'))
        self.assertEqual(d.parse_sni(data), 'gateway.discord.gg')
        chunks = iter(bytes([b]) for b in data)
        sock = Mock()
        sock.recv.side_effect = lambda count: next(chunks, b'')
        self.assertEqual(d._recv_full_client_hello(sock), data)

    def test_truncated_and_invalid_names_never_resolve(self):
        valid = hello('discord.com')
        for data in (valid[:-1], b'', hello(None), hello('example.org'),
                     valid.replace(b'discord.com', b'discord\ncom')):
            relay = d.DiscordUnblocker()
            relay._resolve = Mock()
            with patch.object(d, '_recv_full_client_hello', return_value=data):
                relay._handle(Mock())
            relay._resolve.assert_not_called()

    def test_truncated_record_raises_without_waiting_forever(self):
        data = bytearray(hello('discord.com')[:-1])
        sock = Mock()
        def read(n):
            chunk = bytes(data[:n])
            del data[:n]
            return chunk
        sock.recv.side_effect = read
        with self.assertRaises(ValueError):
            d._recv_full_client_hello(sock)

    def test_third_ip_fragmented_strategy_is_reached(self):
        data = hello('discord.com')
        ips = ['162.159.135.232', '162.159.136.232', '162.159.137.232',
               '162.159.138.232', '162.159.139.232']
        def connect(address, **kwargs):
            sock = Mock()
            sent = []
            sock.sendall.side_effect = sent.append
            sock.recv.side_effect = lambda _: b'\x16\x03\x03' if (
                address[0] == ips[2] and sent[0] != data) else b''
            return sock
        relay = d.DiscordUnblocker()
        with patch.object(d.socket, 'create_connection', side_effect=connect):
            server, _ = relay._open_upstream(data, ips)
        self.assertIsNotNone(server)
        relay.stop()

    def test_total_tls_budget_and_cancellation_prevent_connect(self):
        relay = d.DiscordUnblocker()
        with patch.object(d.socket, 'create_connection') as connect:
            self.assertEqual(relay._open_upstream(hello('discord.com'), ['1.1.1.1'],
                                                 total_timeout=0), (None, None))
            relay.stop()
            self.assertEqual(relay._open_upstream(hello('discord.com'), ['1.1.1.1']),
                             (None, None))
            connect.assert_not_called()

    def test_stop_closes_existing_socket_and_old_generation(self):
        relay = d.DiscordUnblocker()
        old = relay._stop_event
        left, right = socket.socketpair()
        self.addCleanup(right.close)
        self.assertTrue(relay._track(left, old))
        relay.stop()
        right.settimeout(1)
        self.assertEqual(right.recv(1), b'')
        relay._stop_event = threading.Event()
        late = Mock()
        self.assertFalse(relay._track(late, old))
        late.close.assert_called_once()

    def test_stop_during_connect_discards_late_socket(self):
        relay = d.DiscordUnblocker()
        sock = Mock()
        def connect(*args, **kwargs):
            relay.stop()
            return sock
        with patch.object(d.socket, 'create_connection', side_effect=connect):
            self.assertEqual(relay._open_upstream(hello('discord.com'), ['1.1.1.1']),
                             (None, None))
        sock.sendall.assert_not_called()
        sock.close.assert_called_once()

    def test_tls_deadline_stops_retry_after_blocked_attempt(self):
        relay = d.DiscordUnblocker()
        clock = [10.0]
        def connect(*args, **kwargs):
            clock[0] += 25
            raise TimeoutError()
        with patch.object(d.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(d.socket, 'create_connection', side_effect=connect) as call:
            self.assertEqual(relay._open_upstream(hello('discord.com'), ['1.1.1.1']),
                             (None, None))
        self.assertEqual(call.call_count, 1)

    def test_pump_reset_is_logged_without_exception_contents(self):
        logs = []
        relay = d.DiscordUnblocker(log=logs.append)
        left, right = Mock(), Mock()
        left.recv.side_effect = ConnectionResetError('private contents')
        relay._pump(left, right)
        self.assertIn('hata=reset', '\n'.join(logs))
        self.assertNotIn('private contents', '\n'.join(logs))

    def test_expected_socket_errors_after_stop_or_tunnel_close_are_not_failures(self):
        for closing_relay in (True, False):
            logs = []
            relay = d.DiscordUnblocker(log=logs.append)
            old_event = relay._stop_event
            closed = threading.Event()
            if closing_relay:
                relay.stop()
                relay._stop_event = threading.Event()  # restarted session
            else:
                closed.set()
            left, right = Mock(), Mock()
            left.recv.side_effect = OSError(10038, 'closed socket')
            relay._pump(left, right, old_event, closed, 'discord.com')
            self.assertFalse(any('aktarim_hatasi' in line for line in logs))

    def test_doh_deadline_does_not_poison_shared_stop_event(self):
        release, done, cancel = threading.Event(), threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            try:
                release.wait(2)
                return ['1.1.1.1']
            finally:
                done.set()
        with patch.object(d, '_doh_resolve_blocking', side_effect=blocked):
            try:
                start = time.monotonic()
                with self.assertRaises(d.DohResolutionError):
                    d.doh_resolve('discord.com', total_timeout=0.05, cancel=cancel)
                self.assertLess(time.monotonic() - start, 1)
                self.assertFalse(cancel.is_set())
            finally:
                release.set()
                self.assertTrue(done.wait(1))

    def test_console_warnings_persist_even_without_console(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'dport.log')
            log = LogManager(path, mirror_console=False)
            log.console('hosts temizlenemedi', level='WARN')
            self.assertIn('WARN | hosts temizlenemedi', ''.join(log.read_lines()))


if __name__ == '__main__':
    unittest.main()
