"""Bounded race tests: no Discord traffic or system DNS/hosts mutations."""
import os
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))
from core import discord_unblock as d

HELLO = b'\x16\x03\x03\x00\x64' + bytes(range(100))
REPLY = b'\x16\x03\x03\x00\x02ok'


class Sock:
    def __init__(self, receive):
        self.receive = receive
        self.closed = threading.Event()
        self.sent = []

    def setsockopt(self, *args): pass
    def settimeout(self, value): pass
    def sendall(self, value): self.sent.append(value)
    def recv(self, size): return self.receive(self)
    def shutdown(self, *args): self.closed.set()
    def close(self): self.closed.set()


class TlsRaceTests(unittest.TestCase):
    def setUp(self):
        self.slots = threading.BoundedSemaphore(1)
        self.patch = patch.object(d, '_TLS_RACE_SLOTS', self.slots)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.logs = []
        self.relay = d.DiscordUnblocker(log=self.logs.append)
        self.addCleanup(self.relay.stop)
        self.addCleanup(self.wait_workers)

    def wait_workers(self):
        self.assertTrue(self.slots.acquire(timeout=2), 'TLS workers leaked')
        self.slots.release()

    def test_direct_finishes_without_waiting_for_fragment_timeout(self):
        entered = threading.Event()
        created = []
        def receive(sock):
            if sock.sent == [HELLO]:
                self.assertTrue(entered.wait(1))
                return REPLY
            entered.set()
            self.assertTrue(sock.closed.wait(2), 'losing recv was not cancelled')
            raise OSError()
        def connect(*args, **kwargs):
            sock = Sock(receive)
            created.append(sock)
            return sock
        with patch.object(d.socket, 'create_connection', side_effect=connect):
            start = time.monotonic()
            winner, data = self.relay._open_upstream(HELLO, ['192.0.2.1'], attempts=2)
            elapsed = time.monotonic() - start
            self.wait_workers()
        self.assertLess(elapsed, 1)
        self.assertEqual(data, REPLY)
        self.assertEqual(winner.sent, [HELLO])
        self.assertFalse(winner.closed.is_set())
        self.assertEqual(self.relay._sockets, {winner})
        self.assertTrue(all(s.closed.is_set() for s in created if s is not winner))
        self.assertIn('tam_oturum_dogrulanmadi=True', '\n'.join(self.logs))

    def test_simultaneous_success_keeps_exactly_one_socket(self):
        barrier = threading.Barrier(2)
        created = []
        def receive(sock):
            barrier.wait(timeout=1)
            return REPLY
        def connect(*a, **k):
            sock = Sock(receive)
            created.append(sock)
            return sock
        with patch.object(d.socket, 'create_connection', side_effect=connect):
            winner, data = self.relay._open_upstream(HELLO, ['192.0.2.1'], attempts=2)
            self.wait_workers()
        self.assertEqual(data, REPLY)
        self.assertEqual(sum(not s.closed.is_set() for s in created), 1)
        self.assertEqual(self.relay._sockets, {winner})

    def test_cancel_and_deadline_close_both_pending_receives(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                entered = threading.Barrier(2)
                cancel = threading.Event()
                created = []
                def receive(sock):
                    entered.wait(timeout=1)
                    if stop:
                        cancel.set()
                    sock.closed.wait(1)
                    raise OSError()
                def connect(*a, **k):
                    sock = Sock(receive)
                    created.append(sock)
                    return sock
                with patch.object(d.socket, 'create_connection', side_effect=connect):
                    self.assertEqual(self.relay._open_upstream(
                        HELLO, ['192.0.2.1'], attempts=2, stop_event=cancel,
                        total_timeout=.15), (None, None))
                    self.wait_workers()
                self.assertTrue(all(s.closed.is_set() for s in created))
                self.assertFalse(self.relay._sockets)

    def test_late_tcp_socket_is_closed_without_sending(self):
        release = threading.Event()
        entered = threading.Event()
        late = Sock(lambda s: REPLY)
        def connect(*a, **k):
            entered.set()
            release.wait(1)
            return late
        with patch.object(d.socket, 'create_connection', side_effect=connect):
            self.assertEqual(self.relay._open_upstream(
                HELLO, ['192.0.2.1'], attempts=1, total_timeout=.05), (None, None))
            self.assertTrue(entered.is_set())
            # A pending connect still owns capacity, even after caller returned.
            self.assertFalse(self.slots.acquire(blocking=False))
            release.set()
            self.wait_workers()
        self.assertTrue(late.closed.is_set())
        self.assertFalse(late.sent)

    def test_capacity_wait_honors_budget_without_spawning(self):
        self.slots.acquire()
        try:
            with patch.object(d.socket, 'create_connection') as connect:
                self.assertEqual(self.relay._open_upstream(
                    HELLO, ['192.0.2.1'], total_timeout=.05), (None, None))
                connect.assert_not_called()
        finally:
            self.slots.release()

    def test_thread_start_failure_releases_capacity(self):
        with patch.object(d.threading.Thread, 'start', side_effect=RuntimeError('start')):
            with self.assertRaises(RuntimeError):
                self.relay._open_upstream(HELLO, ['192.0.2.1'])
        self.assertFalse(self.relay._sockets)

    def test_second_worker_start_failure_cancels_first(self):
        original = threading.Thread.start
        starts = [0]
        entered = threading.Event()
        sock = Sock(lambda s: (s.closed.wait(1), REPLY)[1])
        def connect(*a, **k):
            entered.set()
            return sock
        def start(thread):
            starts[0] += 1
            if starts[0] == 2:
                self.assertTrue(entered.wait(1))
                raise RuntimeError('second worker')
            original(thread)
        with patch.object(d.socket, 'create_connection', side_effect=connect), \
             patch.object(d.threading.Thread, 'start', start):
            with self.assertRaises(RuntimeError):
                self.relay._open_upstream(HELLO, ['192.0.2.1'])
            self.wait_workers()
        self.assertTrue(sock.closed.is_set())
        self.assertFalse(self.relay._sockets)

    def test_controlled_before_after_wait_reduction(self):
        # A synthetic 150ms fragmented timeout, not a live ISP benchmark.
        def receive(sock):
            if sock.sent == [HELLO]:
                return REPLY
            sock.closed.wait(.15)
            raise TimeoutError()
        timings = []
        with patch.object(d.socket, 'create_connection',
                          side_effect=lambda *a, **k: Sock(receive)):
            for method in (self.relay._open_upstream_serial, self.relay._open_upstream):
                start = time.monotonic()
                winner, data = method(HELLO, ['192.0.2.1', '192.0.2.2'], attempts=4)
                timings.append(time.monotonic() - start)
                self.assertEqual(data, REPLY)
                self.relay._close_socket(winner)
                self.wait_workers()
        self.assertGreaterEqual(timings[0], .3)
        self.assertLess(timings[1], timings[0] / 2 + .05)
        print(f'Controlled TLS wait: serial={timings[0]*1000:.1f}ms race={timings[1]*1000:.1f}ms')

    def test_real_socket_loser_gets_eof_and_winner_preserves_bytes(self):
        peers = []
        clients = []
        handlers = []
        observed = []
        fragment_seen = threading.Event()
        errors = []
        def connect(*a, **k):
            client, peer = socket.socketpair()
            peers.append(peer)
            clients.append(client)
            def serve():
                try:
                    peer.settimeout(2)
                    request = peer.recv(65536)
                    observed.append(request)
                    if request == HELLO:
                        if not fragment_seen.wait(1):
                            raise AssertionError('fragment worker did not send')
                        peer.sendall(REPLY)
                    else:
                        fragment_seen.set()
                        observed.append(peer.recv(1))
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=serve)
            handlers.append(thread)
            thread.start()
            return client
        # socketpair has no TCP_NODELAY; use a wrapper only for that option.
        class Wrapper:
            def __init__(self, sock): self.sock = sock
            def setsockopt(self, *args): pass
            def __getattr__(self, key): return getattr(self.sock, key)
        try:
            with patch.object(d.socket, 'create_connection', side_effect=lambda *a, **k: Wrapper(connect())):
                winner, data = self.relay._open_upstream(HELLO, ['192.0.2.1'], attempts=2)
                self.wait_workers()
            self.assertEqual(data, REPLY)
            for thread in handlers:
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertIn(HELLO, observed)
            self.assertIn(b'', observed)
            self.assertFalse(errors)
            self.assertFalse(winner.sock._closed)
        finally:
            for sock in clients + peers:
                sock.close()


if __name__ == '__main__':
    unittest.main()
