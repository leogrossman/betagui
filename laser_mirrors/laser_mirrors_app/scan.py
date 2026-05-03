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
from .models import BestPointRecommendation, CommandRecord, MeasurementRecord, MirrorAngles, MotorTargets, ScanPoint, UndulatorTarget


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
                    group_index=row,
                    group_label=f"row {row + 1}",
                )
            )
            index += 1
    return points


def build_overlap_scan_points(
    geometry: LaserMirrorGeometry,
    reference_steps: dict[str, float],
    axis: Literal["horizontal", "vertical"],
    position_target: Literal["mirror1", "mirror2"],
    position_points: int,
    position_step_steps: float,
    angle_points: int,
    angle_span_urad: float,
    solve_mode: Literal["mirror1_primary", "mirror2_primary", "two_mirror_target"],
) -> list[ScanPoint]:
    del solve_mode  # The overlap-strip scan is defined directly in mirror-angle space.
    axis_code = "x" if axis == "horizontal" else "y"
    motor_axis = "horizontal" if axis == "horizontal" else "vertical"
    fixed_mirror = 1 if position_target == "mirror1" else 2
    sweep_mirror = 2 if fixed_mirror == 1 else 1
    fixed_key = f"m{fixed_mirror}_{motor_axis}"
    sweep_key = f"m{sweep_mirror}_{motor_axis}"
    position_span = max(0.0, float(position_step_steps)) * max(0, int(position_points) - 1)
    position_offsets = sorted(
        linspace(0.0, position_span, max(1, int(position_points))),
        key=lambda value: geometry.steps_to_angle_delta(value, axis_code, fixed_mirror),
    )
    sweep_angles = sorted(linspace(0.0, float(angle_span_urad), max(1, int(angle_points))))
    points: list[ScanPoint] = []
    index = 0
    for group_index, position_offset_steps in enumerate(position_offsets):
        fixed_angle_urad = geometry.steps_to_angle_delta(position_offset_steps, axis_code, fixed_mirror)
        fixed_target_steps = reference_steps[fixed_key] + position_offset_steps
        for sweep_angle_urad in sweep_angles:
            sweep_target_steps = reference_steps[sweep_key] + geometry.urad_to_steps(sweep_angle_urad, axis_code, sweep_mirror)
            targets = dict(reference_steps)
            targets[fixed_key] = fixed_target_steps
            targets[sweep_key] = sweep_target_steps
            if fixed_mirror == 1:
                mirror1_angle_urad = fixed_angle_urad
                mirror2_angle_urad = sweep_angle_urad
            else:
                mirror1_angle_urad = sweep_angle_urad
                mirror2_angle_urad = fixed_angle_urad
            points.append(
                ScanPoint(
                    index=index,
                    mode=f"overlap_{axis}",
                    angle_x_urad=mirror1_angle_urad,
                    angle_y_urad=mirror2_angle_urad,
                    offset_x_mm=math.nan,
                    offset_y_mm=math.nan,
                    targets=MotorTargets(**targets),
                    group_index=group_index,
                    group_label=f"strip {group_index + 1}",
                )
            )
            index += 1
    return points

