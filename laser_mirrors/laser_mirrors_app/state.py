from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from .geometry import LaserMirrorGeometry
from .models import MirrorAngles, UndulatorTarget


@dataclass
class MirrorStateSnapshot:
    """Mirror-state file contents in the legacy `mirror_state.ini` style."""

    last_known_x: UndulatorTarget
    last_known_y: UndulatorTarget
    last_set_x: UndulatorTarget
    last_set_y: UndulatorTarget

    @classmethod
    def zeros(cls) -> "MirrorStateSnapshot":
        zero = UndulatorTarget(offset_mm=0.0, angle_urad=0.0)
        return cls(last_known_x=zero, last_known_y=zero, last_set_x=zero, last_set_y=zero)


def load_state(path: Path) -> MirrorStateSnapshot:
    config = configparser.ConfigParser()
    if not path.exists():
        return MirrorStateSnapshot.zeros()
    config.read(path)
    try:
        return MirrorStateSnapshot(
            last_known_x=UndulatorTarget(
                offset_mm=float(config["last_known"]["OffsetX"]),
                angle_urad=float(config["last_known"]["AngleX"]),
            ),
            last_known_y=UndulatorTarget(
                offset_mm=float(config["last_known"]["OffsetY"]),
                angle_urad=float(config["last_known"]["AngleY"]),
            ),
            last_set_x=UndulatorTarget(
                offset_mm=float(config["last_set"]["OffsetX"]),
                angle_urad=float(config["last_set"]["AngleX"]),
            ),
            last_set_y=UndulatorTarget(
                offset_mm=float(config["last_set"]["OffsetY"]),
                angle_urad=float(config["last_set"]["AngleY"]),
            ),
        )
    except (KeyError, ValueError):
        return MirrorStateSnapshot.zeros()


def save_state(
    path: Path,
    geometry: LaserMirrorGeometry,
    current_angles_x: MirrorAngles,
    current_angles_y: MirrorAngles,
    requested_x: UndulatorTarget,
    requested_y: UndulatorTarget,
) -> None:
    """Persist the current and requested states using the legacy section layout."""

    current_x = geometry.to_undulator_target(current_angles_x, "x")
    current_y = geometry.to_undulator_target(current_angles_y, "y")
    config = configparser.ConfigParser()
    config["last_known"] = {
        "OffsetX": str(current_x.offset_mm),
        "AngleX": str(current_x.angle_urad),
        "OffsetY": str(current_y.offset_mm),
        "AngleY": str(current_y.angle_urad),
    }
    config["last_set"] = {
        "OffsetX": str(requested_x.offset_mm),
        "AngleX": str(requested_x.angle_urad),
        "OffsetY": str(requested_y.offset_mm),
        "AngleY": str(requested_y.angle_urad),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        config.write(handle)
