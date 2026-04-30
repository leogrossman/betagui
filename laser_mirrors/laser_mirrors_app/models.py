from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MirrorAngles:
    """Angular state of both movable mirrors in one steering plane."""

    mirror1_urad: float
    mirror2_urad: float


@dataclass(frozen=True)
class UndulatorTarget:
    """Desired beam offset and interaction angle at the undulator center."""

    offset_mm: float
    angle_urad: float


@dataclass(frozen=True)
class MotorTargets:
    """Absolute EPICS motor targets in controller step units."""

    m1_horizontal: float
    m1_vertical: float
    m2_horizontal: float
    m2_vertical: float

    def as_dict(self) -> dict[str, float]:
        return {
            "m1_horizontal": self.m1_horizontal,
            "m1_vertical": self.m1_vertical,
            "m2_horizontal": self.m2_horizontal,
            "m2_vertical": self.m2_vertical,
        }


@dataclass(frozen=True)
class CommandRecord:
    timestamp: str
    action: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SignalReading:
    label: str
    pv: str
    value: float
    ok: bool
    timestamp_iso: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class PreviewCommand:
    motor_key: str
    start_rbv: float
    target_val: float
    ramp_values: tuple[float, ...]
    wait_for_dmov: bool
    settle_s: float


@dataclass(frozen=True)
class ScanPoint:
    index: int
    mode: str
    angle_x_urad: float
    angle_y_urad: float
    offset_x_mm: float
    offset_y_mm: float
    targets: MotorTargets


@dataclass
class MeasurementRecord:
    point_index: int
    mode: str
    elapsed_s: float
    angle_x_urad: float
    angle_y_urad: float
    offset_x_mm: float
    offset_y_mm: float
    signal_label: str
    signal_pv: str
    signal_value: float
    signal_average: float
    signal_std: float
    samples_used: int
    commanded_m1_horizontal: float
    commanded_m1_vertical: float
    commanded_m2_horizontal: float
    commanded_m2_vertical: float
    rbv_m1_horizontal: float
    rbv_m1_vertical: float
    rbv_m2_horizontal: float
    rbv_m2_vertical: float
    timestamp_iso: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class BestPointRecommendation:
    objective: str
    signal_label: str
    signal_value: float
    point_index: int
    angle_x_urad: float
    angle_y_urad: float
    offset_x_mm: float
    offset_y_mm: float
    targets: MotorTargets


@dataclass
class PassiveSample:
    """One passive observation of motor state plus the selected live signal."""

    elapsed_s: float
    signal_label: str
    signal_pv: str
    signal_value: float
    m1_horizontal: float
    m1_vertical: float
    m2_horizontal: float
    m2_vertical: float
    dmov_all: int
    movn_any: int
    source: str = "passive_poll"
    timestamp_iso: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class PenTestPoint:
    """One cautious motor stress-test command around a captured reference."""

    index: int
    motor_key: str
    amplitude_steps: float
    target_steps: float
    dwell_s: float
    note: str
