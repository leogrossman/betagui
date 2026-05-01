from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ControllerConfig
from .geometry import ramp_values
from .models import CommandRecord, PreviewCommand, SignalReading

MOTOR_PVS = {
    "m1_vertical": "MNF1C1L2RP",
    "m1_horizontal": "MNF1C2L2RP",
    "m2_vertical": "MNF2C1L2RP",
    "m2_horizontal": "MNF2C2L2RP",
}


SIGNAL_PRESETS = {
    "p1_h1_raw": ("P1 raw", "SCOPE1ZULP:h1p1:rdAmpl"),
    "p1_h1_avg": ("P1 avg", "SCOPE1ZULP:h1p1:rdAmplAv"),
    "p1_h1_std": ("P1 std", "SCOPE1ZULP:h1p1:rdAmplDev"),
    "p3_h1_raw": ("P3 raw", "SCOPE1ZULP:h1p3:rdAmpl"),
    "p3_h1_avg": ("P3 avg", "SCOPE1ZULP:h1p3:rdAmplAv"),
    "qpd01_sigma_x": ("QPD01 sigma X", "QPD01ZL2RP:rdSigmaX"),
    "qpd01_sigma_y": ("QPD01 sigma Y", "QPD01ZL2RP:rdSigmaY"),
    "qpd01_center_x_avg": ("QPD01 center X avg", "QPD01ZL2RP:rdCenterXav"),
    "qpd00_sigma_x": ("QPD00 sigma X", "QPD00ZL4RP:rdSigmaX"),
    "qpd00_sigma_y": ("QPD00 sigma Y", "QPD00ZL4RP:rdSigmaY"),
    "qpd00_center_x_avg": ("QPD00 center X avg", "QPD00ZL4RP:rdCenterXav"),
}


class SimPV:
    def __init__(self, name: str, initial=0.0):
        self.name = name
        self.value = initial
        self.connected = True
        self.callbacks: list[Callable[..., None]] = []

    def get(self, timeout=None):
        return self.value

    def put(self, value, wait=False, timeout=None):
        self.value = value
        for callback in list(self.callbacks):
            try:
                callback(pvname=self.name, value=value, timestamp=time.time())
            except Exception:
                pass
        return True

    def add_callback(self, callback):
        self.callbacks.append(callback)

    def clear_callbacks(self):
        self.callbacks.clear()


class PVFactory:
    def __init__(self, safe_mode: bool):
        self.safe_mode = safe_mode
        self.cache = {}
        self.PV = None
        if not safe_mode:
            from epics import PV  # type: ignore

            self.PV = PV

    def pv(self, name: str, initial=0.0):
        if name in self.cache:
            return self.cache[name]
        if self.safe_mode:
            pv = SimPV(name, initial)
        else:
            pv = self.PV(name, connection_timeout=1.0)
        self.cache[name] = pv
        return pv


def safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


@dataclass
class MotorSnapshot:
    key: str
    base: str
    val: float
    rbv: float
    dmov: int
    movn: int
    desc: str
    egu: str
    stat: str
    sevr: str
    rtyp: str
    hlm: float | None = None
    llm: float | None = None
    velo: float | None = None
    accl: float | None = None


class EpicsMotor:
    def __init__(self, key: str, base: str, factory: PVFactory):
        self.key = key
        self.base = base
        self.factory = factory
        self.val = factory.pv(base + ".VAL", 0.0)
        self.rbv = factory.pv(base + ".RBV", 0.0)
        self.dmov = factory.pv(base + ".DMOV", 1)
        self.movn = factory.pv(base + ".MOVN", 0)
        self.stop_pv = factory.pv(base + ".STOP", 0)
        self.desc = factory.pv(base + ".DESC", key)
        self.egu = factory.pv(base + ".EGU", "steps")
        self.stat = factory.pv(base + ".STAT", "NO_ALARM")
        self.sevr = factory.pv(base + ".SEVR", "NO_ALARM")
        self.rtyp = factory.pv(base + ".RTYP", "motor")
        self.hlm = factory.pv(base + ".HLM", math.nan)
        self.llm = factory.pv(base + ".LLM", math.nan)
        self.velo = factory.pv(base + ".VELO", math.nan)
        self.accl = factory.pv(base + ".ACCL", math.nan)

    def snapshot(self) -> MotorSnapshot:
        return MotorSnapshot(
            key=self.key,
            base=self.base,
            val=safe_float(self.val.get(timeout=0.3)),
            rbv=safe_float(self.rbv.get(timeout=0.3)),
            dmov=int(safe_float(self.dmov.get(timeout=0.3), 0)),
            movn=int(safe_float(self.movn.get(timeout=0.3), 0)),
            desc=str(self.desc.get(timeout=0.3)),
            egu=str(self.egu.get(timeout=0.3)),
            stat=str(self.stat.get(timeout=0.3)),
            sevr=str(self.sevr.get(timeout=0.3)),
            rtyp=str(self.rtyp.get(timeout=0.3)),
            hlm=safe_float(self.hlm.get(timeout=0.3), math.nan),
            llm=safe_float(self.llm.get(timeout=0.3), math.nan),
            velo=safe_float(self.velo.get(timeout=0.3), math.nan),
            accl=safe_float(self.accl.get(timeout=0.3), math.nan),
        )

    def put_target(self, target: float) -> None:
        self.val.put(float(target), wait=False)
        if self.factory.safe_mode:
            self.movn.put(1)
            self.dmov.put(0)
            self.rbv.put(float(target))
            self.val.put(float(target))
            self.movn.put(0)
            self.dmov.put(1)

    def wait_done(self, timeout_s: float = 30.0, poll_s: float = 0.05) -> bool:
        start = time.time()
        while time.time() - start < timeout_s:
            try:
                if int(float(self.dmov.get(timeout=0.2))) == 1:
                    return True
            except Exception:
                pass
            time.sleep(poll_s)
        return False

    def stop(self) -> None:
        self.stop_pv.put(1, wait=False)

    def clear_callbacks(self) -> None:
        for pv in [self.val, self.rbv, self.dmov, self.movn, self.stop_pv, self.stat, self.sevr]:
            try:
                pv.clear_callbacks()
            except Exception:
                pass


