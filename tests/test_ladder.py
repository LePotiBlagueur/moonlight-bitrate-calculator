"""La recherche par paliers doit retrouver la capacité d'un lien simulé."""

import unittest

from moonlight_bitrate import ladder
from moonlight_bitrate.config import AppConfig
from moonlight_bitrate.iperf import TcpResult, UdpTrial
from moonlight_bitrate.report import Logger, Palette


class SilentLogger(Logger):
    def __init__(self):
        super().__init__(Palette(), False)

    def section(self, text): pass
    def step(self, text): pass
    def ok(self, text): pass
    def warn(self, text): pass
    def error(self, text): pass
    def trial(self, t): pass


def make_link(capacity_mbps, sender_cap_mbps=float("inf")):
    """Lien simulé : propre sous la capacité, perdant au-dessus."""
    def _run_udp(iperf, host, port, target, duration, omit, streams,
                 length, reverse):
        sent = min(target, sender_cap_mbps)
        delivered = min(sent, capacity_mbps)
        loss = 100.0 * (sent - delivered) / sent if sent else 0.0
        jitter = 0.3 + (2.0 if loss > 0 else 0.0)
        packets = int(duration * sent * 1e6 / (8 * 1400))
        return UdpTrial(
            target_mbps=target, achieved_mbps=delivered, loss_pct=loss,
            jitter_ms=jitter, packets=packets,
            lost_packets=int(packets * loss / 100),
        )
    return _run_udp


class TestLadder(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig()
        self.cfg.bench.ping_probe = False
        # Pas d'E/S réseau dans les tests : la sonde MTU a sa propre suite.
        self.cfg.bench.mtu_check = False
        self.cfg.bench.retry_on_fail = False
        self.log = SilentLogger()
        self._orig_udp = ladder.run_udp
        self._orig_tcp = ladder.run_tcp

    def tearDown(self):
        ladder.run_udp = self._orig_udp
        ladder.run_tcp = self._orig_tcp

    def _measure(self, capacity, tcp_mbps=None, sender_cap=float("inf")):
        ladder.run_udp = make_link(capacity, sender_cap)
        ladder.run_tcp = lambda *a, **k: TcpResult(mbps=tcp_mbps or capacity)
        return ladder.measure(self.cfg, self.log).primary

    def test_converges_near_true_capacity(self):
        for capacity in (95.0, 300.0, 940.0):
            with self.subTest(capacity=capacity):
                p = self._measure(capacity, tcp_mbps=capacity * 1.02)
                self.assertLessEqual(p.clean_mbps, capacity + 1e-6)
                self.assertGreater(p.clean_mbps, capacity * 0.85)

    def test_never_reports_more_than_the_link_allows(self):
        p = self._measure(120.0, tcp_mbps=940.0)
        self.assertLessEqual(p.clean_mbps, 120.0 + 1e-6)

    def test_detects_sender_limit(self):
        # Le réseau tient 900 Mbps mais l'émetteur plafonne à 200.
        p = self._measure(900.0, tcp_mbps=940.0, sender_cap=200.0)
        self.assertTrue(p.sender_limited)
        self.assertGreater(p.clean_mbps, 150.0)
        self.assertLessEqual(p.clean_mbps, 210.0)

    def test_flags_unreached_ceiling(self):
        # Le lien encaisse tout : aucun palier ne doit échouer.
        p = self._measure(10_000.0, tcp_mbps=940.0)
        self.assertTrue(p.ceiling_not_reached)
        self.assertFalse(p.sender_limited)

    def test_clean_trial_is_the_highest_passing_one(self):
        p = self._measure(300.0, tcp_mbps=310.0)
        passing = [t.target_mbps for t in p.trials if t.ok]
        self.assertTrue(passing)
        self.assertAlmostEqual(p.clean_trial.target_mbps, max(passing))


if __name__ == "__main__":
    unittest.main()
