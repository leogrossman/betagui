from __future__ import annotations

from dataclasses import dataclass

from .config import GeometryConfig
from .models import MirrorAngles, UndulatorTarget


@dataclass
class PlaneStepCalibration:
    mirror1_urad_per_step: float
    mirror2_urad_per_step: float


class LaserMirrorGeometry:
    """Encodes the mirror-pair geometry and mirror-to-undulator transforms.

    The underlying formulas are adapted from the legacy `MirrorControlCalculate.py`
    tool, but wrapped in a more explicit and testable interface.
    """

    def __init__(self, config: GeometryConfig):
        self.config = config
        self._x_steps = PlaneStepCalibration(
            mirror1_urad_per_step=config.vertical_step_urad,
            mirror2_urad_per_step=config.vertical_step_urad,
        )
        self._y_steps = PlaneStepCalibration(
            mirror1_urad_per_step=config.horizontal_step_urad,
            mirror2_urad_per_step=config.horizontal_step_urad,
        )

    def to_mirror_angles(self, target: UndulatorTarget, axis: str) -> MirrorAngles:
        """Convert undulator offset/angle into mirror angles in microradians."""
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        offset_angle = -target.offset_mm / (2.0 * mdist) * 1e6
        m1_from_angle = target.angle_urad / 2.0 * udist / mdist
        m2_from_angle = target.angle_urad / 2.0 + m1_from_angle
        m1 = m1_from_angle + offset_angle
        m2 = m2_from_angle + offset_angle
        if axis.lower() == "x":
            m2 *= self.config.mirror2_x_sign
        else:
            m2 *= self.config.mirror2_y_sign
        return MirrorAngles(mirror1_urad=m1, mirror2_urad=m2)

    def to_undulator_target(self, angles: MirrorAngles, axis: str) -> UndulatorTarget:
        """Convert mirror angles back into offset/angle at the undulator."""
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        m1 = angles.mirror1_urad
        m2 = angles.mirror2_urad
        if axis.lower() == "x":
            m2 *= self.config.mirror2_x_sign
        else:
            m2 *= self.config.mirror2_y_sign
        angle = 2.0 * (m2 - m1)
        offset_mm = (angle * udist - 2.0 * mdist * m1) / 1e6
        return UndulatorTarget(offset_mm=offset_mm, angle_urad=angle)

    def solve_mirror2_for_fixed_offset(self, mirror1_urad: float, offset_mm: float, axis: str) -> MirrorAngles:
        """Solve mirror 2 when mirror 1 is chosen and the undulator offset must stay fixed."""
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        sign = self.config.mirror2_x_sign if axis.lower() == "x" else self.config.mirror2_y_sign
        mirror2_signed = (offset_mm * 1e6 + 2.0 * (udist + mdist) * mirror1_urad) / (2.0 * udist)
        return MirrorAngles(mirror1_urad=mirror1_urad, mirror2_urad=mirror2_signed * sign)

    def solve_mirror1_for_fixed_offset(self, mirror2_urad: float, offset_mm: float, axis: str) -> MirrorAngles:
        """Solve mirror 1 when mirror 2 is chosen and the undulator offset must stay fixed."""
        mdist = self.config.mirror_distance_mm
        udist = self.config.undulator_distance_mm
        sign = self.config.mirror2_x_sign if axis.lower() == "x" else self.config.mirror2_y_sign
        mirror2_signed = mirror2_urad * sign
        mirror1 = (2.0 * udist * mirror2_signed - offset_mm * 1e6) / (2.0 * (udist + mdist))
        return MirrorAngles(mirror1_urad=mirror1, mirror2_urad=mirror2_urad)

    def angle_delta_to_steps(self, angle_delta_urad: float, axis: str, mirror_index: int) -> int:
        calib = self._x_steps if axis.lower() == "x" else self._y_steps
        scale = calib.mirror1_urad_per_step if mirror_index == 1 else calib.mirror2_urad_per_step
        return int(round(angle_delta_urad / scale))

    def steps_to_angle_delta(self, steps: int, axis: str, mirror_index: int) -> float:
        calib = self._x_steps if axis.lower() == "x" else self._y_steps
        scale = calib.mirror1_urad_per_step if mirror_index == 1 else calib.mirror2_urad_per_step
        return steps * scale
