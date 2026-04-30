from __future__ import annotations

import csv
import json
import math
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from .config import AppConfig
from .geometry import LaserMirrorGeometry, linspace
from .hardware import MirrorController
from .models import BestPointRecommendation, CommandRecord, MeasurementRecord, MotorTargets, ScanPoint, UndulatorTarget


@dataclass
class ScanContext:
    reference_steps: dict[str, float]
    signal_label: str
    signal_pv: str


def rectangular_spiral(step_x: float, step_y: float, turns: int) -> list[tuple[float, float]]:
    x = 0.0
    y = 0.0
    points = [(x, y)]
    directions = [(step_x, 0.0), (0.0, step_y), (-step_x, 0.0), (0.0, -step_y)]
    segment_length = 1
    direction_index = 0
    increases = 0
    for _ in range(max(0, turns)):
        dx, dy = directions[direction_index]
        for _ in range(segment_length):
            x += dx
            y += dy
            points.append((x, y))
        direction_index = (direction_index + 1) % 4
        increases += 1
        if increases % 2 == 0:
            segment_length += 1
    return points


def build_angle_scan_points(config: AppConfig, geometry: LaserMirrorGeometry, reference_steps: dict[str, float]) -> list[ScanPoint]:
    scan = config.scan
    xs = linspace(scan.center_angle_x_urad, scan.span_angle_x_urad, scan.points_x)
    ys = linspace(scan.center_angle_y_urad, scan.span_angle_y_urad, scan.points_y)
    if scan.mode == "horizontal_only":
        ys = [scan.center_angle_y_urad]
    elif scan.mode == "vertical_only":
        xs = [scan.center_angle_x_urad]
    points: list[ScanPoint] = []
    index = 0
    for row, angle_y in enumerate(ys):
        row_xs = list(xs)
        if scan.serpentine and row % 2:
            row_xs.reverse()
        for angle_x in row_xs:
            targets = _targets_for_mode(
                geometry,
                reference_steps,
                scan.offset_x_mm,
                scan.offset_y_mm,
                angle_x,
                angle_y,
                scan.solve_mode,
            )
            points.append(
                ScanPoint(
                    index=index,
                    mode=scan.mode,
                    angle_x_urad=angle_x,
                    angle_y_urad=angle_y,
                    offset_x_mm=scan.offset_x_mm,
                    offset_y_mm=scan.offset_y_mm,
                    targets=targets,
                )
            )
            index += 1
    return points


def build_spiral_scan_points(config: AppConfig, reference_steps: dict[str, float]) -> list[ScanPoint]:
    coords = rectangular_spiral(config.scan.spiral_step_x, config.scan.spiral_step_y, config.scan.spiral_turns)
    points: list[ScanPoint] = []
    for index, (dx, dy) in enumerate(coords):
        targets = MotorTargets(
            m1_horizontal=reference_steps["m1_horizontal"],
            m1_vertical=reference_steps["m1_vertical"],
            m2_horizontal=reference_steps["m2_horizontal"] + dx,
            m2_vertical=reference_steps["m2_vertical"] + dy,
        )
        points.append(
            ScanPoint(
                index=index,
                mode="mirror2_spiral",
                angle_x_urad=math.nan,
                angle_y_urad=math.nan,
                offset_x_mm=math.nan,
                offset_y_mm=math.nan,
                targets=targets,
            )
        )
    return points


def _targets_for_mode(
    geometry: LaserMirrorGeometry,
    reference_steps: dict[str, float],
    offset_x_mm: float,
    offset_y_mm: float,
    angle_x_urad: float,
    angle_y_urad: float,
    solve_mode: Literal["two_mirror_target", "mirror1_primary", "mirror2_primary"],
) -> MotorTargets:
    if solve_mode == "two_mirror_target":
        return geometry.absolute_targets_from_reference(reference_steps, offset_x_mm, offset_y_mm, angle_x_urad, angle_y_urad)
    if solve_mode == "mirror1_primary":
        solved_x = geometry.solve_mirror2_for_fixed_offset(angle_x_urad, offset_x_mm, "x")
        solved_y = geometry.solve_mirror2_for_fixed_offset(angle_y_urad, offset_y_mm, "y")
    else:
        solved_x = geometry.solve_mirror1_for_fixed_offset(angle_x_urad, offset_x_mm, "x")
        solved_y = geometry.solve_mirror1_for_fixed_offset(angle_y_urad, offset_y_mm, "y")
    delta = MotorTargets(
        m1_horizontal=geometry.urad_to_steps(solved_x.mirror1_urad, "x", 1),
        m1_vertical=geometry.urad_to_steps(solved_y.mirror1_urad, "y", 1),
        m2_horizontal=geometry.urad_to_steps(solved_x.mirror2_urad, "x", 2),
        m2_vertical=geometry.urad_to_steps(solved_y.mirror2_urad, "y", 2),
    )
    return MotorTargets(
        m1_horizontal=reference_steps["m1_horizontal"] + delta.m1_horizontal,
        m1_vertical=reference_steps["m1_vertical"] + delta.m1_vertical,
        m2_horizontal=reference_steps["m2_horizontal"] + delta.m2_horizontal,
        m2_vertical=reference_steps["m2_vertical"] + delta.m2_vertical,
    )


