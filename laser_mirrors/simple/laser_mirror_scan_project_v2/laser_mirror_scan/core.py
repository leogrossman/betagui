from __future__ import annotations

import csv
import datetime as dt
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal


MOTOR_PVS = {
    "m1_vertical": "MNF1C1L2RP",
    "m1_horizontal": "MNF1C2L2RP",
    "m2_vertical": "MNF2C1L2RP",
    "m2_horizontal": "MNF2C2L2RP",
}


@dataclass
class GeometryConfig:
    """Legacy two-mirror optical geometry.

    Distances:
    - mirror_distance_mm: M1 -> M2
    - undulator_distance_mm: M2 -> undulator center

    Step scales are the legacy calibration in µrad mirror angle per motor step.
    EPICS motor records themselves use steps.
    """

    mirror_distance_mm: float = 2285.0
    undulator_distance_mm: float = 6010.0
    horizontal_urad_per_step: float = 2.75
    vertical_urad_per_step: float = 1.89
    mirror2_horizontal_sign: float = -1.0
    mirror2_vertical_sign: float = 1.0


@dataclass
class UndulatorTarget:
    offset_mm: float
    angle_urad: float


@dataclass
class MirrorAngles:
    m1_urad: float
    m2_urad: float


@dataclass
class MotorTargets:
    m1_horizontal: float
    m1_vertical: float
    m2_horizontal: float
    m2_vertical: float


@dataclass
class ScanPoint:
    index: int
    angle_h_urad: float
    angle_v_urad: float
    offset_h_mm: float
    offset_v_mm: float
    motor_targets: MotorTargets
    mode: str


@dataclass
class Measurement:
    timestamp: str
    index: int
    mode: str
    angle_h_urad: float
    angle_v_urad: float
    offset_h_mm: float
    offset_v_mm: float
    target_m1_horizontal: float
    target_m1_vertical: float
    target_m2_horizontal: float
    target_m2_vertical: float
    rbv_m1_horizontal: float
    rbv_m1_vertical: float
    rbv_m2_horizontal: float
    rbv_m2_vertical: float
    p1: float
    samples: int


