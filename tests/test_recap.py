"""Construction du récapitulatif et rendu dans chaque format."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from moonlight_bitrate.config import AppConfig
from moonlight_bitrate.recap import (
    RENDERERS,
    best_table,
    SECTIONS,
    build_recap,
    codec_table,
    matrix_table,
    quality_table,
    render_text,
)
from moonlight_bitrate.recap_cli import apply_overrides, build_parser, main
from moonlight_bitrate.recap_cli import resolve_source
from moonlight_bitrate.report import SLIDER_NOTE, Logger, Palette
from tests.test_cli import sample_profile


class SilentLogger(Logger):
    def __init__(self):
        super().__init__(Palette(), False)

    def section(self, text): pass
    def step(self, text): pass
    def ok(self, text): pass
    def warn(self, text): pass
    def error(self, text): pass
    def trial(self, t): pass


def recap_for(budget=200.0, cfg=None, sections=None, plain=False):
    cfg = cfg or AppConfig()
    return build_recap(cfg, budget, budget / cfg.model.safety_margin, None,
                       sections or ["matrix", "codecs", "quality", "best"],
                       "test", plain=plain)


class TestTables(unittest.TestCase):
    def test_matrix_shape_matches_config(self):
        cfg = AppConfig()
        table = matrix_table(200.0, cfg.model, plain=False)
        self.assertEqual(len(table.rows), len(cfg.model.resolutions))
        self.assertEqual(len(table.headers), 2 + len(cfg.model.framerates))

    def test_plain_mode_drops_the_symbols(self):
        plain = matrix_table(200.0, AppConfig().model, plain=True)
        for row in plain.rows:
            for cell in row[2:]:
                self.assertNotIn("✓", cell)
                self.assertNotIn("~", cell)

    def test_codec_table_ranks_av1_at_least_as_high(self):
        # À budget serré, AV1 doit tenir au moins autant de fps que H.264.
        table = codec_table(35.0, AppConfig().model)
        for row in table.rows:
            h264, av1 = row[2], row[4]
            if h264 == "—":
                continue
            self.assertNotEqual(av1, "—", f"AV1 devrait tenir si H.264 tient : {row}")
            self.assertGreaterEqual(int(av1.split()[0]), int(h264.split()[0]))

    def test_relaxing_quality_unlocks_bigger_modes(self):
        # Les lignes vont de « max » à « saver » : à budget constant, plus le
        # préréglage est léger, plus le mode atteignable est gros.
        rows = quality_table(60.0, AppConfig().model).rows
        loads = []
        for row in rows:
            if row[2] == "—":
                continue
            w, h = (int(part) for part in row[2].split("x"))
            loads.append(w * h * int(row[3]))
        self.assertTrue(loads)
        self.assertEqual(loads, sorted(loads))

    def test_quality_raises_the_bitrate_of_a_fixed_mode(self):
        from moonlight_bitrate.config import ModelConfig
        from moonlight_bitrate.model import evaluate_mode

        previous = 0.0
        for preset in ("saver", "balanced", "high", "max"):
            mode = evaluate_mode("x", 1920, 1080, 60, 10_000.0,
                                 ModelConfig(quality=preset))
            self.assertGreater(mode.advised_mbps, previous)
            previous = mode.advised_mbps

    def test_best_table_has_one_row_per_screen_size(self):
        cfg = AppConfig()
        table = best_table(300.0, cfg.model)
        self.assertEqual(len(table.rows), len(cfg.model.resolutions))
        self.assertEqual([row[1] for row in table.rows],
                         [f"{w}x{h}" for _, w, h in cfg.model.resolutions])

    def test_above_4k_rows_are_flagged_as_a_floor(self):
        table = best_table(300.0, AppConfig().model)
        flagged = [row[0] for row in table.rows if row[0].endswith(" *")]
        self.assertEqual(flagged, ["4K 16:10 *", "5K2K UW *", "5K *"])
        self.assertTrue(any("plafonne" in note for note in table.notes))

    def test_cells_above_the_slider_are_flagged(self):
        from moonlight_bitrate.config import ModelConfig

        model = ModelConfig(quality="max")
        table = matrix_table(10_000.0, model, plain=False)
        flagged = [cell for row in table.rows for cell in row[2:] if "†" in cell]
        self.assertTrue(flagged, "4K @ 175 en qualité max dépasse 150 Mbps")
        self.assertIn(SLIDER_NOTE, table.notes)
        # Au débit par défaut, rien ne dépasse : pas de note parasite.
        quiet = matrix_table(10_000.0, ModelConfig(), plain=False)
        self.assertFalse([c for row in quiet.rows for c in row[2:] if "†" in c])
        self.assertNotIn(SLIDER_NOTE, quiet.notes)

    def test_plain_mode_drops_the_slider_marker(self):
        from moonlight_bitrate.config import ModelConfig

        table = matrix_table(10_000.0, ModelConfig(quality="max"), plain=True)
        self.assertFalse([c for row in table.rows for c in row[2:] if "†" in c])

    def test_tight_budget_marks_everything_impossible(self):
        table = matrix_table(2.0, AppConfig().model, plain=False)
        self.assertTrue(all("✗" in cell for row in table.rows for cell in row[2:]))


class TestRenderers(unittest.TestCase):
    def test_every_format_produces_output(self):
        recap = recap_for()
        text = render_text(recap, Palette())
        self.assertIn("Récapitulatif Moonlight", text)
        for name, renderer in RENDERERS.items():
            with self.subTest(format=name):
                out = renderer(recap)
                self.assertGreater(len(out), 200)
                self.assertIn("1920x1080", out)

    def test_html_is_wellformed_enough(self):
        out = RENDERERS["html"](recap_for())
        self.assertTrue(out.startswith("<!doctype html>"))
        self.assertEqual(out.count("<table>"), out.count("</table>"))
        self.assertEqual(out.count("<tr>"), out.count("</tr>"))
        self.assertIn("prefers-color-scheme", out)

    def test_json_is_parsable(self):
        data = json.loads(RENDERERS["json"](recap_for()))
        self.assertIn("meta", data)
        self.assertTrue(data["tables"])

    def test_csv_rows_have_a_constant_width_per_table(self):
        out = RENDERERS["csv"](recap_for(sections=["matrix"]))
        self.assertIn("Résolution;Définition", out)

    def test_network_section_appears_only_with_a_profile(self):
        with_profile = build_recap(AppConfig(), 200.0, 235.0, sample_profile(),
                                   list(SECTIONS), "test")
        titles = [t.title for t in with_profile.tables]
        self.assertIn("Lien mesuré", titles)
        self.assertNotIn("Lien mesuré", [t.title for t in recap_for().tables])


class TestRecapCli(unittest.TestCase):
    def parse(self, argv):
        return build_parser().parse_args(argv)

    def test_sections_parsing(self):
        self.assertEqual(self.parse(["--sections", "all"]).sections, list(SECTIONS))
        self.assertEqual(self.parse(["--sections", "matrix,best"]).sections,
                         ["matrix", "best"])
        with self.assertRaises(SystemExit):
            self.parse(["--sections", "nope"])

    def test_sources_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parse(["-b", "100", "--load", "x.json"])

    def test_bandwidth_applies_the_safety_margin(self):
        cfg = apply_overrides(AppConfig(), self.parse(["-b", "100"]))
        capacity, budget, profile, _ = resolve_source(
            cfg, self.parse(["-b", "100"]), SilentLogger())
        self.assertAlmostEqual(capacity, 100.0)
        self.assertAlmostEqual(budget, 85.0)
        self.assertIsNone(profile)

    def test_budget_bypasses_the_safety_margin(self):
        args = self.parse(["--budget", "85"])
        _, budget, _, _ = resolve_source(AppConfig(), args, SilentLogger())
        self.assertAlmostEqual(budget, 85.0)

    def test_no_source_is_an_error(self):
        with self.assertRaises(ValueError):
            resolve_source(AppConfig(), self.parse([]), SilentLogger())

    def test_negative_bandwidth_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_source(AppConfig(), self.parse(["-b", "-5"]), SilentLogger())

    def test_end_to_end_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recap.md"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["-b", "300", "--format", "markdown", "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("| 1920x1080 |", out.read_text("utf-8"))

    def test_end_to_end_from_saved_measurements(self):
        from moonlight_bitrate.cli import profile_to_dict

        with tempfile.TemporaryDirectory() as tmp:
            measures = Path(tmp) / "m.json"
            measures.write_text(
                json.dumps(profile_to_dict(sample_profile(), AppConfig())),
                encoding="utf-8")
            out = Path(tmp) / "recap.html"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--load", str(measures), "--format", "html",
                             "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("Lien mesuré", out.read_text("utf-8"))

    def test_missing_source_exits_with_code_2(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--no-color"]), 2)


if __name__ == "__main__":
    unittest.main()


class TestNetworkTableEdgeCases(unittest.TestCase):
    def test_absent_clean_trial_shows_a_dash(self):
        """Émetteur bridé : aucun palier propre, pas de 0.00 trompeur."""
        from moonlight_bitrate.ladder import DirectionProfile, NetworkProfile
        from moonlight_bitrate.recap import network_table

        profile = NetworkProfile(primary=DirectionProfile(
            direction="download", tcp_mbps=871.4, clean_mbps=200.0,
            clean_trial=None, sender_limited=True))
        row = network_table(profile).rows[0]
        self.assertEqual(row[2], "200.0")
        self.assertEqual(row[3], "—")
        self.assertEqual(row[4], "—")
        self.assertTrue(any("plafonné" in n for n in network_table(profile).notes))
