"""Ek kollar (hedging): gercek ag yok, soketler sahte, gecikme kisaltilmis."""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))
from core import discord_unblock as d  # noqa: E402

HELLO = b'\x16\x03\x03\x00\x64' + bytes(range(100))
REPLY = b'\x16\x03\x03\x00\x02ok'
IPS = [f'192.0.2.{i}' for i in range(1, 6)]
DELAY = 0.05


class Sock:
    def __init__(self, ip, receive):
        self.ip = ip
        self.receive = receive
        self.closed = threading.Event()
        self.sent = []

    def setsockopt(self, *args): pass
    def settimeout(self, value): pass
    def sendall(self, value): self.sent.append(value)
    def recv(self, size): return self.receive(self)
    def shutdown(self, *args): self.closed.set()
    def close(self): self.closed.set()


def hang(sock):
    sock.closed.wait(2)          # yanitsiz deneme: kapatilana kadar bekler
    raise TimeoutError()


class Hedging(unittest.TestCase):
    def setUp(self):
        self.slots = threading.BoundedSemaphore(1)
        for patcher in (patch.object(d, '_TLS_RACE_SLOTS', self.slots),
                        patch.object(d, '_HEDGE_DELAY', DELAY)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.logs = []
        self.relay = d.DiscordUnblocker(log=self.logs.append)
        self.addCleanup(self.relay.stop)
        self.created = []

    def wait_workers(self):
        self.assertTrue(self.slots.acquire(timeout=3), 'TLS workers leaked')
        self.slots.release()

    def connect_with(self, receive_for_ip):
        def connect(address, *a, **k):
            sock = Sock(address[0], receive_for_ip(address[0]))
            self.created.append(sock)
            return sock
        return patch.object(d.socket, 'create_connection', side_effect=connect)

    def test_hedge_starts_on_free_ips_and_can_win(self):
        # Ana kollar 192.0.2.1 / .2'de takilir; ek kollar .3 / .4 ile baslar.
        alive = '192.0.2.4'
        def receive_for(ip):
            def receive(sock):
                if ip == alive and sock.sent == [HELLO]:
                    return REPLY
                return hang(sock)
            return receive
        with self.connect_with(receive_for):
            start = time.monotonic()
            winner, data = self.relay._open_upstream(HELLO, IPS)
            elapsed = time.monotonic() - start
            self.relay._close_socket(winner)
            self.wait_workers()
        self.assertEqual(data, REPLY)
        self.assertEqual(winner.ip, alive)
        self.assertGreaterEqual(elapsed, DELAY)
        self.assertLess(elapsed, 1)
        joined = '\n'.join(self.logs)
        self.assertIn('asama=ek_kol_basladi | ek_kol=2', joined)
        self.assertIn('ilk_hedefler=192.0.2.3,192.0.2.4', joined)
        self.assertIn('kol=3', joined)
        self.assertTrue(all(s.closed.is_set() for s in self.created if s is not winner))
        self.assertFalse(self.relay._sockets - {winner})

    def test_fast_answer_starts_no_hedge(self):
        with patch.object(d, '_HEDGE_DELAY', 0.5), \
             self.connect_with(lambda ip: (lambda s: REPLY if s.sent == [HELLO] else hang(s))):
            winner, data = self.relay._open_upstream(HELLO, IPS)
            self.relay._close_socket(winner)
            self.wait_workers()
        self.assertEqual(data, REPLY)
        self.assertNotIn('ek_kol_basladi', '\n'.join(self.logs))
        self.assertEqual(len(self.created), 2)

    def test_exhausted_lanes_do_not_start_hedges(self):
        def reset(sock):
            raise ConnectionResetError()
        with self.connect_with(lambda ip: reset):
            self.assertEqual(self.relay._open_upstream(HELLO, IPS[:2], attempts=4), (None, None))
            self.wait_workers()
        self.assertNotIn('ek_kol_basladi', '\n'.join(self.logs))

    def test_hedge_thread_failure_is_not_fatal_and_releases_capacity(self):
        original = threading.Thread.start
        def start(thread):
            if thread.name.endswith(('-2', '-3')):
                raise RuntimeError('no thread')
            original(thread)
        with self.connect_with(lambda ip: hang), \
             patch.object(d.threading.Thread, 'start', start):
            self.assertEqual(self.relay._open_upstream(HELLO, IPS, total_timeout=.3), (None, None))
            self.wait_workers()
        joined = '\n'.join(self.logs)
        self.assertEqual(joined.count('sonuc=ek_kol_baslatilamadi'), 2)
        self.assertTrue(all(s.closed.is_set() for s in self.created))

    def test_deadline_closes_hedge_sockets_too(self):
        with self.connect_with(lambda ip: hang):
            self.assertEqual(self.relay._open_upstream(HELLO, IPS, total_timeout=.3), (None, None))
            self.wait_workers()
        self.assertGreaterEqual(len(self.created), 4)   # 2 ana + 2 ek kol
        self.assertTrue(all(s.closed.is_set() for s in self.created))
        self.assertFalse(self.relay._sockets)

    def test_preferred_mode_hedges_use_preferred_strategy(self):
        for _ in range(d._PREFER_MIN_WINS):
            self.relay._count('dogrudan_basari')
        for _ in range(d._PREFER_MIN_FAILS):
            self.relay._count('parcali_timeout')
        lanes = []
        lock = threading.Lock()
        def capture(hello, ips, **kwargs):
            with lock:
                lanes.append((kwargs['_lane'], [(c[2], c[0]) for c in kwargs['_candidates']]))
            kwargs['stop_event'].wait(1)
            return None, None
        with patch.object(self.relay, '_open_upstream_serial', side_effect=capture):
            self.relay._open_upstream(HELLO, IPS, total_timeout=.3)
            self.wait_workers()
        lanes.sort()
        self.assertEqual([no for no, _ in lanes], [0, 1, 2, 3])
        self.assertTrue(all(not fragmented for _, lane in lanes for fragmented, _ip in lane))
        self.assertEqual([lane[0][1] for _, lane in lanes[2:]], ['192.0.2.3', '192.0.2.4'])


class HedgePlan(unittest.TestCase):
    def plan(self, n):
        ips = [str(i) for i in range(n)]
        lanes = [[(ip, b'F', True) for ip in ips[0::2] + ips[1::2]],
                 [(ip, b'D', False) for ip in ips[1::2] + ips[0::2]]]
        return lanes, d.DiscordUnblocker._hedge_lanes(lanes, ips)

    def test_hedges_cover_all_ips_with_parent_strategy(self):
        for n in (1, 2, 3, 5):
            with self.subTest(n=n):
                lanes, hedges = self.plan(n)
                self.assertEqual(len(hedges), 2)
                for parent, hedge in zip(lanes, hedges):
                    self.assertEqual(sorted(ip for ip, _, _ in hedge), sorted(str(i) for i in range(n)))
                    self.assertTrue(all(p == parent[0][1] and m == parent[0][2] for _, p, m in hedge))

    def test_hedges_prefer_ips_not_used_by_main_lanes(self):
        lanes, hedges = self.plan(5)
        busy = {lane[0][0] for lane in lanes}
        self.assertTrue(all(hedge[0][0] not in busy for hedge in hedges))
        self.assertNotEqual(hedges[0][0][0], hedges[1][0][0])
        lanes, hedges = self.plan(2)                     # bos IP yok: caprazlanir
        self.assertEqual([h[0][0] for h in hedges], ['1', '0'])

    def test_empty_parent_lane_gets_no_hedge(self):
        lanes = [[('0', b'F', True)], []]
        self.assertEqual(len(d.DiscordUnblocker._hedge_lanes(lanes, ['0'])), 1)


if __name__ == '__main__':
    unittest.main()
