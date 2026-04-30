from __future__ import annotations

import csv
import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .geometry import LaserMirrorGeometry
from .hardware import MirrorBackend, P1Backend, command_record
from .models import MeasurementRecord, MirrorAngles, ScanPoint, UndulatorTarget


def build_scan_grid(config: AppConfig, offset_x_mm: float, offset_y_mm: float) -> list[ScanPoint]:
    scan = config.scan
    x_values = _linspace(scan.center_angle_x_urad - scan.span_angle_x_urad / 2.0, scan.center_angle_x_urad + scan.span_angle_x_urad / 2.0, scan.points_x)
    y_values = _linspace(scan.center_angle_y_urad - scan.span_angle_y_urad / 2.0, scan.center_angle_y_urad + scan.span_angle_y_urad / 2.0, scan.points_y)
    points: list[ScanPoint] = []
    idx = 0
    for row_index, y_value in enumerate(y_values):
        x_iter = list(x_values)
        if scan.serpentine and row_index % 2 == 1:
            x_iter.reverse()
        for x_value in x_iter:
            points.append(
                ScanPoint(
                    index=idx,
                    target_x=UndulatorTarget(offset_mm=offset_x_mm, angle_urad=x_value),
                    target_y=UndulatorTarget(offset_mm=offset_y_mm, angle_urad=y_value),
                    note=f"grid[{row_index}]",
                )
            )
            idx += 1
    return points


def _linspace(start: float, stop: float, count: int) -> list[float]:
    if count <= 1:
        return [start]
    step = (stop - start) / (count - 1)
    return [start + i * step for i in range(count)]


@dataclass
class ScanContext:
    angles_x: MirrorAngles
    angles_y: MirrorAngles
    offset_x_mm: float
    offset_y_mm: float
    requested_x: UndulatorTarget
    requested_y: UndulatorTarget


