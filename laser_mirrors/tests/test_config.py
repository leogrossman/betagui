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
        self.assertTrue(loaded.controller.write_mode)
        self.assertEqual(loaded.controller.max_step_per_put, 100.0)
        self.assertEqual(loaded.controller.settle_s, 0.30)
        self.assertEqual(loaded.controller.max_delta_from_reference, 5000.0)
        self.assertEqual(loaded.controller.max_absolute_move_steps, 5000.0)
        self.assertEqual(loaded.scan.dwell_s, 0.50)
        self.assertEqual(loaded.scan.p1_samples_per_point, 3)
        self.assertEqual(loaded.scan.spiral_radius_x, 1500.0)
        self.assertEqual(loaded.scan.overlap_vertical_step_steps, 200.0)
        self.assertEqual(loaded.scan.overlap_horizontal_step_steps, 100.0)
        self.assertEqual(loaded.scan.overlap_line_span_urad, 300.0)
        self.assertEqual(loaded.scan.overlap_m1_span_urad, 56.7)
        self.assertEqual(loaded.scan.overlap_m2_span_urad, 567.0)
        self.assertEqual(loaded.scan.overlap_m1_span_steps, 30.0)
        self.assertEqual(loaded.scan.overlap_m2_span_steps, 300.0)
        self.assertAlmostEqual(loaded.scan.overlap_diagonal_slope, -1.38)
        self.assertEqual(loaded.scan.overlap_plot_axis, "angle")
        self.assertEqual(loaded.scan.overlap_pattern, "horizontal_strips")
        self.assertTrue(loaded.scan.overlap_serpentine)
        self.assertEqual(loaded.scan.plot_dot_radius, 6.0)

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
