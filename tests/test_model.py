"""Le modèle doit reproduire les valeurs par défaut de Moonlight."""

import unittest

from moonlight_bitrate.config import ModelConfig
from moonlight_bitrate.model import (
    SLIDER_MAX_MBPS,
    best_per_resolution,
    build_matrix,
    evaluate_mode,
    framerate_factor,
    link_need,
    max_video_for_budget,
    moonlight_default_mbps,
    needs_unlock,
    reference_is_clamped,
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

    def test_above_4k_is_clamped_like_moonlight(self):
        """La sentinelle du tableau amont renvoie le dernier facteur (40)."""
        for w, h in [(3840, 2400), (5120, 2160), (5120, 2880)]:
            with self.subTest(res=f"{w}x{h}"):
                self.assertEqual(moonlight_default_mbps(w, h, 60),
                                 moonlight_default_mbps(3840, 2160, 60))
                self.assertTrue(reference_is_clamped(w, h))
        self.assertFalse(reference_is_clamped(3840, 2160))
        self.assertFalse(reference_is_clamped(5120, 1440))

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


class TestPerResolutionAdvice(unittest.TestCase):
    """Une recommandation par taille d'écran, jamais une seule ligne globale."""

    def setUp(self):
        self.m = ModelConfig()

    def test_one_entry_per_resolution_in_order(self):
        pairs = best_per_resolution(build_matrix(300.0, self.m))
        self.assertEqual([key for key, _ in pairs],
                         [tuple(r) for r in self.m.resolutions])

    def test_picks_the_highest_feasible_framerate(self):
        # Budget large : chaque taille doit atteindre la fréquence maximale.
        top = max(self.m.framerates)
        for _, mode in best_per_resolution(build_matrix(10_000.0, self.m)):
            self.assertIsNotNone(mode)
            self.assertEqual(mode.fps, top)

    def test_small_budget_keeps_the_rows_but_empties_them(self):
        pairs = best_per_resolution(build_matrix(12.0, self.m))
        self.assertEqual(len(pairs), len(self.m.resolutions))
        self.assertIsNone(pairs[-1][1])        # 5K hors budget
        self.assertIsNotNone(pairs[0][1])      # 720p tient encore

    def test_requested_framerates_are_covered(self):
        for fps in (60, 144, 175):
            self.assertIn(fps, self.m.framerates)


class TestSliderCeiling(unittest.TestCase):
    """Le curseur de Moonlight s'arrête à 150 Mbps sans déblocage."""

    def test_threshold(self):
        self.assertFalse(needs_unlock(SLIDER_MAX_MBPS))
        self.assertTrue(needs_unlock(SLIDER_MAX_MBPS + 0.1))

    def test_4k_at_max_quality_needs_the_unlock(self):
        from moonlight_bitrate.model import evaluate_mode

        mode = evaluate_mode("4K", 3840, 2160, 175, 10_000.0,
                             ModelConfig(quality="max"))
        self.assertTrue(needs_unlock(mode.advised_mbps))
        # Le même mode en qualité par défaut reste saisissable.
        default = evaluate_mode("4K", 3840, 2160, 175, 10_000.0, ModelConfig())
        self.assertFalse(needs_unlock(default.advised_mbps))
