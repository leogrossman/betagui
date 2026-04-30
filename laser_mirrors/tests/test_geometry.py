from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import GeometryConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.models import UndulatorTarget


class GeometryTests(unittest.TestCase):
    def test_round_trip_x(self) -> None:
        geom = LaserMirrorGeometry(GeometryConfig())
        target = UndulatorTarget(offset_mm=0.75, angle_urad=120.0)
        angles = geom.to_mirror_angles(target, "x")
        recovered = geom.to_undulator_target(angles, "x")
        self.assertAlmostEqual(recovered.offset_mm, target.offset_mm, places=6)
        self.assertAlmostEqual(recovered.angle_urad, target.angle_urad, places=6)

    def test_round_trip_y(self) -> None:
        geom = LaserMirrorGeometry(GeometryConfig())
        target = UndulatorTarget(offset_mm=-1.2, angle_urad=-85.0)
        angles = geom.to_mirror_angles(target, "y")
        recovered = geom.to_undulator_target(angles, "y")
        self.assertAlmostEqual(recovered.offset_mm, target.offset_mm, places=6)
        self.assertAlmostEqual(recovered.angle_urad, target.angle_urad, places=6)

    def test_step_conversion(self) -> None:
        geom = LaserMirrorGeometry(GeometryConfig())
        steps = geom.angle_delta_to_steps(27.5, "y", 1)
        self.assertEqual(steps, 15)
        angle = geom.steps_to_angle_delta(10, "y", 1)
        self.assertAlmostEqual(angle, 18.9, places=6)

    def test_solve_mirror2_for_fixed_offset(self) -> None:
        geom = LaserMirrorGeometry(GeometryConfig())
        solved = geom.solve_mirror2_for_fixed_offset(mirror1_urad=150.0, offset_mm=0.4, axis="x")
        target = geom.to_undulator_target(solved, "x")
        self.assertAlmostEqual(target.offset_mm, 0.4, places=6)

    def test_solve_mirror1_for_fixed_offset(self) -> None:
        geom = LaserMirrorGeometry(GeometryConfig())
        solved = geom.solve_mirror1_for_fixed_offset(mirror2_urad=-90.0, offset_mm=-0.7, axis="y")
        target = geom.to_undulator_target(solved, "y")
        self.assertAlmostEqual(target.offset_mm, -0.7, places=6)


if __name__ == "__main__":
    unittest.main()