class SignalBackend:
    def __init__(self, label: str, pv_name: str, factory: PVFactory):
        self.label = label
        self.pv_name = pv_name
        self.pv = factory.pv(pv_name, 0.0)

    def read(self) -> SignalReading:
        value = self.pv.get(timeout=0.3)
        numeric = safe_float(value, math.nan)
        return SignalReading(self.label, self.pv_name, numeric, numeric == numeric)


class SimulatedSignalBackend:
    def __init__(self, label: str):
        self.label = label
        self.pv_name = "simulated"
        self.center_x = 0.0
        self.center_y = 0.0
        self.width_x = 45.0
        self.width_y = 45.0
        self.noise = 0.015
        self._target = (0.0, 0.0)

    def update_target(self, angle_x: float, angle_y: float) -> None:
        self._target = (angle_x, angle_y)

    def read(self) -> SignalReading:
        ax, ay = self._target
        dx = (ax - self.center_x) / self.width_x
        dy = (ay - self.center_y) / self.width_y
        value = max(0.0, math.exp(-(dx * dx + dy * dy)) + random.uniform(-self.noise, self.noise))
        return SignalReading(self.label, self.pv_name, value, True)


class MirrorController:
    """Controller-safe EPICS motor wrapper.

    It intentionally defaults to read-only behavior. Real writes are only sent
    when `write_mode` is enabled. All moves are converted into small `.VAL`
    ramps with DMOV waiting and extra settle time to reduce IOC/controller load.
    """

    def __init__(
        self,
        config: ControllerConfig,
        factory: PVFactory,
        debug: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.factory = factory
        self.debug = debug or (lambda message: None)
        self.write_mode = True if config.safe_mode else config.write_mode
        self.motors = {key: EpicsMotor(key, pv, factory) for key, pv in MOTOR_PVS.items()}
        self.reference_steps = self.capture_reference()
        self.last_move_error: str | None = None

    def capture_reference(self) -> dict[str, float]:
        reference = {}
        for key, motor in self.motors.items():
            reference[key] = motor.snapshot().rbv
        self.reference_steps = reference
        return dict(reference)

    def current_steps(self) -> dict[str, float]:
        return {key: motor.snapshot().rbv for key, motor in self.motors.items()}

    def motor_snapshots(self) -> list[MotorSnapshot]:
        return [motor.snapshot() for motor in self.motors.values()]

    def diagnostics(self) -> dict[str, object]:
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "safe_mode": self.config.safe_mode,
            "write_mode": self.write_mode,
            "reference_steps": dict(self.reference_steps),
            "motors": [asdict(snapshot) for snapshot in self.motor_snapshots()],
        }

    def write_diagnostics(self, path: Path) -> None:
        path.write_text(json.dumps(self.diagnostics(), indent=2, sort_keys=True))

    def plan_absolute_move(self, current_steps: dict[str, float], targets: dict[str, float]) -> dict[str, list[PreviewCommand]]:
        plan: dict[str, list[PreviewCommand]] = {}
        for key, target in targets.items():
            start = current_steps[key]
            ramp = tuple(ramp_values(start, target, self.config.max_step_per_put))
            plan[key] = [
                PreviewCommand(
                    motor_key=key,
                    start_rbv=start if idx == 0 else ramp[idx - 1],
                    target_val=value,
                    ramp_values=(value,),
                    wait_for_dmov=True,
                    settle_s=self.config.settle_s,
                )
                for idx, value in enumerate(ramp)
            ]
        return plan

    def validate_targets(self, targets: dict[str, float]) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for key, target in targets.items():
            reference = self.reference_steps.get(key, 0.0)
            if abs(target - reference) > self.config.max_delta_from_reference:
                errors.append(f"{key}: target {target:.3f} exceeds max delta from reference {reference:.3f}")
            current = self.motors[key].snapshot()
            if current.hlm == current.hlm and target > current.hlm:
                errors.append(f"{key}: target {target:.3f} exceeds HLM {current.hlm:.3f}")
            if current.llm == current.llm and target < current.llm:
                errors.append(f"{key}: target {target:.3f} below LLM {current.llm:.3f}")
            if abs(target - current.rbv) > self.config.max_absolute_move_steps:
                errors.append(f"{key}: requested move {target - current.rbv:.3f} exceeds max absolute move window")
            if self.config.alarm_lockout and current.sevr not in ("NO_ALARM", "0", "None"):
                errors.append(f"{key}: motor alarm severity {current.sevr}")
        return (not errors, errors)

    def move_absolute_group(
        self,
        targets: dict[str, float],
        request_stop: Callable[[], bool] | None = None,
        command_logger: Callable[[CommandRecord], None] | None = None,
        command_path: Path | None = None,
    ) -> bool:
        self.last_move_error = None
        ok, errors = self.validate_targets(targets)
        if not ok:
            self.last_move_error = "Unsafe motor command blocked: " + "; ".join(errors)
            raise RuntimeError(self.last_move_error)
        current_steps = self.current_steps()
        plan = self.plan_absolute_move(current_steps, targets)
        if command_path is not None:
            command_path.write_text(
                json.dumps(
                    {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "targets": targets,
                        "plan": {
                            key: [asdict(item) for item in items] for key, items in plan.items()
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        for key, commands in plan.items():
            motor = self.motors[key]
            self.debug(f"Starting serialized move for {motor.base} with {len(commands)} ramp layer(s).")
            for command in commands:
                if request_stop and request_stop():
                    self.debug("Move interrupted by stop request before next command.")
                    return False
                record = CommandRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    action="motor_put",
                    payload={
                        "motor_key": key,
                        "pv": motor.base + ".VAL",
                        "from": command.start_rbv,
                        "to": command.target_val,
                        "wait_for_dmov": command.wait_for_dmov,
                        "settle_s": command.settle_s,
                    },
                )
                if command_logger is not None:
                    command_logger(record)
                self.debug(
                    f"planned write {motor.base}.VAL {command.start_rbv:.3f} -> {command.target_val:.3f}; "
                    f"wait DMOV, settle {command.settle_s:.2f}s"
                )
                if self.write_mode:
                    before = motor.snapshot()
                    self.debug(
                        f"{motor.base}: before write RBV={before.rbv:.3f} VAL={before.val:.3f} "
                        f"DMOV={before.dmov} MOVN={before.movn} STAT={before.stat} SEVR={before.sevr}"
                    )
                    motor.put_target(command.target_val)
                    self.debug(f"{motor.base}: command sent, waiting for DMOV=1.")
                    if command.wait_for_dmov and not motor.wait_done(timeout_s=self.config.wait_timeout_s):
                        self.last_move_error = f"{motor.base} did not report DMOV within timeout"
                        raise RuntimeError(self.last_move_error)
                    after_wait = motor.snapshot()
                    self.debug(
                        f"{motor.base}: after wait RBV={after_wait.rbv:.3f} VAL={after_wait.val:.3f} "
                        f"DMOV={after_wait.dmov} MOVN={after_wait.movn} STAT={after_wait.stat} SEVR={after_wait.sevr}"
                    )
                    if abs(after_wait.rbv - command.target_val) > max(0.5, self.config.max_step_per_put):
                        self.last_move_error = (
                            f"{motor.base} reached RBV={after_wait.rbv:.3f}, expected {command.target_val:.3f}. "
                            "Move may not have completed correctly."
                        )
                        raise RuntimeError(self.last_move_error)
                    time.sleep(max(0.0, self.config.settle_s))
                    settled = motor.snapshot()
                    self.debug(
                        f"{motor.base}: post-settle RBV={settled.rbv:.3f} VAL={settled.val:.3f} "
                        f"DMOV={settled.dmov} MOVN={settled.movn}"
                    )
                time.sleep(max(0.0, self.config.inter_put_delay_s))
            self.debug(f"Finished serialized move for {motor.base}.")
        return True

    def stop_all(self) -> None:
        self.debug("Issuing STOP to all mirror motors.")
        if self.write_mode:
            for motor in self.motors.values():
                motor.stop()


def build_signal_backend(
    safe_mode: bool,
    preset_key: str | None,
    manual_pv: str | None,
    factory: PVFactory,
) -> object:
    if safe_mode:
        label = SIGNAL_PRESETS.get(preset_key or "", ("Signal", ""))[0] if preset_key else "Signal"
        return SimulatedSignalBackend(label)
    if manual_pv:
        return SignalBackend(manual_pv, manual_pv, factory)
    if preset_key and preset_key in SIGNAL_PRESETS:
        label, pv = SIGNAL_PRESETS[preset_key]
        return SignalBackend(label, pv, factory)
    label, pv = SIGNAL_PRESETS["p1_h1_avg"]
    return SignalBackend(label, pv, factory)
