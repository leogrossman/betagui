from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MirrorAngles:
    """Angular state of both mirrors in one plane, in microradians."""

    mirror1_urad: float
    mirror2_urad: float


@dataclass
class UndulatorTarget:
    """Desired laser state at the undulator center for one plane."""

    offset_mm: float
    angle_urad: float


@dataclass
class CommandRecord:
    timestamp: str
    backend: str
    action: str
    payload: dict[str, Any]


@dataclass
class ScanPoint:
    index: int
    target_x: UndulatorTarget
    target_y: UndulatorTarget
    note: str = ""


@dataclass
class MeasurementRecord:
    point_index: int
    elapsed_s: float
    angle_x_urad: float
    angle_y_urad: float
    offset_x_mm: float
    offset_y_mm: float
    p1_value: float
    samples_used: int
    mirror1_x_urad: float
    mirror2_x_urad: float
    mirror1_y_urad: float
    mirror2_y_urad: float
    command_batch_id: str
    timestamp_iso: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
