from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.hardware import MirrorController, PVFactory, build_signal_backend
from laser_mirrors_app.scan import ScanContext, ScanRunner, build_angle_scan_points, build_spiral_scan_points, choose_best_point


class ScanTests(unittest.TestCase):
    def test_spiral_points_can_target_mirror1(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_spiral_scan_points(config, controller.capture_reference(), target_pair="mirror1")
        self.assertTrue(points)
        self.assertEqual(points[0].mode, "mirror1_spiral")
        self.assertEqual(points[0].targets.m2_horizontal, controller.capture_reference()["m2_horizontal"])

    def test_build_scan_grid_count(self) -> None:
        config = AppConfig()
        config.scan.mode = "both_2d"
        config.scan.points_x = 5
        config.scan.points_y = 4
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_angle_scan_points(config, geometry, controller.capture_reference())
        self.assertEqual(len(points), 20)

    def test_runner_collects_measurements(self) -> None:
        config = AppConfig()
        config.scan.mode = "both_2d"
        config.scan.points_x = 2
        config.scan.points_y = 2
        config.scan.dwell_s = 0.0
        config.scan.p1_samples_per_point = 1
        config.controller.inter_put_delay_s = 0.0
        config.controller.settle_s = 0.0
        config.controller.max_step_per_put = 1000.0
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        signal = build_signal_backend(True, "p1_h1_avg", None, factory)
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, controller, signal, lambda msg: None, out)
        seen = []
        finished = []
        ctx = ScanContext(reference_steps=controller.capture_reference(), signal_label="P1 avg", signal_pv="simulated")
        runner.start("angle", ctx, on_measurement=seen.append, on_finish=lambda path, best: finished.append((path, best)))
        runner.join(timeout=5.0)
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(runner.measurements), 4)
        self.assertTrue(finished)

    def test_primary_mirror_mode_keeps_offset(self) -> None:
        config = AppConfig()
        config.scan.mode = "horizontal_only"
        config.scan.points_x = 2
        config.scan.points_y = 1
        config.scan.dwell_s = 0.0
        config.scan.p1_samples_per_point = 1
        config.controller.inter_put_delay_s = 0.0
        config.controller.settle_s = 0.0
        config.controller.max_step_per_put = 1000.0
        config.scan.solve_mode = "mirror1_primary"
        config.scan.center_angle_x_urad = 100.0
        config.scan.span_angle_x_urad = 20.0
        config.scan.offset_x_mm = 0.25
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        signal = build_signal_backend(True, "p1_h1_avg", None, factory)
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, controller, signal, lambda msg: None, out)
        seen = []
        ctx = ScanContext(reference_steps=controller.capture_reference(), signal_label="P1 avg", signal_pv="simulated")
        runner.start("angle", ctx, on_measurement=seen.append, on_finish=lambda path, best: None)
        runner.join(timeout=5.0)
        self.assertTrue(seen)
        for measurement in seen:
            self.assertAlmostEqual(measurement.offset_x_mm, 0.25, places=6)

    def test_choose_best_point_max(self) -> None:
        config = AppConfig()
        config.scan.mode = "both_2d"
        config.controller.inter_put_delay_s = 0.0
        config.controller.settle_s = 0.0
        config.controller.max_step_per_put = 1000.0
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        signal = build_signal_backend(True, "p1_h1_avg", None, factory)
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, controller, signal, lambda msg: None, out)
        ctx = ScanContext(reference_steps=controller.capture_reference(), signal_label="P1 avg", signal_pv="simulated")
        runner.start("angle", ctx, on_measurement=lambda row: None, on_finish=lambda path, best: None)
        runner.join(timeout=5.0)
        best = choose_best_point(runner.measurements, "max")
        self.assertIsNotNone(best)

    def test_runner_survives_move_failure_and_sets_last_error(self) -> None:
        config = AppConfig()
        config.scan.mode = "horizontal_only"
        config.scan.points_x = 2
        config.scan.points_y = 1
        config.scan.dwell_s = 0.0
        config.scan.p1_samples_per_point = 1
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        signal = build_signal_backend(True, "p1_h1_avg", None, factory)
        out = Path(tempfile.mkdtemp())
        runner = ScanRunner(config, geometry, controller, signal, lambda msg: None, out)
        seen = []
        finished = []
        ctx = ScanContext(reference_steps=controller.capture_reference(), signal_label="P1 avg", signal_pv="simulated")

        def broken_move(*args, **kwargs):
            raise RuntimeError("simulated move timeout")

        controller.move_absolute_group = broken_move  # type: ignore[method-assign]
        runner.start("angle", ctx, on_measurement=seen.append, on_finish=lambda path, best: finished.append((path, best)))
        runner.join(timeout=5.0)
        self.assertEqual(seen, [])
        self.assertTrue(finished)
        self.assertEqual(runner.last_error, "simulated move timeout")


if __name__ == "__main__":
    unittest.main()
