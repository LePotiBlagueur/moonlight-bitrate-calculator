"""Sonde de MTU : dichotomie ICMP, repli par la route, réglages déduits."""

import unittest

from moonlight_bitrate import ladder, mtu
from moonlight_bitrate.config import AppConfig
from moonlight_bitrate.mtu import MtuResult, advise, discover_icmp, fits
from tests.test_ladder import SilentLogger


def fake_link(path_mtu, answers_icmp=True):
    """Sonde simulée : un paquet passe si MTU(paquet) <= path_mtu."""
    def probe(host, payload, windows, timeout=3.0):
        if not answers_icmp:
            return False
        return payload + mtu.IPV4_HEADER + mtu.ICMP_HEADER <= path_mtu
    return probe


class TestIcmpDiscovery(unittest.TestCase):
    def test_finds_the_exact_mtu(self):
        for real in (1500, 1420, 1360, 1280, 1000):
            with self.subTest(mtu=real):
                r = discover_icmp("h", windows=False, probe=fake_link(real))
                self.assertEqual(r.method, "icmp")
                self.assertEqual(r.path_mtu, real)

    def test_no_reduction_short_circuits(self):
        r = discover_icmp("h", windows=False, probe=fake_link(1500))
        self.assertEqual(r.path_mtu, 1500)
        # Un seul test suffit quand la taille maximale passe du premier coup.
        self.assertEqual(len(r.probes), 1)

    def test_silent_host_is_not_mistaken_for_a_tiny_mtu(self):
        r = discover_icmp("h", windows=False,
                          probe=fake_link(1500, answers_icmp=False))
        self.assertIsNone(r.path_mtu)
        self.assertEqual(r.method, "indisponible")
        self.assertIn("ICMP", r.note)

    def test_search_converges_quickly(self):
        r = discover_icmp("h", windows=False, probe=fake_link(1360))
        self.assertLess(len(r.probes), 12)


class TestEffectiveMtu(unittest.TestCase):
    def test_lowest_constraint_wins(self):
        self.assertEqual(MtuResult("h", path_mtu=1400, route_mtu=1360)
                         .effective_mtu, 1360)
        self.assertEqual(MtuResult("h", path_mtu=1300, route_mtu=1360)
                         .effective_mtu, 1300)

    def test_single_source(self):
        self.assertEqual(MtuResult("h", route_mtu=1360).effective_mtu, 1360)
        self.assertIsNone(MtuResult("h").effective_mtu)


class TestAdvice(unittest.TestCase):
    def test_payload_math(self):
        self.assertEqual(advise(1500).datagram_len, 1472)   # 1500 - 20 - 8
        self.assertEqual(advise(1420).datagram_len, 1392)
        self.assertEqual(advise(1360).datagram_len, 1332)

    def test_inside_the_tunnel_the_mtu_is_the_tunnel_mtu(self):
        self.assertEqual(advise(1360, through_tunnel=True).wireguard_mtu, 1360)

    def test_underlay_subtracts_wireguard_overhead(self):
        self.assertEqual(advise(1500, through_tunnel=False).wireguard_mtu,
                         1500 - mtu.WG_OVERHEAD_V4)

    def test_ipv6_overheads(self):
        self.assertEqual(advise(1500, ipv6=True).datagram_len, 1452)
        self.assertEqual(advise(1500, through_tunnel=False, ipv6=True)
                         .wireguard_mtu, 1500 - mtu.WG_OVERHEAD_V6)

    def test_advice_always_fits(self):
        for value in (1500, 1420, 1360, 1280, 576):
            self.assertTrue(fits(advise(value).datagram_len, value))

    def test_fits_boundary(self):
        self.assertTrue(fits(1332, 1360))
        self.assertTrue(fits(1333, 1361))
        self.assertFalse(fits(1333, 1360))
        self.assertFalse(fits(1380, 1360))


class TestLadderIntegration(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig()
        self.log = SilentLogger()
        self._orig = ladder.mtu_mod.discover

    def tearDown(self):
        ladder.mtu_mod.discover = self._orig

    def _stub(self, result):
        ladder.mtu_mod.discover = lambda *a, **k: result

    def test_autofit_clamps_an_oversized_datagram(self):
        self._stub(MtuResult("h", route_mtu=1360, method="route"))
        self.cfg.bench.datagram_len = 1380
        found, method = ladder.check_mtu(self.cfg, self.log)
        self.assertEqual(found, 1360)
        self.assertEqual(method, "route")
        self.assertEqual(self.cfg.bench.datagram_len, 1332)

    def test_autofit_disabled_leaves_the_value_alone(self):
        self._stub(MtuResult("h", route_mtu=1360, method="route"))
        self.cfg.bench.datagram_len = 1380
        self.cfg.bench.mtu_autofit = False
        ladder.check_mtu(self.cfg, self.log)
        self.assertEqual(self.cfg.bench.datagram_len, 1380)

    def test_a_fitting_value_is_never_touched(self):
        self._stub(MtuResult("h", route_mtu=1500, method="route"))
        self.cfg.bench.datagram_len = 1400
        ladder.check_mtu(self.cfg, self.log)
        self.assertEqual(self.cfg.bench.datagram_len, 1400)

    def test_unknown_mtu_is_not_fatal(self):
        self._stub(MtuResult("h"))
        self.cfg.bench.datagram_len = 1400
        found, _ = ladder.check_mtu(self.cfg, self.log)
        self.assertIsNone(found)
        self.assertEqual(self.cfg.bench.datagram_len, 1400)

    def test_check_can_be_disabled(self):
        self._stub(MtuResult("h", route_mtu=100, method="route"))
        self.cfg.bench.mtu_check = False
        self.cfg.bench.datagram_len = 1400
        found, _ = ladder.check_mtu(self.cfg, self.log)
        self.assertIsNone(found)
        self.assertEqual(self.cfg.bench.datagram_len, 1400)


if __name__ == "__main__":
    unittest.main()


class TestSunshinePacketsize(unittest.TestCase):
    """`packetsize` = MTU - 28 - 16, d'après la documentation de Sunshine."""

    def test_formula(self):
        for value, expected in [(1500, 1456), (1420, 1376), (1392, 1348),
                                (1360, 1316), (1280, 1236)]:
            with self.subTest(mtu=value):
                self.assertEqual(advise(value).sunshine_packetsize, expected)

    def test_sixteen_bytes_below_the_datagram_payload(self):
        a = advise(1360)
        self.assertEqual(a.datagram_len - a.sunshine_packetsize,
                         mtu.SUNSHINE_HEADER)

    def test_stays_inside_the_mtu(self):
        for value in (1500, 1420, 1360, 1280, 576):
            a = advise(value)
            self.assertTrue(fits(a.sunshine_packetsize, value))