def choose_best_point(measurements: list[MeasurementRecord], objective: str) -> BestPointRecommendation | None:
    if not measurements:
        return None
    best = min(measurements, key=lambda row: row.signal_average) if objective == "min" else max(measurements, key=lambda row: row.signal_average)
    return BestPointRecommendation(
        objective=objective,
        signal_label=best.signal_label,
        signal_value=best.signal_average,
        point_index=best.point_index,
        angle_x_urad=best.angle_x_urad,
        angle_y_urad=best.angle_y_urad,
        offset_x_mm=best.offset_x_mm,
        offset_y_mm=best.offset_y_mm,
        targets=MotorTargets(
            m1_horizontal=best.commanded_m1_horizontal,
            m1_vertical=best.commanded_m1_vertical,
            m2_horizontal=best.commanded_m2_horizontal,
            m2_vertical=best.commanded_m2_vertical,
        ),
    )


class ScanRunner:
    def __init__(
        self,
        config: AppConfig,
        geometry: LaserMirrorGeometry,
        controller: MirrorController,
        signal_backend,
        debug: Callable[[str], None],
        output_root: Path,
    ):
        self.config = config
        self.geometry = geometry
        self.controller = controller
        self.signal_backend = signal_backend
        self.debug = debug
        self.output_root = output_root
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self.measurements: list[MeasurementRecord] = []
        self.command_log: list[CommandRecord] = []
        self.session_dir: Path | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_stop(self) -> None:
        self._stop_requested.set()

    def clear_stop(self) -> None:
        self._stop_requested.clear()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def build_preview(self, points: list[ScanPoint], reference_steps: dict[str, float]) -> list[dict[str, object]]:
        current = dict(reference_steps)
        rows: list[dict[str, object]] = []
        for point in points:
            targets = point.targets.as_dict()
            plan = self.controller.plan_absolute_move(current, targets)
            max_layers = max((len(commands) for commands in plan.values()), default=0)
            max_delta = max((abs(targets[key] - reference_steps[key]) for key in targets), default=0.0)
            rows.append(
                {
                    "index": point.index,
                    "mode": point.mode,
                    "angle_x_urad": point.angle_x_urad,
                    "angle_y_urad": point.angle_y_urad,
                    "targets": targets,
                    "max_delta_from_reference": max_delta,
                    "estimated_ramp_layers": max_layers,
                }
            )
            current = dict(targets)
        return rows

    def start(
        self,
        mode: Literal["angle", "spiral"],
        context: ScanContext,
        on_measurement: Callable[[MeasurementRecord], None],
        on_finish: Callable[[Path, BestPointRecommendation | None], None],
    ) -> None:
        if self.is_running():
            raise RuntimeError("Scan already running")
        self.measurements.clear()
        self.command_log.clear()
        self.clear_stop()
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.session_dir = self.output_root / ("laser_mirror_" + mode + "_" + run_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        points = build_angle_scan_points(self.config, self.geometry, context.reference_steps) if mode == "angle" else build_spiral_scan_points(self.config, context.reference_steps)
        self._thread = threading.Thread(
            target=self._run,
            args=(points, context, on_measurement, on_finish),
            daemon=True,
        )
        self._thread.start()

    def _run(
        self,
        points: list[ScanPoint],
        context: ScanContext,
        on_measurement: Callable[[MeasurementRecord], None],
        on_finish: Callable[[Path, BestPointRecommendation | None], None],
    ) -> None:
        assert self.session_dir is not None
        start = time.perf_counter()
        total_points = len(points)
        self.debug(f"Starting {points[0].mode if points else 'scan'} with {total_points} points. Session dir: {self.session_dir}")
        for point in points:
            if self._stop_requested.is_set():
                self.debug("Stop requested before next point. Ending scan gracefully.")
                break
            targets = point.targets.as_dict()
            self.debug(
                "Point "
                f"{point.index + 1}/{total_points}: "
                f"angle=({point.angle_x_urad:.2f}, {point.angle_y_urad:.2f}) µrad "
                f"offset=({point.offset_x_mm:.3f}, {point.offset_y_mm:.3f}) mm "
                f"targets={{{', '.join(f'{key}={value:.2f}' for key, value in targets.items())}}}"
            )
            moved = self.controller.move_absolute_group(
                targets,
                request_stop=self._stop_requested.is_set,
                command_logger=self.command_log.append,
                command_path=self.session_dir / "last_move_plan.json",
            )
            if not moved:
                self.debug(f"Move aborted at point {point.index + 1}/{total_points}.")
                break
            if hasattr(self.signal_backend, "update_target") and point.angle_x_urad == point.angle_x_urad:
                self.signal_backend.update_target(point.angle_x_urad, point.angle_y_urad)
            self.debug(f"Point {point.index + 1}/{total_points}: move complete, dwelling for {max(0.0, self.config.scan.dwell_s):.2f} s.")
            time.sleep(max(0.0, self.config.scan.dwell_s))
            samples: list[float] = []
            for _ in range(max(1, self.config.scan.p1_samples_per_point)):
                reading = self.signal_backend.read()
                if reading.ok:
                    samples.append(reading.value)
                time.sleep(0.02)
            average = sum(samples) / len(samples) if samples else math.nan
            variance = 0.0 if len(samples) <= 1 else sum((value - average) ** 2 for value in samples) / len(samples)
            rbv = self.controller.current_steps()
            measurement = MeasurementRecord(
                point_index=point.index,
                mode=point.mode,
                elapsed_s=time.perf_counter() - start,
                angle_x_urad=point.angle_x_urad,
                angle_y_urad=point.angle_y_urad,
                offset_x_mm=point.offset_x_mm,
                offset_y_mm=point.offset_y_mm,
                signal_label=context.signal_label,
                signal_pv=context.signal_pv,
                signal_value=samples[-1] if samples else math.nan,
                signal_average=average,
                signal_std=math.sqrt(variance),
                samples_used=len(samples),
                commanded_m1_horizontal=point.targets.m1_horizontal,
                commanded_m1_vertical=point.targets.m1_vertical,
                commanded_m2_horizontal=point.targets.m2_horizontal,
                commanded_m2_vertical=point.targets.m2_vertical,
                rbv_m1_horizontal=rbv["m1_horizontal"],
                rbv_m1_vertical=rbv["m1_vertical"],
                rbv_m2_horizontal=rbv["m2_horizontal"],
                rbv_m2_vertical=rbv["m2_vertical"],
            )
            self.measurements.append(measurement)
            self.debug(
                f"Point {point.index + 1}/{total_points}: "
                f"{context.signal_label} avg={average:.6g} std={math.sqrt(variance):.6g} "
                f"from {len(samples)} samples | "
                f"RBV m1h={rbv['m1_horizontal']:.2f} m1v={rbv['m1_vertical']:.2f} "
                f"m2h={rbv['m2_horizontal']:.2f} m2v={rbv['m2_vertical']:.2f}"
            )
            on_measurement(measurement)
        self._write_session(points)
        best = choose_best_point(self.measurements, self.config.scan.objective)
        if best is not None:
            self.debug(
                f"Scan finished. Best point: index={best.point_index} "
                f"angle=({best.angle_x_urad:.2f}, {best.angle_y_urad:.2f}) µrad "
                f"{best.signal_label}={best.signal_value:.6g} objective={best.objective}"
            )
        else:
            self.debug("Scan finished with no valid best point.")
        on_finish(self.session_dir, best)

    def _write_session(self, points: list[ScanPoint]) -> None:
        assert self.session_dir is not None
        (self.session_dir / "config.json").write_text(json.dumps(asdict(self.config), indent=2, sort_keys=True))
        (self.session_dir / "plan.json").write_text(json.dumps([asdict(point) for point in points], indent=2))
        with (self.session_dir / "commands.jsonl").open("w", encoding="utf-8") as handle:
            for record in self.command_log:
                handle.write(json.dumps(asdict(record)) + "\n")
        with (self.session_dir / "measurements.csv").open("w", newline="", encoding="utf-8") as handle:
            rows = [asdict(measurement) for measurement in self.measurements]
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        best = choose_best_point(self.measurements, self.config.scan.objective)
        if best is not None:
            (self.session_dir / "best_point.json").write_text(json.dumps(asdict(best), indent=2, sort_keys=True))
