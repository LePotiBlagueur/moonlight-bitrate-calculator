"""Détection de la version d'iperf3 distante (validée sur un hôte réel 3.1.4)."""

import unittest

from moonlight_bitrate.remote import (
    MIN_PARALLEL_UDP,
    MIN_RECOMMENDED,
    parse_version,
    version_warnings,
)

# Sortie exacte relevée sur l'hôte Windows de test.
REAL_314 = ("iperf 3.1.4\n"
            "CYGWIN_NT-10.0 kwak 2.6.0(0.304/5/3) 2016-08-31 14:32 x86_64\n"
            "Optional features available: None")


class TestParseVersion(unittest.TestCase):
    def test_real_cygwin_output(self):
        self.assertEqual(parse_version(REAL_314), (3, 1, 4))

    def test_modern_output(self):
        self.assertEqual(parse_version("iperf 3.17.1 (cJSON 1.7.15)"), (3, 17, 1))

    def test_two_component_version(self):
        self.assertEqual(parse_version("iperf 3.9"), (3, 9, 0))

    def test_garbage(self):
        self.assertIsNone(parse_version("'iperf3' n'est pas reconnu"))
        self.assertIsNone(parse_version(""))

    def test_ordering_is_numeric_not_lexicographic(self):
        # 3.9 < 3.17 : une comparaison de chaînes donnerait l'inverse.
        self.assertLess(parse_version("iperf 3.9"), parse_version("iperf 3.17"))


class TestWarnings(unittest.TestCase):
    def test_old_build_is_flagged(self):
        issues = version_warnings((3, 1, 4), streams=1)
        self.assertEqual(len(issues), 1)
        self.assertIn("ancien", issues[0])

    def test_parallel_udp_flagged_only_when_requested(self):
        self.assertEqual(len(version_warnings((3, 1, 4), streams=1)), 1)
        self.assertEqual(len(version_warnings((3, 1, 4), streams=4)), 2)

    def test_recent_build_is_silent(self):
        self.assertEqual(version_warnings((3, 17, 1), streams=4), [])

    def test_thresholds_are_consistent(self):
        self.assertLessEqual(MIN_PARALLEL_UDP, MIN_RECOMMENDED)

    def test_unknown_version_is_reported(self):
        issues = version_warnings(None, streams=1)
        self.assertEqual(len(issues), 1)
        self.assertIn("indéterminée", issues[0])


if __name__ == "__main__":
    unittest.main()
