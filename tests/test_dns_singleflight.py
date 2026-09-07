import concurrent.futures
import os
import sys
import threading
import socket
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))
from core import discord_unblock as d


class SingleFlightTests(unittest.TestCase):
    def test_burst_shares_one_result_or_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                waiting, release = threading.Event(), threading.Event()
                lock = threading.Lock()
                waiters = [0]
                def log(line):
                    if 'ortak_sorgu_bekleniyor' in line:
                        with lock:
                            waiters[0] += 1
                            if waiters[0] == 7:
                                waiting.set()
                def resolve(*args, **kwargs):
                    release.wait(3)
                    if fail:
                        raise d.DohResolutionError('test')
                    return ['162.159.130.233']
                relay = d.DiscordUnblocker(log=log)
                with patch.object(d, 'doh_resolve', side_effect=resolve) as lookup:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                        futures = [pool.submit(relay._resolve, 'cdn.discordapp.com') for _ in range(8)]
                        try:
                            self.assertTrue(waiting.wait(2))
                        finally:
                            release.set()
                        for future in futures:
                            if fail:
                                with self.assertRaises(d.DohResolutionError):
                                    future.result(2)
                            else:
                                self.assertEqual(future.result(2), ['162.159.130.233'])
                    self.assertEqual(lookup.call_count, 1)
                self.assertEqual(relay._dns_pending, {})
                if fail:
                    with patch.object(d, 'doh_resolve', return_value=['1.1.1.1']):
                        self.assertEqual(relay._resolve('cdn.discordapp.com'), ['1.1.1.1'])

    def test_cancelled_resolution_does_not_repopulate_cache(self):
        relay = d.DiscordUnblocker()
        def resolve(*args, **kwargs):
            relay.stop()
            return ['1.1.1.1']
        with patch.object(d, 'doh_resolve', side_effect=resolve):
            with self.assertRaises(d.DohResolutionError):
                relay._resolve('discord.com')
        self.assertEqual(relay._ip_cache, {})
        self.assertEqual(relay._dns_pending, {})

    def test_capacity_wait_is_bounded_and_cancellable(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        with patch.object(d, '_DOH_SLOTS', semaphore), patch.object(d, '_doh_resolve_blocking') as worker:
            with self.assertRaises(d.DohResolutionError):
                d.doh_resolve('discord.com', total_timeout=0.02)
            worker.assert_not_called()
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(d.DohResolutionError):
                d.doh_resolve('discord.com', cancel=cancel)
        semaphore.release()

    def test_transfer_error_identifies_direction_operation_and_id(self):
        logs = []
        relay = d.DiscordUnblocker(log=logs.append)
        source, target = Mock(), Mock()
        source.recv.return_value = b'encrypted'
        target.sendall.side_effect = ConnectionAbortedError(10053, 'private')
        relay._pump(source, target, host='discord.com', direction='sunucu_istemci', connection_id=42)
        output = '\n'.join(logs)
        self.assertIn('id=42', output)
        self.assertIn('yon=sunucu_istemci | islem=send', output)
        self.assertNotIn('private', output)
        self.assertNotIn('encrypted', output)

    def test_transfer_close_reasons(self):
        for mode, expected in [('eof', 'karsi_uc_eof'), ('timeout', 'zaman_asimi'),
                               ('stop', 'dport_durdurdu'), ('closed', 'diger_yon_kapandi')]:
            with self.subTest(mode=mode):
                logs = []
                relay = d.DiscordUnblocker(log=logs.append)
                source, target = Mock(), Mock()
                stop, closed = threading.Event(), threading.Event()
                source.recv.return_value = b''
                if mode == 'timeout':
                    source.recv.side_effect = TimeoutError()
                if mode == 'stop':
                    stop.set()
                if mode == 'closed':
                    closed.set()
                result = relay._pump(source, target, stop, closed)
                self.assertEqual(result, expected)
                self.assertIn('neden=' + expected, '\n'.join(logs))

    def test_wait_observation_is_bounded_and_does_not_abort_transfer(self):
        logs = []
        relay = d.DiscordUnblocker(log=logs.append)
        source, target = Mock(), Mock()
        source.recv.side_effect = [b'secret_payload', b'']
        with patch.object(d.select, 'select', side_effect=[([], [], []), ([], [], []),
                ([source], [], []), ([], [], []), ([source], [], [])]), \
                patch.object(d.time, 'monotonic', side_effect=[0, 31, 32, 33, 65, 66]):
            reason = relay._pump(source, target, host='discord.com', connection_id=7,
                                 observe_wait=True)
        self.assertEqual(reason, 'karsi_uc_eof')
        target.sendall.assert_called_once_with(b'secret_payload')
        output = '\n'.join(logs)
        self.assertEqual(output.count('sonuc=veri_bekleniyor'), 1)
        self.assertIn('ariza_kaniti=False', output)
        self.assertNotIn('secret_payload', output)

    def test_observer_stop_does_not_touch_socket(self):
        relay = d.DiscordUnblocker()
        stop = threading.Event()
        stop.set()
        source, target = Mock(), Mock()
        result = relay._pump(source, target, stop_event=stop, observe_wait=True)
        self.assertEqual(result, 'dport_durdurdu')
        source.recv.assert_not_called()

    def test_observer_preserves_real_socket_bytes_and_eof(self):
        source, writer = socket.socketpair()
        target, reader = socket.socketpair()
        try:
            for sock in (source, writer, target, reader):
                sock.settimeout(2)
            writer.sendall(b'opaque TLS bytes')
            writer.shutdown(socket.SHUT_WR)
            relay = d.DiscordUnblocker()
            self.assertEqual(relay._pump(source, target, observe_wait=True), 'karsi_uc_eof')
            self.assertEqual(reader.recv(100), b'opaque TLS bytes')
            self.assertEqual(reader.recv(100), b'')
        finally:
            for sock in (source, writer, target, reader):
                sock.close()
