from __future__ import annotations

import importlib.util
import math
import random
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .geometry import LaserMirrorGeometry
from .models import CommandRecord, MeasurementRecord


class MirrorBackend(Protocol):
    name: str

    def relative_move(self, axis: str, mirror_index: int, steps: int) -> None: ...
    def get_position_steps(self, axis: str, mirror_index: int) -> int: ...


class P1Backend(Protocol):
    name: str

    def read(self) -> float: ...


class SimulatedMirrorBackend:
    name = "simulated"

    def __init__(self, debug: Callable[[str], None] | None = None):
        self.debug = debug or (lambda message: None)
        self._positions = {("x", 1): 0, ("x", 2): 0, ("y", 1): 0, ("y", 2): 0}

    def relative_move(self, axis: str, mirror_index: int, steps: int) -> None:
        self._positions[(axis, mirror_index)] += int(steps)
        self.debug(f"[sim] relative_move axis={axis} mirror={mirror_index} steps={steps}")

    def get_position_steps(self, axis: str, mirror_index: int) -> int:
        return self._positions[(axis, mirror_index)]


class SimulatedP1Backend:
    name = "simulated"

    def __init__(self, debug: Callable[[str], None] | None = None):
        self.debug = debug or (lambda message: None)
        self.center_x = 90.0
        self.center_y = -45.0
        self.width_x = 160.0
        self.width_y = 120.0
        self.noise = 0.03
        self._latest_target = (0.0, 0.0)

    def update_target(self, angle_x_urad: float, angle_y_urad: float) -> None:
        self._latest_target = (angle_x_urad, angle_y_urad)

    def read(self) -> float:
        ax, ay = self._latest_target
        dx = (ax - self.center_x) / self.width_x
        dy = (ay - self.center_y) / self.width_y
        value = math.exp(-(dx * dx + dy * dy)) + random.uniform(-self.noise, self.noise)
        return max(value, 0.0)


class EpicsP1Backend:
    name = "epics"

    def __init__(self, pv_name: str):
        if not pv_name:
            raise ValueError("P1 PV name is required for EPICS backend")
        from epics import PV  # type: ignore

        self.pv = PV(pv_name)

    def read(self) -> float:
        value = self.pv.get()
        if value is None:
            return math.nan
        return float(value)


class PicomotorBackend:
    name = "picomotor"

    def __init__(self, cmdlib_path: Path, debug: Callable[[str], None] | None = None):
        self.debug = debug or (lambda message: None)
        spec = importlib.util.spec_from_file_location("legacy_mirror_cmdlib", cmdlib_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load legacy mirror command library from {cmdlib_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._lib = module.MCCmdLib()

    def relative_move(self, axis: str, mirror_index: int, steps: int) -> None:
        axis_id = 0 if axis == "x" else 1
        self.debug(f"[picomotor] RelativeMove axis={axis} mirror={mirror_index} steps={steps}")
        if mirror_index == 1:
            self._lib.RelativeMove(steps, 0, axis=axis_id)
        else:
            self._lib.RelativeMove(0, steps, axis=axis_id)

    def get_position_steps(self, axis: str, mirror_index: int) -> int:
        axis_id = 0 if axis == "x" else 1
        pos1, pos2 = self._lib.GetPosition(axis=axis_id)
        return int(pos1 if mirror_index == 1 else pos2)


def build_backends(
    safe_mode: bool,
    p1_backend_name: str,
    p1_pv: str,
    cmdlib_path: Path,
    debug: Callable[[str], None],
) -> tuple[MirrorBackend, P1Backend]:
    if safe_mode:
        return SimulatedMirrorBackend(debug), SimulatedP1Backend(debug)
    mirror_backend = PicomotorBackend(cmdlib_path, debug=debug)
    if p1_backend_name == "epics":
        return mirror_backend, EpicsP1Backend(p1_pv)
    return mirror_backend, SimulatedP1Backend(debug)


def command_record(backend: str, action: str, payload: dict[str, object]) -> CommandRecord:
    from datetime import datetime

    return CommandRecord(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        backend=backend,
        action=action,
        payload=dict(payload),
    )
