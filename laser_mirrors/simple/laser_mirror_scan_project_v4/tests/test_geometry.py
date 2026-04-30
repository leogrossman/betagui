import unittest
from laser_mirror_scan.core import BeamGeometry, GeometryConfig, UndulatorTarget


class GeometryTests(unittest.TestCase):
    def test_round_trip_horizontal(self):
        g = BeamGeometry(GeometryConfig())
        target = UndulatorTarget(offset_mm=0.75, angle_urad=120.0)
        angles = g.target_to_mirror_angles(target, "horizontal")
        rec = g.mirror_angles_to_target(angles, "horizontal")
        self.assertAlmostEqual(rec.offset_mm, target.offset_mm, places=6)
        self.assertAlmostEqual(rec.angle_urad, target.angle_urad, places=6)

    def test_round_trip_vertical(self):
        g = BeamGeometry(GeometryConfig())
        target = UndulatorTarget(offset_mm=-0.3, angle_urad=-80.0)
        angles = g.target_to_mirror_angles(target, "vertical")
        rec = g.mirror_angles_to_target(angles, "vertical")
        self.assertAlmostEqual(rec.offset_mm, target.offset_mm, places=6)
        self.assertAlmostEqual(rec.angle_urad, target.angle_urad, places=6)

    def test_zero_target_zero_delta(self):
        g = BeamGeometry(GeometryConfig())
        d = g.target_to_step_deltas(0, 0, 0, 0)
        self.assertAlmostEqual(d.m1_horizontal, 0)
        self.assertAlmostEqual(d.m2_horizontal, 0)
        self.assertAlmostEqual(d.m1_vertical, 0)
        self.assertAlmostEqual(d.m2_vertical, 0)


if __name__ == "__main__":
    unittest.main()
