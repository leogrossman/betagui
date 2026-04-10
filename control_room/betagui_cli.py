#!/usr/bin/env python3
"""Standalone legacy-profile control-room CLI for chromaticity measurement.

By default this behaves like the legacy script and allows live writes.
Use ``--safe`` for read-only preflight.
"""

import argparse
import json
import os
import platform
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

SPEED_OF_LIGHT_M_PER_S = 299792458.0
NHARMONIC = 80
DEFAULT_LOG_DIRNAME = "betagui_logs"


def _json_ready(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.poly1d):
        return value.c.tolist()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return repr(value)


@dataclass
class SessionLogger:
    session_dir: Path
    text_log_path: Path
    event_log_path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def create(cls, root: Optional[Path], prefix: str):
        root_dir = Path(root) if root is not None else Path.cwd() / DEFAULT_LOG_DIRNAME
        session_name = "%s_%s_pid%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"), os.getpid())
        session_dir = root_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=False)
        (session_dir / "measurements").mkdir()
        return cls(
            session_dir=session_dir,
            text_log_path=session_dir / "session.log",
            event_log_path=session_dir / "events.jsonl",
        )

    def log_line(self, line: str):
        with self._lock:
            with self.text_log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def record(self, event_type: str, **payload):
        event = {
            "timestamp": time.time(),
            "event": event_type,
            "data": _json_ready(payload),
        }
        with self._lock:
            with self.event_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")

    def write_payload(self, relative_name: str, payload) -> Path:
        payload_path = self.session_dir / relative_name
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with payload_path.open("w", encoding="utf-8") as stream:
                json.dump(_json_ready(payload), stream, indent=2, sort_keys=True)
                stream.write("\n")
        return payload_path


class EpicsUnavailableError(RuntimeError):
    """Raised when pyepics is not available but live access was requested."""


def _import_epics():
    try:
        import epics  # type: ignore
    except ImportError as exc:
        raise EpicsUnavailableError(
            "pyepics is not available; this control-room CLI needs live EPICS."
        ) from exc
    return epics


class EpicsAdapter:
    """Tiny cache for pyepics PV objects."""

    def __init__(self, timeout: float = 1.0):
        self.timeout = timeout
        self._epics = _import_epics()
        self._cache = {}

    def pv(self, name: str):
        pv = self._cache.get(name)
        if pv is None:
            pv = self._epics.PV(name, connection_timeout=self.timeout)
            self._cache[name] = pv
        return pv

    def get(self, name: str, default=None):
        value = self.pv(name).get(timeout=self.timeout, use_monitor=False)
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        return self.pv(name).put(value)


class UnavailableAdapter:
    def get(self, name: str, default=None):
        return default

    def put(self, name: str, value):
        return False


@dataclass
class BetaguiPVs:
    tune_x: Optional[str] = "TUNEZRP:measX"
    tune_y: Optional[str] = "TUNEZRP:measY"
    tune_s: Optional[str] = "CUMZ4X003GP:tuneSyn"
    rf_setpoint: Optional[str] = "MCLKHGP:setFrq"
    optics_mode: Optional[str] = "MLSOPCCP:actOptRmpTblSet"
    orbit_mode: Optional[str] = "ORBITCCP:selRunMode"
    orbit_mode_readback: Optional[str] = "RMC00VP"
    feedback_x: Optional[str] = "IGPF:X:FBCTRL"
    feedback_y: Optional[str] = "IGPF:Y:FBCTRL"
    feedback_s: Optional[str] = "IGPF:Z:FBCTRL"
    cavity_voltage: Optional[str] = "PAHRP:setVoltCav"
    beam_energy: Optional[str] = "ERMPCGP:rdRmp"


@dataclass
class MeasurementInputs:
    n_tune_samples: int = 7
    n_rf_points: int = 11
    delta_x_min_mm: float = -2.0
    delta_x_max_mm: float = 2.0
    fit_order: int = 1
    delay_after_rf_s: float = 5.0
    delay_between_tune_reads_s: float = 1.0


