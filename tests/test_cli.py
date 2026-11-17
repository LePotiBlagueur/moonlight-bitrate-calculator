"""Surcharges CLI et aller-retour JSON des mesures."""

import json
import tempfile
import unittest
from pathlib import Path

from moonlight_bitrate.cli import (
    apply_overrides,
    build_parser,
    profile_from_dict,
    profile_to_dict,
)
from moonlight_bitrate.config import AppConfig
from moonlight_bitrate.iperf import PingResult, UdpTrial
from moonlight_bitrate.ladder import DirectionProfile, NetworkProfile


def sample_profile():
    trials = [
        UdpTrial(100.0, 99.8, 0.01, 0.4, 9000, 1, ok=True),
        UdpTrial(200.0, 150.0, 25.0, 8.0, 18000, 4500, ok=False, note="perte"),
    ]
    primary = DirectionProfile(
        direction="download", tcp_mbps=940.0, ceiling_mbps=987.0,
        clean_mbps=100.0, clean_trial=trials[0], trials=trials,
    )
    return NetworkProfile(primary=primary, ping=PingResult(1.2, 0.3, 0.0, 20))


class TestSerialisation(unittest.TestCase):
    def test_round_trip(self):
        cfg = AppConfig()
        payload = profile_to_dict(sample_profile(), cfg)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mesures.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            restored = profile_from_dict(json.loads(path.read_text("utf-8")))
        self.assertAlmostEqual(restored.primary.clean_mbps, 100.0)
        self.assertEqual(len(restored.primary.trials), 2)
        self.assertTrue(restored.primary.trials[0].ok)
        self.assertAlmostEqual(restored.ping.avg_ms, 1.2)

    def test_invalid_payload(self):
        with self.assertRaises(ValueError):
            profile_from_dict({})


class TestOverrides(unittest.TestCase):
    def parse(self, argv):
        return apply_overrides(AppConfig(), build_parser().parse_args(argv))

    def test_flags_reach_the_right_sections(self):
        cfg = self.parse([
            "--host", "10.0.0.5", "--user", "bob", "--codec", "av1",
            "--quality", "high", "--streams", "4", "--max-loss", "0.5",
            "--no-tcp-probe", "--yuv444",
        ])
        self.assertEqual(cfg.host.host, "10.0.0.5")
        self.assertEqual(cfg.host.user, "bob")
        self.assertEqual(cfg.model.codec, "av1")
        self.assertEqual(cfg.model.quality, "high")
        self.assertTrue(cfg.model.yuv444)
        self.assertEqual(cfg.bench.streams, 4)
        self.assertAlmostEqual(cfg.bench.max_loss_pct, 0.5)
        self.assertFalse(cfg.bench.tcp_probe)

    def test_defaults_are_untouched_without_flags(self):
        base, cfg = AppConfig(), self.parse([])
        self.assertEqual(cfg.host.host, base.host.host)
        self.assertEqual(cfg.bench.duration, base.bench.duration)
        self.assertEqual(cfg.model.resolutions, base.model.resolutions)

    def test_resolution_and_fps_replace_the_lists(self):
        cfg = self.parse([
            "--resolution", "1920x1200", "--resolution", "UW:3440x1440",
            "--fps", "60", "--fps", "165",
        ])
        self.assertEqual(cfg.model.resolutions,
                         [("1200p", 1920, 1200), ("UW", 3440, 1440)])
        self.assertEqual(cfg.model.framerates, [60, 165])


if __name__ == "__main__":
    unittest.main()
