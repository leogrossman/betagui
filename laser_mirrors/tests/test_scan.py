from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.hardware import MirrorController, PVFactory, build_signal_backend
from laser_mirrors_app.scan import ScanContext, ScanRunner, build_angle_scan_points, build_overlap_scan_points, build_spiral_scan_points, choose_best_point


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

    def test_invalid_zero_ioc_limits_are_ignored_by_default(self) -> None:
        config = AppConfig()
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        controller.motors['m2_horizontal'].llm.put(0.0)
        controller.motors['m2_horizontal'].hlm.put(0.0)
        ok, errors = controller.validate_targets({'m2_horizontal': -10.0})
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_manual_motor_limits_are_enforced(self) -> None:
        config = AppConfig()
        config.controller.use_manual_motor_limits = True
        config.controller.m2_horizontal_llm = -20.0
        config.controller.m2_horizontal_hlm = 20.0
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        ok, errors = controller.validate_targets({'m2_horizontal': -25.0})
        self.assertFalse(ok)
        self.assertTrue(any('below LLM' in err and '(manual)' in err for err in errors))

    def test_choose_best_point_rejects_isolated_spike_in_spiral(self) -> None:
        from laser_mirrors_app.models import MeasurementRecord
        rows = []
        base = dict(
            mode='mirror2_spiral', elapsed_s=0.0, angle_x_urad=float('nan'), angle_y_urad=float('nan'),
            offset_x_mm=float('nan'), offset_y_mm=float('nan'), signal_label='P1 avg', signal_pv='pv',
            signal_std=0.0, samples_used=5, commanded_m1_horizontal=0.0, commanded_m1_vertical=0.0,
            rbv_m1_horizontal=0.0, rbv_m1_vertical=0.0, rbv_m2_horizontal=0.0, rbv_m2_vertical=0.0,
            timestamp_iso='t'
        )
        def row(idx, x, y, avg):
            return MeasurementRecord(point_index=idx, signal_value=avg, signal_average=avg, commanded_m2_horizontal=x, commanded_m2_vertical=y, **base)
        rows.extend([
            row(0, 0.0, 0.0, 9.0),
            row(1, 1.0, 0.0, 9.2),
            row(2, -1.0, 0.0, 9.1),
            row(3, 0.0, 1.0, 9.0),
            row(4, 0.0, -1.0, 9.1),
            row(5, 10.0, 10.0, 10.0),
        ])
        best = choose_best_point(rows, 'max')
        self.assertIsNotNone(best)
        self.assertNotEqual(best.point_index, 5)

    def test_build_overlap_scan_points_count(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            5,
            8.0,
            9,
            50.0,
            'mirror1_primary',
        )
        self.assertEqual(len(points), 45)
        self.assertTrue(all(point.mode == 'overlap_vertical' for point in points))

    def test_build_overlap_scan_points_hold_fixed_angle_per_strip(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            3,
            8.0,
            5,
            40.0,
            'mirror1_primary',
        )
        strips: dict[int, list] = {}
        for point in points:
            strips.setdefault(point.group_index, []).append(point)
        self.assertEqual(len(strips), 3)
        for strip_points in strips.values():
            mirror1_angles = {round(point.angle_x_urad, 8) for point in strip_points}
            mirror2_angles = {round(point.angle_y_urad, 8) for point in strip_points}
            self.assertGreater(len(mirror1_angles), 1)
            self.assertEqual(len(mirror2_angles), 1)


if __name__ == "__main__":
    unittest.main()