@dataclass
class MeasurementResult:
    rf_points_hz: np.ndarray
    delta_hz: np.ndarray
    tune_x_khz: np.ndarray
    tune_y_khz: np.ndarray
    tune_s_khz: np.ndarray
    fit_x: np.poly1d
    fit_y: np.poly1d
    fit_s: np.poly1d
    xi: List[float]
    alpha0: float
    alpha0_details: Dict[str, object] = field(default_factory=dict)
    point_records: List[Dict[str, object]] = field(default_factory=list)
    fit_x_coeffs: List[float] = field(default_factory=list)
    fit_y_coeffs: List[float] = field(default_factory=list)
    fit_s_coeffs: List[float] = field(default_factory=list)
    initial_rf_hz: float = 0.0
    optics_mode: float = 0.0
    dmax: float = 0.0
    feedback_snapshot: Dict[str, float] = field(default_factory=dict)


def optics_mode_to_dmax(optics_mode) -> float:
    if optics_mode == 1:
        return 1.5
    if optics_mode == 3:
        return 1.0
    return 2.0


def calculate_alpha0_with_details(adapter, pvs: BetaguiPVs, harmonic_number: int = NHARMONIC, samples: int = 10):
    freq_samples = [float(adapter.get(pvs.tune_s, 0.0) or 0.0) for _ in range(samples)]
    freq_s_khz = float(np.mean(freq_samples))
    rf_hz = float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0)
    cavity_voltage_v = float(adapter.get(pvs.cavity_voltage, 0.0) or 0.0) * 1000.0
    energy_ev = float(adapter.get(pvs.beam_energy, 0.0) or 0.0) * 1e6
    if rf_hz == 0.0 or cavity_voltage_v == 0.0:
        raise ValueError("RF frequency and cavity voltage must be non-zero.")
    alpha0 = (freq_s_khz * 1000.0) ** 2 / (rf_hz * 1000.0) ** 2 * 2.0 * np.pi * harmonic_number * energy_ev / cavity_voltage_v
    details = {
        "mode": "dynamic",
        "harmonic_number": harmonic_number,
        "tune_s_samples_khz": freq_samples,
        "tune_s_mean_khz": freq_s_khz,
        "rf_hz": rf_hz,
        "cavity_voltage_v": cavity_voltage_v,
        "beam_energy_ev": energy_ev,
        "alpha0": alpha0,
    }
    return float(alpha0), details


def calculate_alpha0(adapter, pvs: BetaguiPVs, harmonic_number: int = NHARMONIC, samples: int = 10) -> float:
    alpha0, _details = calculate_alpha0_with_details(
        adapter,
        pvs,
        harmonic_number=harmonic_number,
        samples=samples,
    )
    return alpha0


def build_rf_range(frf0_hz: float, alpha0: float, dmax: float, delta_x_min_mm: float, delta_x_max_mm: float, n_points: int) -> np.ndarray:
    delta_x_max_m = delta_x_max_mm / 1000.0
    delta_x_min_m = delta_x_min_mm / 1000.0
    frf_max = frf0_hz + (-delta_x_min_m * alpha0 * frf0_hz / dmax)
    frf_min = frf0_hz - (delta_x_max_m * alpha0 * frf0_hz / dmax)
    return np.linspace(frf_min, frf_max, n_points)


def trim_tune_samples(samples: Sequence[float]) -> np.ndarray:
    values = np.array(samples, dtype=float)
    if len(values) <= 5:
        return values
    values = np.sort(values)
    return values[1:-1]


def average_tune_samples(samples: Sequence[float]) -> float:
    trimmed = trim_tune_samples(samples)
    if len(trimmed) == 0:
        raise ValueError("No tune samples available.")
    return float(np.mean(trimmed))


