from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.hardware import SimulatedMirrorBackend, SimulatedP1Backend
from laser_mirrors_app.models import MirrorAngles, UndulatorTarget
from laser_mirrors_app.scan import ScanContext, ScanRunner, build_scan_grid


class ScanTests(unittest.TestCase):
    def test_build_scan_grid_count(self) -> None:
        config = AppConfig()
        config.scan.points_x = 5
        config.scan.points_y = 4
        points = build_scan_grid(config, 0.0, 0.0)
        self.assertEqual(len(points), 20)

    def test_runner_collects_measurements(self) -> None:
        config = AppConfig()
        config.scan.points_x = 2
        config.scan.points_y = 2
        config.scan.dwell_s = 0.0
        config.scan.p1_samples_per_point = 1
        geometry = LaserMirrorGeometry(config.geometry)
        mirror = SimulatedMirrorBackend()
        p1 = SimulatedP1Backend()
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, mirror, p1, lambda msg: None, out)
        seen = []
        finished = []
        ctx = ScanContext(
            angles_x=MirrorAngles(0.0, 0.0),
            angles_y=MirrorAngles(0.0, 0.0),
            offset_x_mm=0.0,
            offset_y_mm=0.0,
            requested_x=UndulatorTarget(offset_mm=0.0, angle_urad=0.0),
            requested_y=UndulatorTarget(offset_mm=0.0, angle_urad=0.0),
        )
        runner.start(ctx, on_measurement=seen.append, on_finish=finished.append)
        runner._thread.join(timeout=5.0)
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(runner.measurements), 4)
        self.assertTrue(finished)

    def test_primary_mirror_mode_keeps_offset(self) -> None:
        config = AppConfig()
        config.scan.points_x = 2
        config.scan.points_y = 1
        config.scan.dwell_s = 0.0
        config.scan.p1_samples_per_point = 1
        config.scan.solve_mode = "mirror1_primary"
        config.scan.center_angle_x_urad = 100.0
        config.scan.span_angle_x_urad = 20.0
        geometry = LaserMirrorGeometry(config.geometry)
        mirror = SimulatedMirrorBackend()
        p1 = SimulatedP1Backend()
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, mirror, p1, lambda msg: None, out)
        seen = []
        finished = []
        ctx = ScanContext(
            angles_x=MirrorAngles(0.0, 0.0),
            angles_y=MirrorAngles(0.0, 0.0),
            offset_x_mm=0.25,
            offset_y_mm=0.0,
            requested_x=UndulatorTarget(offset_mm=0.25, angle_urad=0.0),
            requested_y=UndulatorTarget(offset_mm=0.0, angle_urad=0.0),
        )
        runner.start(ctx, on_measurement=seen.append, on_finish=finished.append)
        runner.join(timeout=5.0)
        self.assertTrue(seen)
        for measurement in seen:
            self.assertAlmostEqual(measurement.offset_x_mm, 0.25, places=6)


if __name__ == "__main__":
    unittest.main()
