from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.pen_test import build_pen_test_sequence


class PenTestTests(unittest.TestCase):
    def test_pen_test_sequence_returns_to_reference_each_level(self) -> None:
        points = build_pen_test_sequence(
            motor_key="m2_horizontal",
            reference_steps=100.0,
            start_steps=2.0,
            stop_steps=4.0,
            increment_steps=2.0,
            cycles_per_level=1,
            dwell_s=0.5,
        )
        self.assertEqual(points[0].target_steps, 102.0)
        self.assertEqual(points[1].target_steps, 98.0)
        self.assertEqual(points[2].target_steps, 100.0)
        self.assertEqual(points[-1].target_steps, 100.0)

    def test_pen_test_sequence_has_multiple_levels(self) -> None:
        points = build_pen_test_sequence(
            motor_key="m1_vertical",
            reference_steps=0.0,
            start_steps=1.0,
            stop_steps=3.0,
            increment_steps=1.0,
            cycles_per_level=2,
            dwell_s=0.25,
        )
        amplitudes = sorted({point.amplitude_steps for point in points})
        self.assertEqual(amplitudes, [1.0, 2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
