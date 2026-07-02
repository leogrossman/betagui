from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.hardware import MirrorController, PVFactory, build_signal_backend
from laser_mirrors_app.scan import ScanContext, ScanRunner, bounded_rectangular_spiral, build_angle_scan_points, build_overlap_scan_points, build_spiral_scan_points, choose_best_point, fit_overlap_diagonal, fixed_position_diagonal_slope


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

    def test_bounded_spiral_respects_outer_radius(self) -> None:
        coords = bounded_rectangular_spiral(100.0, 100.0, 250.0, 150.0, 20)
        self.assertTrue(coords)
        self.assertTrue(all(abs(x) <= 250.0 and abs(y) <= 150.0 for x, y in coords))

    def test_spiral_points_use_radius_strategy(self) -> None:
        config = AppConfig()
        config.scan.spiral_strategy = "bounded_spiral"
        config.scan.spiral_step_x = 100.0
        config.scan.spiral_step_y = 100.0
        config.scan.spiral_radius_x = 200.0
        config.scan.spiral_radius_y = 200.0
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_spiral_scan_points(config, controller.capture_reference(), target_pair="mirror2")
        self.assertTrue(points)
        for point in points:
            self.assertLessEqual(abs(point.targets.m2_horizontal), 200.0)
            self.assertLessEqual(abs(point.targets.m2_vertical), 200.0)

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

    def test_build_overlap_scan_points_sample_around_diagonal_line(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        slope = -1.5
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
            diagonal_slope=slope,
            pattern='perpendicular_cross',
        )
        strips: dict[int, list] = {}
        for point in points:
            strips.setdefault(point.group_index, []).append(point)
        self.assertEqual(len(strips), 3)
        centers = [strip_points[len(strip_points) // 2] for strip_points in strips.values()]
        for point in centers:
            self.assertLessEqual(abs(point.angle_y_urad - slope * point.angle_x_urad), config.geometry.vertical_step_urad)
        for strip_points in strips.values():
            self.assertGreater(len({round(point.angle_x_urad, 8) for point in strip_points}), 1)
            self.assertGreater(len({round(point.angle_y_urad, 8) for point in strip_points}), 1)

    def test_overlap_scan_targets_use_whole_step_deltas(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        reference = controller.capture_reference()
        points = build_overlap_scan_points(
            geometry,
            reference,
            'vertical',
            'mirror2',
            4,
            7.5,
            4,
            37.0,
            'mirror1_primary',
            diagonal_slope=-1.37,
            pattern='perpendicular_cross',
        )
        for point in points:
            deltas = point.targets.as_dict()
            self.assertEqual(deltas["m1_vertical"] - reference["m1_vertical"], round(deltas["m1_vertical"] - reference["m1_vertical"]))
            self.assertEqual(deltas["m2_vertical"] - reference["m2_vertical"], round(deltas["m2_vertical"] - reference["m2_vertical"]))

    def test_build_overlap_scan_points_can_make_horizontal_strips(self) -> None:
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
            diagonal_slope=-1.5,
            pattern='horizontal_strips',
        )
        strips: dict[int, list] = {}
        for point in points:
            strips.setdefault(point.group_index, []).append(point)
        self.assertEqual(len(strips), 3)
        strip_centers = []
        for strip_points in strips.values():
            self.assertGreater(len({round(point.angle_x_urad, 8) for point in strip_points}), 1)
            self.assertEqual(len({round(point.angle_y_urad, 8) for point in strip_points}), 1)
            mean_x = sum(point.angle_x_urad for point in strip_points) / len(strip_points)
            mean_y = sum(point.angle_y_urad for point in strip_points) / len(strip_points)
            strip_centers.append((mean_x, mean_y))
        self.assertGreater(len({round(center[0], 8) for center in strip_centers}), 1)
        for mean_x, mean_y in strip_centers:
            self.assertLessEqual(abs(mean_y - -1.5 * mean_x), 2 * config.geometry.vertical_step_urad)

    def test_build_overlap_scan_points_can_make_vertical_strips(self) -> None:
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
            diagonal_slope=-1.5,
            pattern='vertical_strips',
        )
        strips: dict[int, list] = {}
        for point in points:
            strips.setdefault(point.group_index, []).append(point)
        self.assertEqual(len(strips), 3)
        strip_centers = []
        for strip_points in strips.values():
            self.assertEqual(len({round(point.angle_x_urad, 8) for point in strip_points}), 1)
            self.assertGreater(len({round(point.angle_y_urad, 8) for point in strip_points}), 1)
            mean_x = sum(point.angle_x_urad for point in strip_points) / len(strip_points)
            mean_y = sum(point.angle_y_urad for point in strip_points) / len(strip_points)
            strip_centers.append((mean_x, mean_y))
        self.assertGreater(len({round(center[1], 8) for center in strip_centers}), 1)
        for mean_x, mean_y in strip_centers:
            self.assertLessEqual(abs(mean_y - -1.5 * mean_x), 2 * config.geometry.vertical_step_urad)

    def test_overlap_direction_can_be_reversed(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        a = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            3,
            100.0,
            3,
            100.0,
            'mirror1_primary',
            'upper_left_to_lower_right',
        )
        b = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            3,
            100.0,
            3,
            100.0,
            'mirror1_primary',
            'lower_left_to_upper_right',
        )
        self.assertNotEqual([p.targets.m2_vertical for p in a[:3]], [p.targets.m2_vertical for p in b[:3]])

    def test_fixed_position_diagonal_slope_uses_geometry(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        self.assertAlmostEqual(fixed_position_diagonal_slope(geometry, 'vertical'), -1.3802, places=3)
        self.assertAlmostEqual(fixed_position_diagonal_slope(geometry, 'horizontal'), -1.3802, places=3)

    def test_overlap_serpentine_reverses_every_other_strip(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            2,
            8.0,
            3,
            40.0,
            'mirror1_primary',
            diagonal_slope=-1.5,
            pattern='horizontal_strips',
            serpentine=True,
        )
        first_strip = [point.angle_x_urad for point in points if point.group_index == 0]
        second_strip = [point.angle_x_urad for point in points if point.group_index == 1]
        self.assertGreater(first_strip[0], first_strip[-1])
        self.assertLess(second_strip[0], second_strip[-1])

    def test_overlap_left_to_right_starts_each_strip_on_left_when_not_serpentine(self) -> None:
        config = AppConfig()
        geometry = LaserMirrorGeometry(config.geometry)
        factory = PVFactory(True)
        controller = MirrorController(config.controller, factory)
        points = build_overlap_scan_points(
            geometry,
            controller.capture_reference(),
            'vertical',
            'mirror2',
            2,
            8.0,
            3,
            40.0,
            'mirror1_primary',
            'left_to_right',
            diagonal_slope=-1.5,
            pattern='horizontal_strips',
            serpentine=False,
        )
        for group_index in (0, 1):
            strip = [point.angle_x_urad for point in points if point.group_index == group_index]
            self.assertLess(strip[0], strip[-1])

    def test_fit_overlap_diagonal_estimates_measured_slope(self) -> None:
        from laser_mirrors_app.models import MeasurementRecord
        rows = []
        base = dict(
            mode='overlap_vertical', elapsed_s=0.0, offset_x_mm=float('nan'), offset_y_mm=float('nan'),
            signal_label='P1 avg', signal_pv='pv', signal_value=1.0, signal_std=0.0, samples_used=1,
            commanded_m1_horizontal=0.0, commanded_m1_vertical=0.0, commanded_m2_horizontal=0.0, commanded_m2_vertical=0.0,
            rbv_m1_horizontal=0.0, rbv_m1_vertical=0.0, rbv_m2_horizontal=0.0, rbv_m2_vertical=0.0,
            timestamp_iso='t',
        )
        for index, x in enumerate((-20.0, -10.0, 0.0, 10.0, 20.0)):
            rows.append(MeasurementRecord(point_index=index, angle_x_urad=x, angle_y_urad=-1.4 * x + 3.0, signal_average=10.0 + index, **base))
        fit = fit_overlap_diagonal(rows, -1.38)
        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertAlmostEqual(fit.slope, -1.4, places=6)
        self.assertAlmostEqual(fit.slope_error, -0.02, places=6)

    def test_fit_overlap_diagonal_uses_best_point_per_strip(self) -> None:
        from laser_mirrors_app.models import MeasurementRecord
        rows = []
        base = dict(
            mode='overlap_vertical', elapsed_s=0.0, offset_x_mm=float('nan'), offset_y_mm=float('nan'),
            signal_label='P1 avg', signal_pv='pv', signal_value=1.0, signal_std=0.0, samples_used=1,
            commanded_m1_horizontal=0.0, commanded_m1_vertical=0.0, commanded_m2_horizontal=0.0, commanded_m2_vertical=0.0,
            rbv_m1_horizontal=0.0, rbv_m1_vertical=0.0, rbv_m2_horizontal=0.0, rbv_m2_vertical=0.0,
            timestamp_iso='t',
        )
        optima = [(0.0, 0.0), (20.0, -10.0), (40.0, -20.0)]
        index = 0
        for group_index, (best_x, y) in enumerate(optima):
            for x, signal in ((-80.0, 1.0), (best_x, 10.0), (80.0, 1.0)):
                rows.append(
                    MeasurementRecord(
                        point_index=index,
                        angle_x_urad=x,
                        angle_y_urad=y,
                        signal_average=signal,
                        group_index=group_index,
                        group_label=f'strip {group_index}',
                        **base,
                    )
                )
                index += 1
        fit = fit_overlap_diagonal(rows, -0.5)
        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertEqual(fit.points_used, 3)
        self.assertAlmostEqual(fit.slope, -0.5, places=6)


if __name__ == "__main__":
    unittest.main()
