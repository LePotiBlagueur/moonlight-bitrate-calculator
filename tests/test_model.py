"""Le modèle doit reproduire les valeurs par défaut de Moonlight."""

import unittest

from moonlight_bitrate.config import ModelConfig
from moonlight_bitrate.model import (
    build_matrix,
    evaluate_mode,
    framerate_factor,
    link_need,
    max_video_for_budget,
    moonlight_default_mbps,
)


class TestMoonlightDefaults(unittest.TestCase):
    # Valeurs publiées par Moonlight (StreamingPreferences::getDefaultBitrate).
    CASES = [
        (1280, 720, 30, 5),
        (1280, 720, 60, 10),
        (1920, 1080, 30, 10),
        (1920, 1080, 60, 20),
        (1920, 1080, 120, 28),
        (2560, 1440, 60, 40),
        (2560, 1440, 120, 57),
        (3840, 2160, 60, 80),
        (3840, 2160, 120, 113),
    ]

    def test_reference_values(self):
        for w, h, fps, expected in self.CASES:
            with self.subTest(res=f"{w}x{h}@{fps}"):
                self.assertEqual(round(moonlight_default_mbps(w, h, fps)), expected)

    def test_interpolation_between_anchors(self):
        # 1920x1200 est entre 1080p (10) et 1440p (20).
        factor = moonlight_default_mbps(1920, 1200, 30)
        self.assertGreater(factor, 10.0)
        self.assertLess(factor, 20.0)

    def test_above_4k_extrapolates(self):
        self.assertGreater(moonlight_default_mbps(5120, 2880, 60),
                           moonlight_default_mbps(3840, 2160, 60))

    def test_framerate_is_sublinear_above_60(self):
        self.assertAlmostEqual(framerate_factor(60), 2.0)
        self.assertLess(framerate_factor(120), 2 * framerate_factor(60))

    def test_yuv444_doubles(self):
        self.assertAlmostEqual(
            moonlight_default_mbps(1920, 1080, 60, yuv444=True),
            2 * moonlight_default_mbps(1920, 1080, 60),
        )


class TestBudget(unittest.TestCase):
    def test_link_need_and_inverse_are_consistent(self):
        m = ModelConfig(fec_overhead=0.2, audio_mbps=0.5)
        need = link_need(50.0, m)
        self.assertAlmostEqual(need, 60.5)
        self.assertAlmostEqual(max_video_for_budget(need, m), 50.0)

    def test_advised_never_exceeds_budget(self):
        m = ModelConfig(codec="h264", quality="max")
        for budget in (15.0, 40.0, 500.0):
            for mode in build_matrix(budget, m):
                with self.subTest(budget=budget, mode=mode.label):
                    self.assertLessEqual(link_need(mode.advised_mbps, m),
                                         budget + 1e-6)

    def test_verdicts(self):
        m = ModelConfig(codec="h264", quality="balanced", fec_overhead=0.2,
                        audio_mbps=0.5, marginal_tolerance=0.15)
        # 1080p60 => 20 Mbps vidéo => 24.5 Mbps réseau.
        self.assertEqual(evaluate_mode("x", 1920, 1080, 60, 30.0, m).verdict, "ok")
        self.assertEqual(evaluate_mode("x", 1920, 1080, 60, 23.0, m).verdict, "marginal")
        self.assertEqual(evaluate_mode("x", 1920, 1080, 60, 10.0, m).verdict, "no")

    def test_codec_efficiency_lowers_requirement(self):
        base = ModelConfig(codec="h264")
        av1 = ModelConfig(codec="av1")
        self.assertLess(
            evaluate_mode("x", 2560, 1440, 120, 200.0, av1).video_mbps,
            evaluate_mode("x", 2560, 1440, 120, 200.0, base).video_mbps,
        )


if __name__ == "__main__":
    unittest.main()
