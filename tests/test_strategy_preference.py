"""Oturum ici yontem tercihi: gercek ag/Discord trafigi yok, soketler sahte."""
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


def seed(relay, **counts):
    for key, value in counts.items():
        for _ in range(value):
            relay._count(key)


class StrategyPreference(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.relay = d.DiscordUnblocker(log=self.logs.append)
        self.addCleanup(self.relay.stop)

    def plan(self, win=False):
        """Bir yarisin kol planini (yontem, IP sirasi) ag olmadan yakalar.
        win=False: hic kazanan yok (yaris basarisiz sayilir)."""
        lanes = []
        lock = threading.Lock()
        class Winner:
            def shutdown(self, *a): pass
            def close(self): pass
        def capture(hello, ips, **kwargs):
            with lock:
                lanes.append([(c[2], c[0]) for c in kwargs['_candidates']])
            return (Winner(), REPLY) if win else (None, None)
        with patch.object(self.relay, '_open_upstream_serial', side_effect=capture):
            self.relay._open_upstream(HELLO, IPS)
        started = [line for line in self.logs if 'paralel_basladi' in line][-1]
        mode = started.split('mod=')[1].split(' |')[0]
        return mode, sorted(lanes)

    def test_without_data_both_strategies_race_as_before(self):
        mode, lanes = self.plan()
        self.assertEqual(mode, 'karma')
        self.assertEqual({lane[0][0] for lane in lanes}, {True, False})

    def test_direct_only_network_moves_both_lanes_to_direct(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        mode, lanes = self.plan()
        self.assertEqual(mode, 'dogrudan')
        self.assertTrue(all(not fragmented for lane in lanes for fragmented, _ in lane))
        first_ips = [lane[0][1] for lane in lanes]
        self.assertEqual(len(set(first_ips)), 2, 'kollar ayni IP ile basladi')
        for lane in lanes:
            self.assertEqual(sorted(ip for _, ip in lane[:len(IPS)]), sorted(IPS))
        self.assertIn('STRATEJI | tercih=dogrudan', '\n'.join(self.logs))

    def test_fragment_only_network_moves_both_lanes_to_fragment(self):
        seed(self.relay, parcali_basari=3, dogrudan_reset=3)
        mode, lanes = self.plan()
        self.assertEqual(mode, 'parcali')
        self.assertTrue(all(fragmented for lane in lanes for fragmented, _ in lane))

    def test_thresholds_and_mixed_success_keep_both_strategies(self):
        wins, fails = d._PREFER_MIN_WINS, d._PREFER_MIN_FAILS
        cases = (
            dict(dogrudan_basari=wins - 1, parcali_timeout=fails),        # az kazanma
            dict(dogrudan_basari=wins, parcali_timeout=fails - 1),        # az kesin hata
            dict(dogrudan_basari=wins, parcali_iptal_bekliyordu=9),       # iptal hata sayilmaz
            dict(dogrudan_basari=5, parcali_basari=1, parcali_timeout=9),  # ikisi de calisti
        )
        for counts in cases:
            with self.subTest(counts=counts):
                self.relay._reset_session_stats()
                seed(self.relay, **counts)
                self.assertEqual(self.plan()[0], 'karma')

    def cancel(self, strategy, waited):
        self.relay._log_cancelled(1, 'discord.com', 0, 5, strategy, '192.0.2.1',
                                  time.monotonic() - waited)

    def test_long_unanswered_wait_counts_as_failure(self):
        seed(self.relay, dogrudan_basari=d._PREFER_MIN_WINS)
        for _ in range(d._PREFER_MIN_FAILS):
            self.cancel('parcali', d._NO_REPLY_EVIDENCE + .2)
        self.assertIn('hata_sayildi=True', self.logs[-1])
        self.assertEqual(self.plan()[0], 'dogrudan')
        self.assertIn(f'parcali[yanitsiz_iptal={d._PREFER_MIN_FAILS}]', self.relay._summary_text())

    def test_short_cancelled_wait_is_not_failure(self):
        seed(self.relay, dogrudan_basari=d._PREFER_MIN_WINS)
        for _ in range(5):
            self.cancel('parcali', .05)
        self.assertIn('hata_sayildi=False', self.logs[-1])
        self.assertEqual(self.plan()[0], 'karma')

    def test_long_wait_alone_cannot_create_preference_without_rival_wins(self):
        # Yavas agda iki yontem de uzun bekleyip iptal edilse bile, hicbiri
        # kazanmadan tercih olusmaz.
        for strategy in ('parcali', 'dogrudan'):
            for _ in range(3):
                self.cancel(strategy, d._NO_REPLY_EVIDENCE + .2)
        self.assertEqual(self.plan()[0], 'karma')

    def test_every_tenth_race_reprobes_both_strategies(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        modes = [self.plan(win=True)[0] for _ in range(d._REPROBE_EVERY)]
        self.assertEqual(modes[:-1], ['dogrudan'] * (d._REPROBE_EVERY - 1))
        self.assertEqual(modes[-1], 'karma')
        started = [line for line in self.logs if 'paralel_basladi' in line]
        self.assertIn('mod_nedeni=yeniden_sinama', started[-1])
        self.assertIn('mod_nedeni=tercih', started[0])

    def test_failed_preferred_race_forces_one_mixed_race(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        self.assertEqual(self.plan()[0], 'dogrudan')   # yakalayici kazanan vermez
        self.assertEqual(self.plan()[0], 'karma')
        self.assertEqual(self.plan()[0], 'dogrudan')

    def test_stopped_relay_does_not_force_mixed(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        stop = threading.Event()
        stop.set()
        self.relay._open_upstream(HELLO, IPS, stop_event=stop, total_timeout=.05)
        self.assertFalse(self.relay._force_mixed)

    def test_strategy_log_only_when_preference_changes(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        for _ in range(3):
            self.plan()
        self.assertEqual(sum(line.startswith('STRATEJI') for line in self.logs), 1)
        seed(self.relay, parcali_basari=1)
        self.plan()
        self.assertIn('STRATEJI | tercih=yok', self.logs[[i for i, line in enumerate(self.logs)
                                                          if line.startswith('STRATEJI')][-1]])

    def test_relay_start_forgets_previous_session(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        self.plan()
        class FakeServer:
            def __init__(self, *a): pass
            def setsockopt(self, *a): pass
            def bind(self, *a): pass
            def listen(self, *a): pass
            def accept(self): raise OSError()
            def close(self): pass
        with patch.object(d.socket, 'socket', FakeServer):
            self.assertTrue(self.relay.start())
        self.assertEqual(self.relay._race_count, 0)
        self.assertIsNone(self.relay._last_preference)
        self.assertEqual(self.plan()[0], 'karma')

    def test_summary_reports_preference_and_race_counts(self):
        seed(self.relay, dogrudan_basari=3, parcali_timeout=3)
        self.plan()
        summary = self.relay._summary_text()
        self.assertIn('tercih=dogrudan', summary)
        self.assertIn('yaris_tercihli=1', summary)
        self.assertIn('yaris_karma=0', summary)


class _Sock:
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


class PreferredDirectBehaviour(unittest.TestCase):
    def test_two_direct_attempts_on_different_ips_avoid_dead_ip_wait(self):
        """Parcali hic calismayan agda: ilk IP yanitsiz, ikincisi calisiyor."""
        slots = threading.BoundedSemaphore(1)
        relay = d.DiscordUnblocker()
        seed(relay, dogrudan_basari=3, parcali_timeout=3)
        dead, alive = '192.0.2.1', '192.0.2.2'
        def connect(address, *a, **k):
            ip = address[0]
            def receive(sock):
                if ip == alive and sock.sent == [HELLO]:
                    return REPLY
                sock.closed.wait(2)
                raise TimeoutError()
            return _Sock(ip, receive)
        with patch.object(d, '_TLS_RACE_SLOTS', slots), \
             patch.object(d.socket, 'create_connection', side_effect=connect):
            start = time.monotonic()
            winner, data = relay._open_upstream(HELLO, [dead, alive])
            elapsed = time.monotonic() - start
            relay._close_socket(winner)
            self.assertTrue(slots.acquire(timeout=3), 'TLS workers leaked')
            slots.release()
        relay.stop()
        self.assertEqual(data, REPLY)
        self.assertEqual(winner.ip, alive)
        self.assertEqual(winner.sent, [HELLO])   # parcali degil, dogrudan
        self.assertLess(elapsed, 1)


if __name__ == '__main__':
    unittest.main()