def sample_tunes(
    adapter,
    pvs: BetaguiPVs,
    n_samples: int,
    delay_between_reads_s: float = 0.0,
) -> Dict[str, float]:
    tune_x = []
    tune_y = []
    tune_s = []
    for sample_index in range(n_samples):
        tune_x.append(float(adapter.get(pvs.tune_x, 0.0) or 0.0))
        tune_y.append(float(adapter.get(pvs.tune_y, 0.0) or 0.0))
        tune_s.append(float(adapter.get(pvs.tune_s, 0.0) or 0.0))
        if sample_index != n_samples - 1 and delay_between_reads_s > 0.0:
            time.sleep(delay_between_reads_s)
    return {
        "x": average_tune_samples(tune_x),
        "y": average_tune_samples(tune_y),
        "s": average_tune_samples(tune_s),
        "raw_x": tune_x,
        "raw_y": tune_y,
        "raw_s": tune_s,
    }


class GuardedAdapter:
    def __init__(self, adapter, allow_machine_writes: bool, logger, event_recorder=None):
        self._adapter = adapter
        self.allow_machine_writes = allow_machine_writes
        self._logger = logger
        self._event_recorder = event_recorder

    def get(self, name: str, default=None):
        try:
            return self._adapter.get(name, default)
        except Exception as exc:
            self._logger("Read failed for %s: %s" % (name, exc))
            if self._event_recorder is not None:
                self._event_recorder("pv_get_failed", pv=name, default=default, error=str(exc))
            return default

    def put(self, name: str, value):
        if self.allow_machine_writes:
            try:
                result = self._adapter.put(name, value)
                if self._event_recorder is not None:
                    self._event_recorder("pv_put", pv=name, value=value, result=result)
                return result
            except Exception as exc:
                self._logger("Write failed for %s: %s" % (name, exc))
                if self._event_recorder is not None:
                    self._event_recorder("pv_put_failed", pv=name, value=value, error=str(exc))
                return False
        self._logger("Suppressed live write to %s -> %r" % (name, value))
        if self._event_recorder is not None:
            self._event_recorder("pv_put_suppressed", pv=name, value=value)
        return False


@dataclass
class RuntimeConfig:
    allow_machine_writes: bool = True
    log_root: Optional[Path] = None


@dataclass
class RuntimeState:
    config: RuntimeConfig
    pvs: BetaguiPVs = field(default_factory=BetaguiPVs)
    adapter: Optional[GuardedAdapter] = None
    session_logger: Optional[SessionLogger] = None
    messages: List[str] = field(default_factory=list)
    frf0: float = 0.0
    ini_fdb: List[float] = field(default_factory=list)
    ini_orbit: float = 0.0
    saved_settings_valid: bool = False
    last_result: Optional[MeasurementResult] = None
    measurement_counter: int = 0

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (timestamp, message)
        self.messages.append(line)
        print(line)
        if self.session_logger is not None:
            self.session_logger.log_line(line)

    def record_event(self, event_type: str, **payload):
        if self.session_logger is not None:
            self.session_logger.record(event_type, **payload)

    def write_payload(self, relative_name: str, payload) -> Optional[Path]:
        if self.session_logger is None:
            return None
        return self.session_logger.write_payload(relative_name, payload)

    def next_measurement_name(self, prefix: str) -> str:
        self.measurement_counter += 1
        return "%s_%03d" % (prefix, self.measurement_counter)

    @property
    def can_write_machine(self) -> bool:
        return self.config.allow_machine_writes


def create_runtime(config: Optional[RuntimeConfig] = None) -> RuntimeState:
    state = RuntimeState(config=config or RuntimeConfig())
    try:
        state.session_logger = SessionLogger.create(state.config.log_root, "betagui_cli")
    except Exception as exc:
        print("Could not create session logger: %s" % exc)
        state.session_logger = None
    if state.session_logger is not None:
        state.log("Session log directory: %s" % state.session_logger.session_dir)
        state.write_payload(
            "session_metadata.json",
            {
                "script": "control_room/betagui_cli.py",
                "cwd": str(Path.cwd()),
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "python": sys.version,
                "platform": platform.platform(),
                "allow_machine_writes": state.config.allow_machine_writes,
            },
        )
        state.record_event(
            "session_start",
            script="control_room/betagui_cli.py",
            cwd=str(Path.cwd()),
            hostname=socket.gethostname(),
            allow_machine_writes=state.config.allow_machine_writes,
        )
    try:
        base_adapter = EpicsAdapter()
        state.log("Using live EPICS adapter.")
    except EpicsUnavailableError as exc:
        state.log(str(exc))
        base_adapter = UnavailableAdapter()
    state.adapter = GuardedAdapter(
        base_adapter,
        state.config.allow_machine_writes,
        state.log,
        event_recorder=state.record_event,
    )
    save_setting(state)
    return state


