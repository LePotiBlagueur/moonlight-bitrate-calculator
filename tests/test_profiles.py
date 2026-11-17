"""Profils de configuration : surcouche LAN / VPN."""

import tempfile
import unittest
from pathlib import Path

from moonlight_bitrate.cli import apply_overrides, build_parser
from moonlight_bitrate.config import AppConfig, list_profiles, load_config

SAMPLE = """
[host]
host = "192.168.1.10"
user = "kwak"

[bench]
duration = 8
datagram_len = 1400
max_jitter_ms = 3.0

[model]
codec = "hevc"
safety_margin = 0.85

[profiles.lan.bench]
max_jitter_ms = 2.0

[profiles.vpn.host]
host = "10.66.119.1"

[profiles.vpn.bench]
datagram_len = 1380
duration = 10

[profiles.vpn.model]
safety_margin = 0.75
"""


class ProfileTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "config.toml"
        self.path.write_text(SAMPLE, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)


class TestLoading(ProfileTestCase):
    def test_listing(self):
        self.assertEqual(list_profiles(self.path), ["lan", "vpn"])
        self.assertEqual(list_profiles(None), [])

    def test_base_is_untouched_without_profile(self):
        cfg = load_config(self.path)
        self.assertIsNone(cfg.active_profile)
        self.assertEqual(cfg.bench.datagram_len, 1400)
        self.assertAlmostEqual(cfg.bench.max_jitter_ms, 3.0)

    def test_profile_overlays_only_its_own_keys(self):
        cfg = load_config(self.path, "vpn")
        self.assertEqual(cfg.active_profile, "vpn")
        # Surchargé par le profil.
        self.assertEqual(cfg.host.host, "10.66.119.1")
        self.assertEqual(cfg.bench.datagram_len, 1380)
        self.assertEqual(cfg.bench.duration, 10)
        self.assertAlmostEqual(cfg.model.safety_margin, 0.75)
        # Hérité de la base, pas écrasé.
        self.assertEqual(cfg.host.user, "kwak")
        self.assertAlmostEqual(cfg.bench.max_jitter_ms, 3.0)
        self.assertEqual(cfg.model.codec, "hevc")

    def test_profiles_do_not_leak_into_each_other(self):
        lan = load_config(self.path, "lan")
        self.assertEqual(lan.bench.datagram_len, 1400)   # pas 1380
        self.assertEqual(lan.host.host, "192.168.1.10")  # pas 10.66.119.1
        self.assertAlmostEqual(lan.bench.max_jitter_ms, 2.0)

    def test_unknown_profile_lists_the_available_ones(self):
        with self.assertRaises(ValueError) as ctx:
            load_config(self.path, "wifi")
        message = str(ctx.exception)
        self.assertIn("wifi", message)
        self.assertIn("lan", message)
        self.assertIn("vpn", message)

    def test_profile_without_config_file_is_rejected(self):
        with self.assertRaises(ValueError):
            load_config(None, "vpn")

    def test_profiles_section_is_not_mistaken_for_a_setting(self):
        # [profiles] ne doit pas déclencher « clé inconnue » à la racine.
        cfg = load_config(self.path)
        self.assertIsInstance(cfg, AppConfig)

    def test_malformed_profiles_section(self):
        bad = self.path.with_name("bad.toml")
        bad.write_text('profiles = "lan"\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_config(bad, "lan")

    def test_unknown_key_inside_a_profile_is_reported_with_its_path(self):
        bad = self.path.with_name("bad2.toml")
        bad.write_text("[profiles.vpn.bench]\nnimportequoi = 1\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_config(bad, "vpn")
        self.assertIn("profiles.vpn.bench", str(ctx.exception))


class TestCliIntegration(ProfileTestCase):
    def test_cli_flags_still_win_over_the_profile(self):
        args = build_parser().parse_args(
            ["-c", str(self.path), "-p", "vpn", "--length", "1200"])
        cfg = apply_overrides(load_config(args.config, args.profile), args)
        self.assertEqual(cfg.bench.datagram_len, 1200)
        self.assertEqual(cfg.active_profile, "vpn")

    def test_short_and_long_flag(self):
        for flag in ("-p", "--profile"):
            args = build_parser().parse_args([flag, "lan"])
            self.assertEqual(args.profile, "lan")


if __name__ == "__main__":
    unittest.main()