def build_spiral_scan_points(
    config: AppConfig,
    reference_steps: dict[str, float],
    target_pair: str | None = None,
    center_targets: MotorTargets | None = None,
    step_scale: float = 1.0,
) -> list[ScanPoint]:
    coords = rectangular_spiral(config.scan.spiral_step_x, config.scan.spiral_step_y, config.scan.spiral_turns)
    target_pair = target_pair or config.scan.spiral_target
    center = center_targets.as_dict() if center_targets is not None else dict(reference_steps)
    points: list[ScanPoint] = []
    for index, (dx, dy) in enumerate(coords):
        dx *= step_scale
        dy *= step_scale
        targets_dict = dict(center)
        if target_pair == "mirror1":
            targets_dict["m1_horizontal"] = center["m1_horizontal"] + dx
            targets_dict["m1_vertical"] = center["m1_vertical"] + dy
        else:
            targets_dict["m2_horizontal"] = center["m2_horizontal"] + dx
            targets_dict["m2_vertical"] = center["m2_vertical"] + dy
        targets = MotorTargets(**targets_dict)
        points.append(
            ScanPoint(
                index=index,
                mode=f"{target_pair}_spiral",
                angle_x_urad=math.nan,
                angle_y_urad=math.nan,
                offset_x_mm=math.nan,
                offset_y_mm=math.nan,
                targets=targets,
                group_index=index,
                group_label=f"spiral {target_pair}",
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
    spacing_candidates: list[float] = []
    spiral_rows = [
        row for row in measurements if row.mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine")
    ]
    for row in spiral_rows:
        x0 = row.commanded_m1_horizontal if row.mode.startswith("mirror1") else row.commanded_m2_horizontal
        y0 = row.commanded_m1_vertical if row.mode.startswith("mirror1") else row.commanded_m2_vertical
        distances = []
        for other in spiral_rows:
            if other.mode != row.mode or other.point_index == row.point_index:
                continue
            x1 = other.commanded_m1_horizontal if other.mode.startswith("mirror1") else other.commanded_m2_horizontal
            y1 = other.commanded_m1_vertical if other.mode.startswith("mirror1") else other.commanded_m2_vertical
            distance = math.hypot(x1 - x0, y1 - y0)
            if distance > 0:
                distances.append(distance)
        if distances:
            spacing_candidates.append(min(distances))
    typical_spacing = min(spacing_candidates) if spacing_candidates else 1.0
    scored_rows: list[tuple[float, MeasurementRecord]] = []
    maximizing = objective != "min"
    for row in measurements:
        if row.mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine"):
            x0 = row.commanded_m1_horizontal if row.mode.startswith("mirror1") else row.commanded_m2_horizontal
            y0 = row.commanded_m1_vertical if row.mode.startswith("mirror1") else row.commanded_m2_vertical
            neighbors: list[tuple[float, MeasurementRecord]] = []
            for other in measurements:
                if other.mode != row.mode:
                    continue
                x1 = other.commanded_m1_horizontal if other.mode.startswith("mirror1") else other.commanded_m2_horizontal
                y1 = other.commanded_m1_vertical if other.mode.startswith("mirror1") else other.commanded_m2_vertical
                distance = math.hypot(x1 - x0, y1 - y0)
                neighbors.append((distance, other))
            neighbors.sort(key=lambda item: item[0])
            local_rows = [other for _distance, other in neighbors[:5]]
            local_values = [other.signal_average for other in local_rows]
            local_mean = sum(local_values) / len(local_values) if local_values else row.signal_average
            ring_values = [other.signal_average for other in local_rows[1:]]
            ring_distances = [distance for distance, _other in neighbors[1:5] if distance > 0]
            if ring_values:
                ring_mean = sum(ring_values) / len(ring_values)
                if maximizing:
                    prominence = row.signal_average - ring_mean
                else:
                    prominence = ring_mean - row.signal_average
            else:
                prominence = 0.0
            distance_penalty = 0.0
            if ring_distances:
                distance_penalty = 0.2 * (sum(ring_distances) / len(ring_distances)) / max(typical_spacing, 1e-9)
            score = (local_mean + 0.35 * prominence - distance_penalty) if maximizing else (local_mean - 0.35 * prominence + distance_penalty)
        else:
            local = [other.signal_average for other in measurements if other.mode == row.mode]
            local_mean = sum(local) / len(local) if local else row.signal_average
            score = row.signal_average if len(local) <= 2 else (row.signal_average * 0.65 + local_mean * 0.35)
        scored_rows.append((score, row))
    best = min(scored_rows, key=lambda item: item[0])[1] if objective == "min" else max(scored_rows, key=lambda item: item[0])[1]
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
        self.last_error: str | None = None

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
        self.last_error = None
        self.clear_stop()
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.session_dir = self.output_root / ("laser_mirror_" + mode + "_" + run_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        if mode == "angle":
            points = build_angle_scan_points(self.config, self.geometry, context.reference_steps)
        else:
            points = build_spiral_scan_points(self.config, context.reference_steps)
        self._thread = threading.Thread(
            target=self._run,
            args=(points, context, on_measurement, on_finish),
            daemon=True,
        )
        self._thread.start()

    def start_custom(
        self,
        mode: str,
        points: list[ScanPoint],
        context: ScanContext,
        on_measurement: Callable[[MeasurementRecord], None],
        on_finish: Callable[[Path, BestPointRecommendation | None], None],
    ) -> None:
        if self.is_running():
            raise RuntimeError("Scan already running")
        self.measurements.clear()
        self.command_log.clear()
        self.last_error = None
        self.clear_stop()
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.session_dir = self.output_root / ("laser_mirror_" + mode + "_" + run_id)
        self.session_dir.mkdir(parents=True, exist_ok=True)
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
        try:
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
                dwell_s = max(0.0, self.config.scan.dwell_s)
                self.debug(f"Point {point.index + 1}/{total_points}: move complete, dwelling for {dwell_s:.2f} s.")
                end_time = time.perf_counter() + dwell_s
                while time.perf_counter() < end_time:
                    if self._stop_requested.is_set():
                        self.debug("Stop requested during dwell. Ending scan gracefully after current move.")
                        break
                    time.sleep(min(0.05, max(0.0, end_time - time.perf_counter())))
                if self._stop_requested.is_set():
                    break
                samples: list[float] = []
                for _ in range(max(1, self.config.scan.p1_samples_per_point)):
                    if self._stop_requested.is_set():
                        self.debug("Stop requested during sampling. Ending scan gracefully.")
                        break
                    reading = self.signal_backend.read()
                    if reading.ok:
                        samples.append(reading.value)
                    time.sleep(0.02)
                if self._stop_requested.is_set() and not samples:
                    break
                average = sum(samples) / len(samples) if samples else math.nan
                variance = 0.0 if len(samples) <= 1 else sum((value - average) ** 2 for value in samples) / len(samples)
                rbv = self.controller.current_steps()
                measurement = MeasurementRecord(
                    point_index=point.index,
                    mode=point.mode,
                    group_index=point.group_index,
                    group_label=point.group_label,
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
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            self.debug(f"Scan aborted with error: {exc}")
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
