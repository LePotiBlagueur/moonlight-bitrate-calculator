"""Comportement des points d'entrée gelés (double-clic Windows)."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from moonlight_bitrate import entry


class TestEntry(unittest.TestCase):
    def test_source_mode_is_never_interactive(self):
        # Sans sys.frozen, les commandes gardent leur comportement normal.
        self.assertFalse(entry._interactive())

    def test_frozen_windows_is_interactive(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(entry._interactive())

    def test_frozen_linux_is_not_interactive(self):
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(entry._interactive())

    def test_config_next_to_the_binary_is_picked_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.toml").write_text("[host]\nhost='1.2.3.4'\n")
            with mock.patch.object(entry, "app_dir", lambda: Path(tmp)):
                self.assertEqual(entry.find_config(),
                                 str(Path(tmp) / "config.toml"))

    def test_example_config_is_the_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.example.toml").write_text("")
            with mock.patch.object(entry, "app_dir", lambda: Path(tmp)):
                self.assertTrue(entry.find_config().endswith("config.example.toml"))

    def test_no_config_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(entry, "app_dir", lambda: Path(tmp)):
                self.assertIsNone(entry.find_config())
                with contextlib.redirect_stdout(io.StringIO()):
                    argv = entry._default_argv(["--measure"])
                self.assertEqual(argv, ["--measure", "--pause"])

    def test_default_argv_prepends_the_config_and_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.toml").write_text("")
            with mock.patch.object(entry, "app_dir", lambda: Path(tmp)):
                argv = entry._default_argv(["--measure"])
        self.assertEqual(argv[0], "-c")
        self.assertEqual(argv[-2:], ["--measure", "--pause"])

    def test_explicit_args_are_passed_through_untouched(self):
        with mock.patch("moonlight_bitrate.recap_cli.main") as fake:
            fake.return_value = 0
            entry.recap_main(["-b", "300", "--format", "csv"])
        fake.assert_called_once_with(["-b", "300", "--format", "csv"])

    def test_recap_entry_runs(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = entry.recap_main(["-b", "300", "--sections", "best",
                                     "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("par taille d'écran", out.getvalue())


if __name__ == "__main__":
    unittest.main()
