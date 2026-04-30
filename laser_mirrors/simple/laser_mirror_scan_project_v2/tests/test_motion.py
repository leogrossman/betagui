import unittest
from laser_mirror_scan.core import ramp_values


class MotionTests(unittest.TestCase):
    def test_ramp_small(self):
        self.assertEqual(ramp_values(0, 5, 10), [5.0])

    def test_ramp_large(self):
        vals = ramp_values(0, 120, 50)
        self.assertEqual(vals[-1], 120.0)
        self.assertTrue(all(abs(b - a) <= 50.000001 for a, b in zip([0] + vals[:-1], vals)))


if __name__ == "__main__":
    unittest.main()
