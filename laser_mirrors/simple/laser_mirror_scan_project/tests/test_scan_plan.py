import unittest
from laser_mirror_scan.core import BeamGeometry, build_angle_grid, build_mirror2_spiral


REF = {
    "m1_vertical": 0.0,
    "m1_horizontal": 0.0,
    "m2_vertical": 0.0,
    "m2_horizontal": 0.0,
}


class ScanPlanTests(unittest.TestCase):
    def test_angle_grid_count_2d(self):
        points = build_angle_grid(BeamGeometry(), REF, 0, 0, 100, 200, 5, 3, 0, 0, "both_2d")
        self.assertEqual(len(points), 15)

    def test_horizontal_only_count(self):
        points = build_angle_grid(BeamGeometry(), REF, 0, 0, 100, 200, 5, 3, 0, 0, "horizontal_only")
        self.assertEqual(len(points), 5)

    def test_vertical_only_count(self):
        points = build_angle_grid(BeamGeometry(), REF, 0, 0, 100, 200, 5, 3, 0, 0, "vertical_only")
        self.assertEqual(len(points), 3)

    def test_spiral_nonempty_and_m2_only(self):
        points = build_mirror2_spiral(REF, 10, 20, 6, 8, 3)
        self.assertTrue(len(points) > 1)
        for p in points:
            self.assertEqual(p.motor_targets.m1_horizontal, 0)
            self.assertEqual(p.motor_targets.m1_vertical, 0)


if __name__ == "__main__":
    unittest.main()
