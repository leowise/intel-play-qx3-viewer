import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qx5_settings import DEFAULT_SETTINGS, load_settings, save_settings


class TestQx5Settings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "settings.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_returns_defaults(self):
        self.assertEqual(load_settings(self.path), DEFAULT_SETTINGS)

    def test_round_trip_preserves_settings(self):
        expected = {
            "led_top": True,
            "led_bottom": False,
            "brightness": 4,
            "saturation": 123,
            "sharpness": 2,
            "gamma": 3,
        }
        save_settings(self.path, expected)
        self.assertEqual(load_settings(self.path), expected)

    def test_invalid_values_fall_back_individually(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({
                "led_top": "yes",
                "led_bottom": True,
                "brightness": 31,
                "saturation": 100,
                "sharpness": 3,
                "gamma": "bad",
            }, handle)

        loaded = load_settings(self.path)
        self.assertEqual(loaded, {
            "led_top": False,
            "led_bottom": True,
            "brightness": 15,
            "saturation": 100,
            "sharpness": 1,
            "gamma": 1,
        })

    def test_both_lights_are_normalized_to_top_only(self):
        save_settings(self.path, {"led_top": True, "led_bottom": True})
        loaded = load_settings(self.path)
        self.assertTrue(loaded["led_top"])
        self.assertFalse(loaded["led_bottom"])


if __name__ == "__main__":
    unittest.main()
