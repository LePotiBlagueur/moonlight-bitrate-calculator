"""Extraction des métriques UDP, quelle que soit la forme du JSON iperf3."""

import unittest

from moonlight_bitrate.iperf import IperfError, _udp_summary


class TestUdpSummary(unittest.TestCase):
    def test_modern_sum_block(self):
        data = {"end": {"sum": {
            "bits_per_second": 450_000_000.0, "jitter_ms": 0.42,
            "lost_packets": 12, "packets": 40_000, "lost_percent": 0.03,
        }}}
        s = _udp_summary(data)
        self.assertEqual(s["packets"], 40_000)
        self.assertAlmostEqual(s["lost_percent"], 0.03)

    def test_falls_back_to_sum_received(self):
        data = {"end": {
            "sum": {"packets": 0},
            "sum_received": {"bits_per_second": 1.0, "jitter_ms": 1.5,
                             "lost_packets": 1, "packets": 100,
                             "lost_percent": 1.0},
        }}
        self.assertEqual(_udp_summary(data)["packets"], 100)

    def test_aggregates_parallel_streams(self):
        data = {"end": {"streams": [
            {"udp": {"bits_per_second": 1e8, "jitter_ms": 0.5,
                     "lost_packets": 5, "packets": 1000}},
            {"udp": {"bits_per_second": 1e8, "jitter_ms": 1.5,
                     "lost_packets": 15, "packets": 1000}},
        ]}}
        s = _udp_summary(data)
        self.assertAlmostEqual(s["bits_per_second"], 2e8)
        self.assertEqual(s["packets"], 2000)
        self.assertEqual(s["lost_packets"], 20)
        # On retient la pire gigue, pas la moyenne.
        self.assertAlmostEqual(s["jitter_ms"], 1.5)
        self.assertAlmostEqual(s["lost_percent"], 1.0)

    def test_missing_udp_stats_raises(self):
        with self.assertRaises(IperfError):
            _udp_summary({"end": {"streams": [{"sender": {}}]}})


if __name__ == "__main__":
    unittest.main()
