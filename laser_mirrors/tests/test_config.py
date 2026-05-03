from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig


class ConfigTests(unittest.TestCase):
    def test_default_scan_mode_is_vertical_only(self) -> None:
        loaded = AppConfig()
        self.assertEqual(loaded.scan.mode, "vertical_only")

    def test_load_ignores_unknown_keys_from_older_configs(self) -> None:
        root = Path(tempfile.mkdtemp())
        config_path = root / "laser_mirrors_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "controller": {
                        "safe_mode": True,
                        "signal_label": "P1 avg",
                        "obsolete_flag": 123,
                    },
                    "scan": {
                        "mode": "horizontal_only",
                        "old_extra_field": "ignored",
                    },
                    "geometry": {
                        "mirror_distance_mm": 2285.0,
                        "legacy_unused_value": 5,
                    },
                }
            ),
            encoding="utf-8",
        )
        loaded = AppConfig.load(config_path)
        self.assertTrue(loaded.controller.safe_mode)
        self.assertEqual(loaded.controller.signal_label, "P1 avg")
        self.assertEqual(loaded.scan.mode, "horizontal_only")
        self.assertEqual(loaded.geometry.mirror_distance_mm, 2285.0)

    def test_manual_motor_limit_fields_round_trip(self) -> None:
        loaded = AppConfig()
        loaded.controller.use_manual_motor_limits = True
        loaded.controller.m2_horizontal_llm = -50.0
        loaded.controller.m2_horizontal_hlm = 250.0
        root = Path(tempfile.mkdtemp())
        config_path = root / "laser_mirrors_config.json"
        loaded.save(config_path)
        reloaded = AppConfig.load(config_path)
        self.assertTrue(reloaded.controller.use_manual_motor_limits)
        self.assertEqual(reloaded.controller.m2_horizontal_llm, -50.0)
        self.assertEqual(reloaded.controller.m2_horizontal_hlm, 250.0)



if __name__ == "__main__":
    unittest.main()