def _get_float(state: RuntimeState, pv_name: str, default: float = 0.0) -> float:
    value = state.adapter.get(pv_name, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        state.log("Non-numeric value from %s: %r" % (pv_name, value))
        return default


def _machine_snapshot(state: RuntimeState) -> Dict[str, object]:
    return {
        "timestamp": time.time(),
        "rf_hz": _get_float(state, state.pvs.rf_setpoint, 0.0),
        "tune_x_khz": _get_float(state, state.pvs.tune_x, 0.0),
        "tune_y_khz": _get_float(state, state.pvs.tune_y, 0.0),
        "tune_s_khz": _get_float(state, state.pvs.tune_s, 0.0),
        "optics_mode": _get_float(state, state.pvs.optics_mode, 0.0),
        "orbit_mode_readback": _get_float(state, state.pvs.orbit_mode_readback, 0.0),
        "feedback_x": _get_float(state, state.pvs.feedback_x, 0.0),
        "feedback_y": _get_float(state, state.pvs.feedback_y, 0.0),
        "feedback_s": _get_float(state, state.pvs.feedback_s, 0.0),
        "cavity_voltage_kv": _get_float(state, state.pvs.cavity_voltage, 0.0),
        "beam_energy_mev": _get_float(state, state.pvs.beam_energy, 0.0),
    }


def _measurement_point_context(state: RuntimeState) -> Dict[str, object]:
    snapshot = _machine_snapshot(state)
    return {
        "rf_hz": snapshot["rf_hz"],
        "tune_x_khz": snapshot["tune_x_khz"],
        "tune_y_khz": snapshot["tune_y_khz"],
        "tune_s_khz": snapshot["tune_s_khz"],
        "optics_mode": snapshot["optics_mode"],
        "orbit_mode_readback": snapshot["orbit_mode_readback"],
        "feedback_x": snapshot["feedback_x"],
        "feedback_y": snapshot["feedback_y"],
        "feedback_s": snapshot["feedback_s"],
        "cavity_voltage_kv": snapshot["cavity_voltage_kv"],
        "beam_energy_mev": snapshot["beam_energy_mev"],
    }


def save_setting(state: RuntimeState):
    raw_rf = state.adapter.get(state.pvs.rf_setpoint, None)
    if raw_rf in (None, ""):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is unavailable.")
        state.record_event("save_setting", success=False, reason="rf_unavailable")
        return False
    try:
        state.frf0 = float(raw_rf)
    except (TypeError, ValueError):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is non-numeric (%r)." % (raw_rf,))
        state.record_event("save_setting", success=False, reason="rf_non_numeric", raw_rf=raw_rf)
        return False
    state.ini_fdb = [
        _get_float(state, state.pvs.feedback_x, 0.0),
        _get_float(state, state.pvs.feedback_y, 0.0),
        _get_float(state, state.pvs.feedback_s, 0.0),
    ]
    state.ini_orbit = _get_float(state, state.pvs.orbit_mode_readback, 0.0)
    state.saved_settings_valid = True
    state.log("Saved current settings.")
    state.record_event(
        "save_setting",
        success=True,
        frf0=state.frf0,
        ini_fdb=state.ini_fdb,
        ini_orbit=state.ini_orbit,
        snapshot=_machine_snapshot(state),
    )
    return True


def set_frf_slowly(state: RuntimeState, target_frf_in_hz: float, n_steps: int = 10, delay_s: float = 0.2):
    start_frf_in_hz = _get_float(state, state.pvs.rf_setpoint, target_frf_in_hz)
    for value in np.linspace(start_frf_in_hz, target_frf_in_hz, n_steps):
        state.adapter.put(state.pvs.rf_setpoint, float(value))
        if state.can_write_machine and delay_s > 0.0:
            time.sleep(delay_s)
    state.log("RF now at %.6f Hz" % target_frf_in_hz)


def cal_alpha0(state: RuntimeState) -> Optional[float]:
    try:
        alpha0, details = calculate_alpha0_with_details(
            state.adapter,
            state.pvs,
            harmonic_number=NHARMONIC,
        )
    except Exception as exc:
        state.log("Could not calculate alpha0: %s" % exc)
        state.record_event("alpha0_failed", error=str(exc), snapshot=_machine_snapshot(state))
        return None
    state.log("alpha0 = %.8f" % alpha0)
    state.record_event("alpha0_calculated", details=details, snapshot=_machine_snapshot(state))
    return alpha0


def disable_feedback_for_measurement(state: RuntimeState) -> Dict[str, float]:
    snapshot = {}
    snapshot[state.pvs.feedback_x] = _get_float(state, state.pvs.feedback_x, 0.0)
    snapshot[state.pvs.feedback_y] = _get_float(state, state.pvs.feedback_y, 0.0)
    snapshot[state.pvs.feedback_s] = _get_float(state, state.pvs.feedback_s, 0.0)
    snapshot[state.pvs.orbit_mode] = _get_float(state, state.pvs.orbit_mode_readback, 0.0)
    state.adapter.put(state.pvs.feedback_x, 0)
    state.adapter.put(state.pvs.feedback_y, 0)
    state.adapter.put(state.pvs.feedback_s, 0)
    state.adapter.put(state.pvs.orbit_mode, 0)
    return snapshot


def restore_feedback_after_measurement(state: RuntimeState, snapshot: Dict[str, float]):
    for pv_name, value in snapshot.items():
        state.adapter.put(pv_name, value)


def measure_chromaticity(state: RuntimeState, inputs: MeasurementInputs, alpha0: Optional[float] = None) -> MeasurementResult:
    frf0_hz = float(state.adapter.get(state.pvs.rf_setpoint, 0.0) or 0.0)
    alpha0_details = {"mode": "fixed", "alpha0": float(alpha0)} if alpha0 is not None else {}
    if alpha0 is None:
        alpha0, alpha0_details = calculate_alpha0_with_details(
            state.adapter,
            state.pvs,
            harmonic_number=NHARMONIC,
        )
    optics_mode = state.adapter.get(state.pvs.optics_mode, 0)
    dmax = optics_mode_to_dmax(optics_mode)
    rf_points_hz = build_rf_range(
        frf0_hz,
        alpha0,
        dmax,
        inputs.delta_x_min_mm,
        inputs.delta_x_max_mm,
        inputs.n_rf_points,
    )
    delta_hz = rf_points_hz - frf0_hz
    tune_x = []
    tune_y = []
    tune_s = []
    snapshot = disable_feedback_for_measurement(state)
    point_records: List[Dict[str, object]] = []
    try:
        for rf_hz in rf_points_hz:
            state.adapter.put(state.pvs.rf_setpoint, float(rf_hz))
            if inputs.delay_after_rf_s > 0.0:
                time.sleep(inputs.delay_after_rf_s)
            sampled = sample_tunes(
                state.adapter,
                state.pvs,
                inputs.n_tune_samples,
                delay_between_reads_s=inputs.delay_between_tune_reads_s,
            )
            point_records.append(
                {
                    "rf_target_hz": float(rf_hz),
                    "rf_readback_hz": float(state.adapter.get(state.pvs.rf_setpoint, rf_hz) or rf_hz),
                    "tune_x_samples_khz": sampled["raw_x"],
                    "tune_y_samples_khz": sampled["raw_y"],
                    "tune_s_samples_khz": sampled["raw_s"],
                    "tune_x_mean_khz": sampled["x"],
                    "tune_y_mean_khz": sampled["y"],
                    "tune_s_mean_khz": sampled["s"],
                    "machine_context": _measurement_point_context(state),
                }
            )
            tune_x.append(sampled["x"])
            tune_y.append(sampled["y"])
            tune_s.append(sampled["s"])
    finally:
        state.adapter.put(state.pvs.rf_setpoint, frf0_hz)
        restore_feedback_after_measurement(state, snapshot)
    fit_order = min(inputs.fit_order, len(delta_hz) - 1)
    fit_x_coeffs = np.polyfit(delta_hz, tune_x, fit_order)
    fit_y_coeffs = np.polyfit(delta_hz, tune_y, fit_order)
    fit_s_coeffs = np.polyfit(delta_hz, tune_s, fit_order)
    fit_x = np.poly1d(fit_x_coeffs)
    fit_y = np.poly1d(fit_y_coeffs)
    fit_s = np.poly1d(fit_s_coeffs)
    frev_khz = SPEED_OF_LIGHT_M_PER_S / 48.0 / 1000.0
    slope_x = float(np.polyder(fit_x)(0.0))
    slope_y = float(np.polyder(fit_y)(0.0))
    slope_s = float(np.polyder(fit_s)(0.0))
    xi = [
        float(-slope_x * frf0_hz * alpha0 / frev_khz),
        float(-slope_y * frf0_hz * alpha0 / frev_khz),
        float(-slope_s * frf0_hz * alpha0 / frev_khz),
    ]
    return MeasurementResult(
        rf_points_hz=np.asarray(rf_points_hz, dtype=float),
        delta_hz=np.asarray(delta_hz, dtype=float),
        tune_x_khz=np.asarray(tune_x, dtype=float),
        tune_y_khz=np.asarray(tune_y, dtype=float),
        tune_s_khz=np.asarray(tune_s, dtype=float),
        fit_x=fit_x,
        fit_y=fit_y,
        fit_s=fit_s,
        xi=xi,
        alpha0=float(alpha0),
        alpha0_details=alpha0_details,
        point_records=point_records,
        fit_x_coeffs=np.asarray(fit_x_coeffs, dtype=float).tolist(),
        fit_y_coeffs=np.asarray(fit_y_coeffs, dtype=float).tolist(),
        fit_s_coeffs=np.asarray(fit_s_coeffs, dtype=float).tolist(),
        initial_rf_hz=float(frf0_hz),
        optics_mode=float(optics_mode or 0.0),
        dmax=float(dmax),
        feedback_snapshot={str(key): float(value) for key, value in snapshot.items()},
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--safe",
        action="store_true",
        help="Read-only preflight mode. Live reads are allowed but machine writes are suppressed.",
    )
    parser.add_argument(
        "--check-alpha0",
        action="store_true",
        help="In --safe mode, also attempt the dynamic alpha0 calculation.",
    )
    parser.add_argument("--ntimes", default="7", help="Number of tune samples at each RF point.")
    parser.add_argument("--npoints", default="11", help="Number of RF points in the sweep.")
    parser.add_argument("--dfmin", default="-2", help="Minimum X-dispersion offset input in mm.")
    parser.add_argument("--dfmax", default="2", help="Maximum X-dispersion offset input in mm.")
    parser.add_argument("--fit-order", default="1", help="Polynomial fit order.")
    parser.add_argument("--delay-set-rf", default="5", help="Delay after each RF step in seconds.")
    parser.add_argument("--delay-mea-tunes", default="1", help="Delay between repeated tune reads in seconds.")
    parser.add_argument("--alpha0", default="dynamic", help="Alpha0 value or 'dynamic'.")
    parser.add_argument("--output", help="Optional text file to save the measured xi vector.")
    parser.add_argument(
        "--log-dir",
        help="Directory where runtime logs and raw measurement payloads will be written. Default: ./betagui_logs/",
    )
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state = create_runtime(
        RuntimeConfig(
            allow_machine_writes=not args.safe,
            log_root=Path(args.log_dir) if args.log_dir else None,
        )
    )
    state.record_event(
        "process_arguments",
        argv=list(argv) if argv is not None else sys.argv[1:],
        safe=args.safe,
    )
    if args.safe:
        preflight = {
            "mode": "safe",
            "snapshot": _machine_snapshot(state),
        }
        print("Legacy-profile read-only preflight")
        print("  rf =", state.adapter.get(state.pvs.rf_setpoint))
        print("  tune_x =", state.adapter.get(state.pvs.tune_x))
        print("  tune_y =", state.adapter.get(state.pvs.tune_y))
        print("  tune_s =", state.adapter.get(state.pvs.tune_s))
        if args.check_alpha0:
            try:
                alpha0, alpha0_details = calculate_alpha0_with_details(
                    state.adapter,
                    state.pvs,
                    harmonic_number=NHARMONIC,
                )
            except Exception as exc:
                state.log("Could not calculate alpha0: %s" % exc)
                alpha0 = None
                alpha0_details = {"error": str(exc)}
            print("  alpha0 =", alpha0)
            preflight["alpha0"] = alpha0
            preflight["alpha0_details"] = alpha0_details
        payload_path = state.write_payload("measurements/preflight.json", preflight)
        state.record_event("safe_preflight_completed", payload_path=payload_path, snapshot=preflight["snapshot"])
        return 0
    alpha0 = None
    if str(args.alpha0).strip() != "dynamic":
        alpha0 = float(args.alpha0)
    inputs = MeasurementInputs(
        n_tune_samples=int(args.ntimes),
        n_rf_points=int(args.npoints),
        delta_x_min_mm=float(args.dfmin),
        delta_x_max_mm=float(args.dfmax),
        fit_order=int(args.fit_order),
        delay_after_rf_s=float(args.delay_set_rf),
        delay_between_tune_reads_s=float(args.delay_mea_tunes),
    )
    measurement_name = state.next_measurement_name("chromaticity")
    start_snapshot = _machine_snapshot(state)
    state.record_event(
        "chromaticity_measurement_started",
        measurement=measurement_name,
        inputs=vars(args),
        start_snapshot=start_snapshot,
    )
    try:
        result = measure_chromaticity(state, inputs, alpha0=alpha0)
    except Exception as exc:
        state.log("Chromaticity measurement failed: %s" % exc)
        payload_path = state.write_payload(
            "measurements/%s_failed.json" % measurement_name,
            {
                "measurement": measurement_name,
                "error": str(exc),
                "inputs": vars(args),
                "start_snapshot": start_snapshot,
            },
        )
        state.record_event(
            "chromaticity_measurement_failed",
            measurement=measurement_name,
            error=str(exc),
            payload_path=payload_path,
        )
        return 1
    set_frf_slowly(state, state.frf0)
    state.last_result = result
    print("Measured xi:")
    print("  xi_x = %.6f" % result.xi[0])
    print("  xi_y = %.6f" % result.xi[1])
    print("  xi_s = %.6f" % result.xi[2])
    print("  alpha0 = %.8f" % result.alpha0)
    payload_path = state.write_payload(
        "measurements/%s.json" % measurement_name,
        {
            "measurement": measurement_name,
            "inputs": vars(args),
            "result": {
                "alpha0": result.alpha0,
                "alpha0_details": result.alpha0_details,
                "xi": result.xi,
                "rf_points_hz": result.rf_points_hz.tolist(),
                "delta_hz": result.delta_hz.tolist(),
                "tune_x_khz": result.tune_x_khz.tolist(),
                "tune_y_khz": result.tune_y_khz.tolist(),
                "tune_s_khz": result.tune_s_khz.tolist(),
                "fit_x_coeffs": result.fit_x_coeffs,
                "fit_y_coeffs": result.fit_y_coeffs,
                "fit_s_coeffs": result.fit_s_coeffs,
                "optics_mode": result.optics_mode,
                "dmax": result.dmax,
                "feedback_snapshot": result.feedback_snapshot,
                "point_records": result.point_records,
            },
            "start_snapshot": start_snapshot,
            "end_snapshot": _machine_snapshot(state),
        },
    )
    state.record_event(
        "chromaticity_measurement_completed",
        measurement=measurement_name,
        xi=result.xi,
        alpha0=result.alpha0,
        payload_path=payload_path,
    )
    if args.output:
        output_path = Path(args.output)
        np.savetxt(output_path, np.asarray(result.xi, dtype=float))
        print("Saved xi to %s" % output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
