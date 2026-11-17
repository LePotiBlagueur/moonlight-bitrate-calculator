"""Garde-fous contre la dérive entre le code, la doc et les complétions."""

import unittest
from dataclasses import fields
from pathlib import Path

from moonlight_bitrate import cli, recap_cli
from moonlight_bitrate.config import AppConfig, BenchConfig, HostConfig, ModelConfig

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Champ interne : renseigné par le chargeur, pas par l'utilisateur.
INTERNAL_KEYS = {"active_profile"}


def option_strings(parser) -> set[str]:
    found = set()
    for action in parser._actions:
        found.update(o for o in action.option_strings if o.startswith("--"))
    return found


class TestConfigurationReference(unittest.TestCase):
    def setUp(self):
        self.text = (DOCS / "configuration.md").read_text("utf-8")

    def test_every_key_is_documented(self):
        undocumented = []
        for section in (HostConfig, BenchConfig, ModelConfig, AppConfig):
            for field in fields(section):
                if field.name in INTERNAL_KEYS:
                    continue
                if section is AppConfig and field.name in ("host", "bench", "model"):
                    continue
                if f"`{field.name}`" not in self.text:
                    undocumented.append(f"{section.__name__}.{field.name}")
        self.assertEqual(undocumented, [],
                         "clés absentes de docs/configuration.md")

    def test_sections_are_present(self):
        for heading in ("[host]", "[bench]", "[model]", "[profiles."):
            self.assertIn(heading, self.text)


class TestCompletions(unittest.TestCase):
    CASES = [
        ("_moonlight-bitrate", cli.build_parser),
        ("_moonlight-recap", recap_cli.build_parser),
    ]

    def test_every_option_is_completable(self):
        for name, build in self.CASES:
            with self.subTest(command=name):
                text = (ROOT / "completions" / name).read_text("utf-8")
                missing = sorted(o for o in option_strings(build())
                                 if o not in text)
                self.assertEqual(missing, [],
                                 f"options absentes de completions/{name}")

    def test_completions_declare_the_right_command(self):
        for name, _ in self.CASES:
            text = (ROOT / "completions" / name).read_text("utf-8")
            self.assertTrue(text.startswith(f"#compdef {name[1:]}\n"))


class TestDocSet(unittest.TestCase):
    EXPECTED = ["README.md", "usage.md", "configuration.md",
                "architecture.md", "troubleshooting.md", "install.md"]

    def test_all_pages_exist_and_are_substantial(self):
        for name in self.EXPECTED:
            page = DOCS / name
            with self.subTest(page=name):
                self.assertTrue(page.exists(), f"docs/{name} manquant")
                self.assertGreater(len(page.read_text("utf-8")), 300)

    def test_index_links_every_page(self):
        index = (DOCS / "README.md").read_text("utf-8")
        for name in self.EXPECTED:
            if name != "README.md":
                self.assertIn(f"({name})", index, f"{name} absent de l'index")

    def test_internal_links_resolve(self):
        import re
        pattern = re.compile(r"\]\((?!https?:)([^)#]+)")
        for page in DOCS.glob("*.md"):
            for target in pattern.findall(page.read_text("utf-8")):
                with self.subTest(page=page.name, link=target):
                    self.assertTrue((page.parent / target).resolve().exists(),
                                    f"lien mort dans docs/{page.name} : {target}")


if __name__ == "__main__":
    unittest.main()


class TestDefaultsMatchTheReference(unittest.TestCase):
    """Les valeurs par défaut citées dans la doc doivent être les vraies."""

    SAMPLES = [
        (HostConfig, "user"), (HostConfig, "port"), (HostConfig, "iperf_port"),
        (BenchConfig, "duration"), (BenchConfig, "datagram_len"),
        (BenchConfig, "max_loss_pct"), (BenchConfig, "max_jitter_ms"),
        (ModelConfig, "codec"), (ModelConfig, "quality"),
        (ModelConfig, "fec_overhead"), (ModelConfig, "safety_margin"),
    ]

    @staticmethod
    def _matches(documented: str, actual) -> bool:
        """`0.20` dans la doc vaut bien 0.2 dans le code."""
        if documented == str(actual):
            return True
        try:
            return float(documented) == float(actual)
        except (TypeError, ValueError):
            return False

    def test_documented_defaults(self):
        import re

        text = (DOCS / "configuration.md").read_text("utf-8")
        for section, name in self.SAMPLES:
            field = next(f for f in fields(section) if f.name == name)
            with self.subTest(key=name):
                row = next((line for line in text.splitlines()
                            if line.startswith(f"| `{name}`")), None)
                self.assertIsNotNone(row, f"{name} absent du tableau")
                cells = [c.strip() for c in row.split("|")]
                documented = re.fullmatch(r"`(.*)`", cells[2])
                self.assertIsNotNone(
                    documented,
                    f"le défaut de {name} doit être entre accents graves")
                self.assertTrue(
                    self._matches(documented.group(1), field.default),
                    f"défaut documenté ({documented.group(1)}) ≠ défaut du "
                    f"code ({field.default}) pour {name}")
