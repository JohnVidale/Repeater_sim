"""Tests for the readable P38 configuration surface."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run import load_settings


class SettingsTests(unittest.TestCase):
    def test_shipped_settings_are_valid(self):
        path = Path(__file__).resolve().parents[1] / "settings" / "p38_yka_ilar.json"
        settings = load_settings(path)
        self.assertEqual(settings["pair"], "P38")
        self.assertTrue(settings["include_relative_offset"])

    def test_relative_offset_must_be_boolean(self):
        settings = {"pair": "P38", "include_relative_offset": "yes", "modes": ["yka_40s"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings))
            with self.assertRaisesRegex(ValueError, "true or false"):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