class BeamGeometry:
    """Geometry transform and schematic ray model.

    Convention:
    - horizontal and vertical are independent 2D steering planes.
    - mirror angle changes deflect the beam by twice the mirror angle.
    - formulas follow the legacy MirrorControlCalculate.py transform.

    The app uses the transform as relative deltas around a captured reference
    motor state. This is safest because EPICS motor coordinates are step values.
    """

    def __init__(self, cfg: GeometryConfig | None = None):
        self.cfg = cfg or GeometryConfig()

    def target_to_mirror_angles(self, target: UndulatorTarget, plane: Literal["horizontal", "vertical"]) -> MirrorAngles:
        md = self.cfg.mirror_distance_mm
        ud = self.cfg.undulator_distance_mm

        offset_angle = -target.offset_mm / (2.0 * md) * 1e6
        m1_from_angle = target.angle_urad / 2.0 * ud / md
        m2_from_angle = target.angle_urad / 2.0 + m1_from_angle

        m1 = m1_from_angle + offset_angle
        m2 = m2_from_angle + offset_angle

        if plane == "horizontal":
            m2 *= self.cfg.mirror2_horizontal_sign
        elif plane == "vertical":
            m2 *= self.cfg.mirror2_vertical_sign
        else:
            raise ValueError(f"unknown plane {plane!r}")

        return MirrorAngles(m1, m2)

    def mirror_angles_to_target(self, angles: MirrorAngles, plane: Literal["horizontal", "vertical"]) -> UndulatorTarget:
        md = self.cfg.mirror_distance_mm
        ud = self.cfg.undulator_distance_mm
        m1 = angles.m1_urad
        m2 = angles.m2_urad
        if plane == "horizontal":
            m2 *= self.cfg.mirror2_horizontal_sign
        elif plane == "vertical":
            m2 *= self.cfg.mirror2_vertical_sign
        angle = 2.0 * (m2 - m1)
        offset_mm = (angle * ud - 2.0 * md * m1) / 1e6
        return UndulatorTarget(offset_mm=offset_mm, angle_urad=angle)

    def urad_to_steps(self, angle_urad: float, plane: Literal["horizontal", "vertical"]) -> float:
        scale = self.cfg.horizontal_urad_per_step if plane == "horizontal" else self.cfg.vertical_urad_per_step
        return angle_urad / scale

    def steps_to_urad(self, steps: float, plane: Literal["horizontal", "vertical"]) -> float:
        scale = self.cfg.horizontal_urad_per_step if plane == "horizontal" else self.cfg.vertical_urad_per_step
        return steps * scale

    def target_to_step_deltas(
        self,
        offset_h_mm: float,
        offset_v_mm: float,
        angle_h_urad: float,
        angle_v_urad: float,
    ) -> MotorTargets:
        h = self.target_to_mirror_angles(UndulatorTarget(offset_h_mm, angle_h_urad), "horizontal")
        v = self.target_to_mirror_angles(UndulatorTarget(offset_v_mm, angle_v_urad), "vertical")
        return MotorTargets(
            m1_horizontal=self.urad_to_steps(h.m1_urad, "horizontal"),
            m2_horizontal=self.urad_to_steps(h.m2_urad, "horizontal"),
            m1_vertical=self.urad_to_steps(v.m1_urad, "vertical"),
            m2_vertical=self.urad_to_steps(v.m2_urad, "vertical"),
        )

    def absolute_targets_from_reference(
        self,
        reference_steps: dict[str, float],
        offset_h_mm: float,
        offset_v_mm: float,
        angle_h_urad: float,
        angle_v_urad: float,
    ) -> MotorTargets:
        d = self.target_to_step_deltas(offset_h_mm, offset_v_mm, angle_h_urad, angle_v_urad)
        return MotorTargets(
            m1_horizontal=reference_steps["m1_horizontal"] + d.m1_horizontal,
            m2_horizontal=reference_steps["m2_horizontal"] + d.m2_horizontal,
            m1_vertical=reference_steps["m1_vertical"] + d.m1_vertical,
            m2_vertical=reference_steps["m2_vertical"] + d.m2_vertical,
        )

    def ray_polyline(self, angle_urad: float, offset_mm: float = 0.0) -> list[tuple[float, float]]:
        """Return a simple ray polyline in physical mm coordinates.

        x coordinates:
        - laser input / upstream: -0.35*Mdist
        - M1: 0
        - M2: Mdist
        - undulator: Mdist + Udist

        y coordinates are schematic beam offsets in mm.
        The final segment reaches the specified undulator offset with final
        slope equal to angle_urad.
        """
        md = self.cfg.mirror_distance_mm
        ud = self.cfg.undulator_distance_mm
        x0 = -0.35 * md
        x1 = 0.0
        x2 = md
        xu = md + ud

        # Back-propagate desired final ray from undulator to M2.
        final_slope = angle_urad * 1e-6
        y_u = offset_mm
        y2 = y_u - final_slope * ud
        # Use straight incoming ray to M1 at zero for a clean schematic.
        y1 = 0.0
        y0 = 0.0
        return [(x0, y0), (x1, y1), (x2, y2), (xu, y_u)]


def linspace(center: float, span: float, n: int) -> list[float]:
    n = max(1, int(n))
    if n == 1:
        return [float(center)]
    lo = center - span / 2.0
    hi = center + span / 2.0
    return [lo + i * (hi - lo) / (n - 1) for i in range(n)]


def rectangular_spiral(step_h: float, step_v: float, turns: int) -> list[tuple[float, float]]:
    h, v = 0.0, 0.0
    points = [(h, v)]
    directions = [(step_h, 0.0), (0.0, step_v), (-step_h, 0.0), (0.0, -step_v)]
    segment_length = 1
    direction_index = 0
    increases = 0
    for _ in range(max(0, turns)):
        dh, dv = directions[direction_index]
        for _ in range(segment_length):
            h += dh
            v += dv
            points.append((h, v))
        direction_index = (direction_index + 1) % 4
        increases += 1
        if increases % 2 == 0:
            segment_length += 1
    return points