class ScanRunner:
    """Runs the mirror-angle scan in a background thread."""

    def __init__(
        self,
        config: AppConfig,
        geometry: LaserMirrorGeometry,
        mirror_backend: MirrorBackend,
        p1_backend: P1Backend,
        debug: Callable[[str], None],
        output_root: Path,
    ):
        self.config = config
        self.geometry = geometry
        self.mirror_backend = mirror_backend
        self.p1_backend = p1_backend
        self.debug = debug
        self.output_root = output_root
        self.command_log: list[dict[str, object]] = []
        self.measurements: list[MeasurementRecord] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_id = ""

    @property
    def session_id(self) -> str:
        return self._session_id

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_stop(self) -> None:
        self.debug("Stop requested for scan runner.")
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def start(
        self,
        context: ScanContext,
        on_measurement: Callable[[MeasurementRecord], None],
        on_finish: Callable[[Path], None],
    ) -> None:
        if self.is_running():
            raise RuntimeError("Scan already running")
        self._stop.clear()
        self.command_log.clear()
        self.measurements.clear()
        self._session_id = f"laser_mirror_scan_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self._thread = threading.Thread(
            target=self._run,
            args=(context, on_measurement, on_finish),
            daemon=True,
        )
        self._thread.start()

    def _run(
        self,
        context: ScanContext,
        on_measurement: Callable[[MeasurementRecord], None],
        on_finish: Callable[[Path], None],
    ) -> None:
        start = time.perf_counter()
        points = build_scan_grid(self.config, context.offset_x_mm, context.offset_y_mm)
        angle_state_x = MirrorAngles(context.angles_x.mirror1_urad, context.angles_x.mirror2_urad)
        angle_state_y = MirrorAngles(context.angles_y.mirror1_urad, context.angles_y.mirror2_urad)
        for point in points:
            if self._stop.is_set():
                break
            target_angles_x, effective_target_x = self._resolve_plane_target(
                point.target_x, context.requested_x, angle_state_x, axis="x"
            )
            target_angles_y, effective_target_y = self._resolve_plane_target(
                point.target_y, context.requested_y, angle_state_y, axis="y"
            )
            batch_id = uuid.uuid4().hex[:8]
            self._move_to_target("x", angle_state_x, target_angles_x, batch_id)
            self._move_to_target("y", angle_state_y, target_angles_y, batch_id)
            angle_state_x = target_angles_x
            angle_state_y = target_angles_y
            if hasattr(self.p1_backend, "update_target"):
                self.p1_backend.update_target(effective_target_x.angle_urad, effective_target_y.angle_urad)
            time.sleep(max(self.config.scan.dwell_s, 0.0))
            samples = []
            for _ in range(max(1, self.config.scan.p1_samples_per_point)):
                value = self.p1_backend.read()
                if value == value:
                    samples.append(value)
                time.sleep(0.02)
            p1_value = sum(samples) / len(samples) if samples else float("nan")
            record = MeasurementRecord(
                point_index=point.index,
                elapsed_s=time.perf_counter() - start,
                angle_x_urad=effective_target_x.angle_urad,
                angle_y_urad=effective_target_y.angle_urad,
                offset_x_mm=effective_target_x.offset_mm,
                offset_y_mm=effective_target_y.offset_mm,
                p1_value=p1_value,
                samples_used=len(samples),
                mirror1_x_urad=angle_state_x.mirror1_urad,
                mirror2_x_urad=angle_state_x.mirror2_urad,
                mirror1_y_urad=angle_state_y.mirror1_urad,
                mirror2_y_urad=angle_state_y.mirror2_urad,
                command_batch_id=batch_id,
            )
            self.measurements.append(record)
            on_measurement(record)
        session_dir = self._write_session()
        on_finish(session_dir)

    def _resolve_plane_target(
        self,
        scan_target: UndulatorTarget,
        requested_target: UndulatorTarget,
        current_angles: MirrorAngles,
        axis: str,
    ) -> tuple[MirrorAngles, UndulatorTarget]:
        """Translate the UI scan setting into actual mirror angles for one plane."""
        mode = self.config.scan.solve_mode
        if mode == "mirror1_primary":
            solved = self.geometry.solve_mirror2_for_fixed_offset(scan_target.angle_urad, requested_target.offset_mm, axis)
            effective = self.geometry.to_undulator_target(solved, axis)
            return solved, effective
        if mode == "mirror2_primary":
            solved = self.geometry.solve_mirror1_for_fixed_offset(scan_target.angle_urad, requested_target.offset_mm, axis)
            effective = self.geometry.to_undulator_target(solved, axis)
            return solved, effective
        target_angles = self.geometry.to_mirror_angles(scan_target, axis)
        return target_angles, scan_target

    def _move_to_target(self, axis: str, current: MirrorAngles, target: MirrorAngles, batch_id: str) -> None:
        delta_m1 = target.mirror1_urad - current.mirror1_urad
        delta_m2 = target.mirror2_urad - current.mirror2_urad
        steps_m1 = self.geometry.angle_delta_to_steps(delta_m1, axis, mirror_index=1)
        steps_m2 = self.geometry.angle_delta_to_steps(delta_m2, axis, mirror_index=2)
        if steps_m1:
            self.debug(f"command[{batch_id}] axis={axis} mirror=1 target_angle={target.mirror1_urad:.2f} urad -> steps={steps_m1}")
            self.mirror_backend.relative_move(axis, 1, steps_m1)
            self.command_log.append(command_record(self.mirror_backend.name, "relative_move", {"batch_id": batch_id, "axis": axis, "mirror": 1, "steps": steps_m1}).__dict__)
        if steps_m2:
            self.debug(f"command[{batch_id}] axis={axis} mirror=2 target_angle={target.mirror2_urad:.2f} urad -> steps={steps_m2}")
            self.mirror_backend.relative_move(axis, 2, steps_m2)
            self.command_log.append(command_record(self.mirror_backend.name, "relative_move", {"batch_id": batch_id, "axis": axis, "mirror": 2, "steps": steps_m2}).__dict__)

    def _write_session(self) -> Path:
        session_dir = self.output_root / self._session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "config.json").write_text(json.dumps({
            "geometry": self.config.geometry.__dict__,
            "controller": self.config.controller.__dict__,
            "scan": self.config.scan.__dict__,
        }, indent=2, sort_keys=True))
        with (session_dir / "commands.jsonl").open("w", newline="") as handle:
            for row in self.command_log:
                handle.write(json.dumps(row) + "\n")
        with (session_dir / "measurements.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(MeasurementRecord.__dataclass_fields__.keys()))
            writer.writeheader()
            for measurement in self.measurements:
                writer.writerow(measurement.__dict__)
        return session_dir
