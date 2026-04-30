from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .config import GeometryConfig
from .models import MirrorAngles, MotorTargets, UndulatorTarget


@dataclass(frozen=True)
class PlaneStepCalibration:
    mirror1_urad_per_step: float
    mirror2_urad_per_step: float


class LaserMirrorGeometry:
    """Translate between undulator-space targets and mirror/controller units.

    The transform is adapted from the legacy mirror calculator and the V3/V4
    EPICS scan prototypes. The key operating idea is:

    desired undulator offset + desired interaction angle
    -> mirror 1 / mirror 2 angular changes
    -> motor step changes via calibration
    -> absolute EPICS motor targets around a captured reference RBV state
    """

    def __init__(self, config: GeometryConfig):
        self.config = config
        self._x_steps = PlaneStepCalibration(
            mirror1_urad_per_step=config.horizontal_step_urad,
            mirror2_urad_per_step=config.horizontal_step_urad,
        )
        self._y_steps = PlaneStepCalibration(
            mirror1_urad_per_step=config.vertical_step_urad,
            mirror2_urad_per_step=config.vertical_step_urad,
        )

    def to_mirror_angles(self, target: UndulatorTarget, axis: Literal["x", "y"]) -> MirrorAngles:
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        offset_angle = -target.offset_mm / (2.0 * mdist) * 1e6
        m1_from_angle = target.angle_urad / 2.0 * udist / mdist
        m2_from_angle = target.angle_urad / 2.0 + m1_from_angle
        m1 = m1_from_angle + offset_angle
        m2 = m2_from_angle + offset_angle
        if axis == "x":
            m2 *= self.config.mirror2_x_sign
        else:
            m2 *= self.config.mirror2_y_sign
        return MirrorAngles(m1, m2)

    def to_undulator_target(self, angles: MirrorAngles, axis: Literal["x", "y"]) -> UndulatorTarget:
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        m1 = angles.mirror1_urad
        m2 = angles.mirror2_urad
        if axis == "x":
            m2 *= self.config.mirror2_x_sign
        else:
            m2 *= self.config.mirror2_y_sign
        angle = 2.0 * (m2 - m1)
        offset_mm = (angle * udist - 2.0 * mdist * m1) / 1e6
        return UndulatorTarget(offset_mm=offset_mm, angle_urad=angle)

    def solve_mirror2_for_fixed_offset(self, mirror1_urad: float, offset_mm: float, axis: Literal["x", "y"]) -> MirrorAngles:
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        sign = self.config.mirror2_x_sign if axis == "x" else self.config.mirror2_y_sign
        mirror2_signed = (offset_mm * 1e6 + 2.0 * (udist + mdist) * mirror1_urad) / (2.0 * udist)
        return MirrorAngles(mirror1_urad=mirror1_urad, mirror2_urad=mirror2_signed * sign)

    def solve_mirror1_for_fixed_offset(self, mirror2_urad: float, offset_mm: float, axis: Literal["x", "y"]) -> MirrorAngles:
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        sign = self.config.mirror2_x_sign if axis == "x" else self.config.mirror2_y_sign
        mirror2_signed = mirror2_urad * sign
        mirror1 = (2.0 * udist * mirror2_signed - offset_mm * 1e6) / (2.0 * (udist + mdist))
        return MirrorAngles(mirror1_urad=mirror1, mirror2_urad=mirror2_urad)

    def urad_to_steps(self, angle_urad: float, axis: Literal["x", "y"], mirror_index: int) -> float:
        calib = self._x_steps if axis == "x" else self._y_steps
        scale = calib.mirror1_urad_per_step if mirror_index == 1 else calib.mirror2_urad_per_step
        return angle_urad / scale

    def steps_to_urad(self, steps: float, axis: Literal["x", "y"], mirror_index: int) -> float:
        calib = self._x_steps if axis == "x" else self._y_steps
        scale = calib.mirror1_urad_per_step if mirror_index == 1 else calib.mirror2_urad_per_step
        return steps * scale

    def steps_to_angle_delta(self, steps: float, axis: Literal["x", "y"], mirror_index: int) -> float:
        return self.steps_to_urad(steps, axis, mirror_index)

    def angle_delta_to_steps(self, angle_delta_urad: float, axis: Literal["x", "y"], mirror_index: int) -> int:
        return int(round(self.urad_to_steps(angle_delta_urad, axis, mirror_index)))

    def target_to_step_deltas(
        self,
        offset_x_mm: float,
        offset_y_mm: float,
        angle_x_urad: float,
        angle_y_urad: float,
    ) -> MotorTargets:
        hx = self.to_mirror_angles(UndulatorTarget(offset_x_mm, angle_x_urad), "x")
        vy = self.to_mirror_angles(UndulatorTarget(offset_y_mm, angle_y_urad), "y")
        return MotorTargets(
            m1_horizontal=self.urad_to_steps(hx.mirror1_urad, "x", 1),
            m1_vertical=self.urad_to_steps(vy.mirror1_urad, "y", 1),
            m2_horizontal=self.urad_to_steps(hx.mirror2_urad, "x", 2),
            m2_vertical=self.urad_to_steps(vy.mirror2_urad, "y", 2),
        )

    def absolute_targets_from_reference(
        self,
        reference_steps: dict[str, float],
        offset_x_mm: float,
        offset_y_mm: float,
        angle_x_urad: float,
        angle_y_urad: float,
    ) -> MotorTargets:
        delta = self.target_to_step_deltas(offset_x_mm, offset_y_mm, angle_x_urad, angle_y_urad)
        return MotorTargets(
            m1_horizontal=reference_steps["m1_horizontal"] + delta.m1_horizontal,
            m1_vertical=reference_steps["m1_vertical"] + delta.m1_vertical,
            m2_horizontal=reference_steps["m2_horizontal"] + delta.m2_horizontal,
            m2_vertical=reference_steps["m2_vertical"] + delta.m2_vertical,
        )

    def ray_polyline(self, angle_urad: float, offset_mm: float = 0.0) -> list[tuple[float, float]]:
        """Schematic beam path including a fixed fold mirror between the two movers."""
        md = self.config.mirror_distance_mm
        fold = self.config.static_fold_distance_mm
        ud = self.config.undulator_distance_mm
        x0 = -0.35 * md
        x1 = 0.0
        x_fold = min(fold, md * 0.65)
        x2 = md
        xu = md + ud
        final_slope = angle_urad * 1e-6
        y_u = offset_mm
        y2 = y_u - final_slope * ud
        y_fold = y2 * 0.45
        y1 = 0.0
        y0 = 0.0
        return [(x0, y0), (x1, y1), (x_fold, y_fold), (x2, y2), (xu, y_u)]

    def clamp_scan_span(self, span_urad: float) -> float:
        return max(-self.config.mirror_distance_mm, min(self.config.mirror_distance_mm, span_urad))


def linspace(center: float, span: float, count: int) -> list[float]:
    count = max(1, int(count))
    if count == 1:
        return [float(center)]
    lo = center - span / 2.0
    hi = center + span / 2.0
    return [lo + i * (hi - lo) / (count - 1) for i in range(count)]


def ramp_values(start: float, stop: float, max_step: float) -> list[float]:
    max_step = abs(float(max_step))
    if max_step <= 0:
        return [float(stop)]
    delta = float(stop) - float(start)
    if abs(delta) <= max_step:
        return [float(stop)]
    n = int(math.ceil(abs(delta) / max_step))
    return [float(start) + delta * (i / n) for i in range(1, n + 1)]