def build_angle_grid(
    geometry: BeamGeometry,
    reference_steps: dict[str, float],
    center_h_urad: float,
    center_v_urad: float,
    span_h_urad: float,
    span_v_urad: float,
    points_h: int,
    points_v: int,
    offset_h_mm: float,
    offset_v_mm: float,
    mode: Literal["both_2d", "horizontal_only", "vertical_only"],
    serpentine: bool = True,
) -> list[ScanPoint]:
    hs = linspace(center_h_urad, span_h_urad, points_h)
    vs = linspace(center_v_urad, span_v_urad, points_v)
    if mode == "horizontal_only":
        vs = [center_v_urad]
    if mode == "vertical_only":
        hs = [center_h_urad]

    points: list[ScanPoint] = []
    idx = 0
    for row, av in enumerate(vs):
        h_iter = list(hs)
        if serpentine and row % 2:
            h_iter.reverse()
        for ah in h_iter:
            targets = geometry.absolute_targets_from_reference(reference_steps, offset_h_mm, offset_v_mm, ah, av)
            points.append(ScanPoint(idx, ah, av, offset_h_mm, offset_v_mm, targets, mode))
            idx += 1
    return points


def build_mirror2_spiral(
    reference_steps: dict[str, float],
    center_h_steps: float,
    center_v_steps: float,
    step_h_steps: float,
    step_v_steps: float,
    turns: int,
) -> list[ScanPoint]:
    coords = rectangular_spiral(step_h_steps, step_v_steps, turns)
    points: list[ScanPoint] = []
    for idx, (dh, dv) in enumerate(coords):
        targets = MotorTargets(
            m1_horizontal=reference_steps["m1_horizontal"],
            m1_vertical=reference_steps["m1_vertical"],
            m2_horizontal=center_h_steps + dh,
            m2_vertical=center_v_steps + dv,
        )
        points.append(ScanPoint(idx, dh, dv, math.nan, math.nan, targets, "mirror2_spiral"))
    return points


def save_measurements_csv(path: Path, rows: Iterable[Measurement]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


SIGNAL_PV_CANDIDATES = {
    "simulated_p1": "",
    "p1_h1p1_raw": "SCOPE1ZULP:h1p1:rdAmpl",
    "p1_h1p2_raw": "SCOPE1ZULP:h1p2:rdAmpl",
    "p1_h1p3_raw": "SCOPE1ZULP:h1p3:rdAmpl",
    "p1_h1p1_avg": "SCOPE1ZULP:h1p1:rdAmplAv",
    "qpd00_sigma_x": "QPD00:SigmaX",
    "qpd00_sigma_y": "QPD00:SigmaY",
    "qpd01_sigma_x": "QPD01:SigmaX",
    "qpd01_sigma_y": "QPD01:SigmaY",
}


@dataclass
class MotionConfig:
    """Safety throttling for EPICS motor writes.

    EPICS motor records can accept immediate large .VAL changes, but the
    underlying controller can become unstable if too many commands are sent too
    quickly. Use ramped moves and dwell between points during commissioning.
    """

    max_step_per_put: float = 50.0
    inter_put_delay_s: float = 0.25
    wait_timeout_s: float = 30.0
    settle_s: float = 0.2
    max_delta_from_reference: float = 500.0


def ramp_values(start: float, stop: float, max_step: float) -> list[float]:
    """Return monotonic intermediate values from start to stop inclusive."""
    max_step = abs(float(max_step))
    if max_step <= 0:
        return [float(stop)]
    delta = float(stop) - float(start)
    if abs(delta) <= max_step:
        return [float(stop)]
    n = int(math.ceil(abs(delta) / max_step))
    return [float(start) + delta * (i / n) for i in range(1, n + 1)]


class SimP1:
    def __init__(self):
        self.center_h = 75.0
        self.center_v = -40.0
        self.width_h = 140.0
        self.width_v = 110.0
        self.noise = 0.02

    def read(self, angle_h: float, angle_v: float) -> float:
        dh = (angle_h - self.center_h) / self.width_h
        dv = (angle_v - self.center_v) / self.width_v
        return max(0.0, math.exp(-(dh * dh + dv * dv)) + random.uniform(-self.noise, self.noise))


def now() -> str:
    return dt.datetime.now().isoformat(timespec="milliseconds")
