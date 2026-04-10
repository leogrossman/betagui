#!/usr/bin/env python3
"""Standalone legacy-style control-room GUI.

By default this behaves like the legacy script and allows live writes.
Use ``--safe`` for read-only preflight.
"""

# ------------------------------------------------------------------------------
# Imports
# ------------------------------------------------------------------------------

import argparse
import json
import os
import platform
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    TK_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host packages
    tk = None
    filedialog = None
    messagebox = None
    TK_AVAILABLE = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host packages
    FigureCanvasTkAgg = None
    Figure = None
    MATPLOTLIB_AVAILABLE = False


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
        measurements_dir = session_dir / "measurements"
        measurements_dir.mkdir()
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


# ------------------------------------------------------------------------------
# EPICS Adapter
# ------------------------------------------------------------------------------


class EpicsUnavailableError(RuntimeError):
    """Raised when pyepics is not available but live access was requested."""


def _import_epics():
    try:
        import epics  # type: ignore
    except ImportError as exc:
        raise EpicsUnavailableError(
            "pyepics is not available; this control-room GUI needs live EPICS."
        ) from exc
    return epics


class PVHandle:
    """Minimal PV wrapper used by the ported code."""

    def __init__(self, pv, name: str, timeout: float):
        self._pv = pv
        self.name = name
        self.timeout = timeout

    def get(self):
        return self._pv.get(timeout=self.timeout, use_monitor=False)

    def put(self, value):
        # WRITE PATH: this changes a live PV when backed by pyepics.
        return self._pv.put(value)

class EpicsAdapter:
    """Tiny factory/cache for PV objects."""

    def __init__(self, timeout: float = 1.0):
        self.timeout = timeout
        self._epics = _import_epics()
        self._cache: Dict[str, PVHandle] = {}

    def pv(self, name: str) -> PVHandle:
        handle = self._cache.get(name)
        if handle is None:
            pv = self._epics.PV(name, connection_timeout=self.timeout)
            handle = PVHandle(pv, name, self.timeout)
            self._cache[name] = handle
        return handle

    def get(self, name: str, default=None):
        value = self.pv(name).get()
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        # WRITE PATH: this changes a live PV when backed by pyepics.
        return self.pv(name).put(value)

# Legacy EPICS names from original/betagui.py.
pvfreqX = "TUNEZRP:measX"
pvfreqY = "TUNEZRP:measY"
pvfreqS = "cumz4x003gp:tuneSyn"
pvfrfSet = "MCLKHGP:setFrq"
pvS1P1 = "S1P1RP:setCur"
pvS1P2 = "S1P2RP:setCur"
pvS2P1 = "S2P1RP:setCur"
pvS2P2 = "S2P2RP:setCur"
pvS2P2K = "S2P2KRP:setCur"
pvS2P2L = "S2P2LRP:setCur"
pvS3P1 = "S3P1RP:setCur"
pvS3P2 = "S3P2RP:setCur"
pvorbit = "ORBITCCP:selRunMode"
pvorbitrdbk = "RMC00VP"
pvfdbsetS = "IGPF:Z:FBCTRL"
pvfdbsetX = "IGPF:X:FBCTRL"
pvfdbsetY = "IGPF:Y:FBCTRL"
pvphasmod = "PAHRP:cmdExtPhasMod"
pvOptTab = "MLSOPCCP:actOptRmpTblSet"
pv10lt = "CUM1ZK3RP:rdLt10"
pv100lt = "CUM1ZK3RP:rdLt100"
pvcurlt = "OPCHECKCCP:calcCurrLife"
QPD1HS = "QPD01ZL2RP:rdSigmaX"
QPD1VS = "QPD01ZL2RP:rdSigmaY"
QPD0HS = "QPD00ZL4RP:rdSigmaX"
QPD0VS = "QPD00ZL4RP:rdSigmaY"
sepdose = "SEKRRP:rdDose"
pvcur = "CUM1ZK3RP:measCur"
pvE = "ERMPCGP:rdRmp"
pvwhitenosie = "WFGENC1CP:rdVolt"
pvUcavSet = "PAHRP:setVoltCav"


@dataclass
class BetaguiPVs:
    """Common PV names used by the legacy tool."""

    tune_x: Optional[str] = pvfreqX
    tune_y: Optional[str] = pvfreqY
    tune_s: Optional[str] = pvfreqS
    rf_setpoint: Optional[str] = pvfrfSet
    optics_mode: Optional[str] = pvOptTab
    orbit_mode: Optional[str] = pvorbit
    orbit_mode_readback: Optional[str] = pvorbitrdbk
    feedback_x: Optional[str] = pvfdbsetX
    feedback_y: Optional[str] = pvfdbsetY
    feedback_s: Optional[str] = pvfdbsetS
    cavity_voltage: Optional[str] = pvUcavSet
    beam_energy: Optional[str] = pvE
    phase_modulation: Optional[str] = pvphasmod
    beam_lifetime_10h: Optional[str] = pv10lt
    beam_lifetime_100h: Optional[str] = pv100lt
    calculated_lifetime: Optional[str] = pvcurlt
    qpd1_sigma_x: Optional[str] = QPD1HS
    qpd1_sigma_y: Optional[str] = QPD1VS
    qpd0_sigma_x: Optional[str] = QPD0HS
    qpd0_sigma_y: Optional[str] = QPD0VS
    dose_rate: Optional[str] = sepdose
    beam_current: Optional[str] = pvcur
    white_noise: Optional[str] = pvwhitenosie
    sext_s1p1: Optional[str] = pvS1P1
    sext_s1p2: Optional[str] = pvS1P2
    sext_s2p1: Optional[str] = pvS2P1
    sext_s2p2: Optional[str] = pvS2P2
    sext_s2p2k: Optional[str] = pvS2P2K
    sext_s2p2l: Optional[str] = pvS2P2L
    sext_s3p1: Optional[str] = pvS3P1
    sext_s3p2: Optional[str] = pvS3P2

    def sextupole_names(self):
        return [
            self.sext_s1p1,
            self.sext_s1p2,
            self.sext_s2p1,
            self.sext_s2p2k,
            self.sext_s2p2l,
            self.sext_s3p1,
            self.sext_s3p2,
        ]

    @classmethod
    def legacy(cls) -> "BetaguiPVs":
        return cls()


# ------------------------------------------------------------------------------
# Measurement Logic
# ------------------------------------------------------------------------------

SPEED_OF_LIGHT_M_PER_S = 299792458.0
REVOLUTION_FREQUENCY_KHZ = SPEED_OF_LIGHT_M_PER_S / 48.0 / 1000.0


def _tune_x_khz_from_pv(raw_value: float) -> float:
    return float(raw_value)


def _tune_y_khz_from_pv(raw_value: float) -> float:
    return float(raw_value)


def _tune_s_khz_from_pv(raw_value: float) -> float:
    # Control-room note:
    # `cumz4x003gp:tuneSyn` appears to be delivered in Hz, while the transverse
    # tune PVs behave like kHz tune frequencies. Convert the synchrotron signal
    # to kHz before comparing or forming unitless tunes.
    return float(raw_value) / 1000.0


def _unitless_tune_from_khz(tune_khz: float) -> float:
    return float(tune_khz) / REVOLUTION_FREQUENCY_KHZ


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


def calculate_alpha0_with_details(adapter, pvs: BetaguiPVs, harmonic_number: int = 80, samples: int = 10):
    if not pvs.tune_s or not pvs.cavity_voltage or not pvs.beam_energy:
        raise ValueError("Dynamic alpha0 requires synchrotron tune, cavity voltage, and beam energy PVs.")
    tune_s_samples_raw = [float(adapter.get(pvs.tune_s, 0.0) or 0.0) for _ in range(samples)]
    tune_s_samples_khz = [_tune_s_khz_from_pv(value) for value in tune_s_samples_raw]
    tune_s_mean_khz = float(np.mean(tune_s_samples_khz))
    tune_s_mean = _unitless_tune_from_khz(tune_s_mean_khz)
    rf_hz = float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0)
    cavity_voltage_v = float(adapter.get(pvs.cavity_voltage, 0.0) or 0.0) * 1000.0
    energy_ev = float(adapter.get(pvs.beam_energy, 0.0) or 0.0) * 1e6
    if tune_s_mean == 0.0 or cavity_voltage_v == 0.0 or energy_ev == 0.0:
        raise ValueError("Synchrotron tune, cavity voltage, and beam energy must be non-zero.")
    # Porting note:
    # `cumz4x003gp:tuneSyn` is a synchrotron tune, not a synchrotron frequency.
    # Use the standard relation:
    #   Qs^2 = alpha0 * h * V / (2*pi*E)
    # so
    #   alpha0 = Qs^2 * 2*pi*E / (h*V)
    alpha0 = (tune_s_mean ** 2) * 2.0 * np.pi * energy_ev / (harmonic_number * cavity_voltage_v)
    details = {
        "mode": "dynamic",
        "harmonic_number": harmonic_number,
        "tune_s_samples_raw": tune_s_samples_raw,
        "tune_s_samples_khz": tune_s_samples_khz,
        "tune_s_mean_khz": tune_s_mean_khz,
        "tune_s_mean_unitless": tune_s_mean,
        "rf_hz": rf_hz,
        "cavity_voltage_v": cavity_voltage_v,
        "beam_energy_ev": energy_ev,
        "alpha0": alpha0,
    }
    return float(alpha0), details


def calculate_alpha0(adapter, pvs: BetaguiPVs, harmonic_number: int = 80, samples: int = 10) -> float:
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


def ramp_rf(adapter, pv_name: str, target_hz: float, steps: int = 10):
    if not pv_name:
        raise ValueError("No RF PV configured for this profile.")
    start_hz = float(adapter.get(pv_name, target_hz) or target_hz)
    for value in np.linspace(start_hz, target_hz, steps):
        # WRITE PATH: this changes RF setpoint on live hardware when using the
        # real EPICS adapter.
        adapter.put(pv_name, float(value))


def sample_tunes(
    adapter,
    pvs: BetaguiPVs,
    n_samples: int,
    delay_between_reads_s: float = 0.0,
) -> Dict[str, float]:
    if not pvs.tune_x or not pvs.tune_y:
        raise ValueError("This profile requires at least X and Y tune PVs.")
    tune_x = []
    tune_y = []
    tune_s = []
    tune_s_raw = []
    for sample_index in range(n_samples):
        tune_x_raw = float(adapter.get(pvs.tune_x, 0.0) or 0.0)
        tune_y_raw = float(adapter.get(pvs.tune_y, 0.0) or 0.0)
        tune_x.append(_tune_x_khz_from_pv(tune_x_raw))
        tune_y.append(_tune_y_khz_from_pv(tune_y_raw))
        if pvs.tune_s:
            tune_s_raw_value = float(adapter.get(pvs.tune_s, 0.0) or 0.0)
            tune_s_raw.append(tune_s_raw_value)
            tune_s.append(_tune_s_khz_from_pv(tune_s_raw_value))
        else:
            tune_s_raw.append(0.0)
            tune_s.append(0.0)
        if sample_index != n_samples - 1 and delay_between_reads_s > 0.0:
            time.sleep(delay_between_reads_s)
    return {
        "x": average_tune_samples(tune_x),
        "y": average_tune_samples(tune_y),
        "s": average_tune_samples(tune_s),
        "raw_x": tune_x,
        "raw_y": tune_y,
        "raw_s": tune_s,
        "raw_s_pv": tune_s_raw,
    }


def measure_chromaticity(
    adapter,
    pvs: BetaguiPVs,
    inputs: MeasurementInputs,
    alpha0: Optional[float] = None,
    harmonic_number: int = 80,
    progress_logger=None,
) -> MeasurementResult:
    if not pvs.rf_setpoint:
        raise ValueError("No RF PV configured for this profile.")
    frf0_hz = float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0)
    alpha0_details = {"mode": "fixed", "alpha0": float(alpha0)} if alpha0 is not None else {}
    if alpha0 is None:
        alpha0, alpha0_details = calculate_alpha0_with_details(
            adapter,
            pvs,
            harmonic_number=harmonic_number,
        )
    optics_mode = adapter.get(pvs.optics_mode, 0) if pvs.optics_mode else 0
    dmax = optics_mode_to_dmax(optics_mode)
    rf_points_hz = build_rf_range(
        frf0_hz=frf0_hz,
        alpha0=alpha0,
        dmax=dmax,
        delta_x_min_mm=inputs.delta_x_min_mm,
        delta_x_max_mm=inputs.delta_x_max_mm,
        n_points=inputs.n_rf_points,
    )
    delta_hz = rf_points_hz - frf0_hz
    tune_x = []
    tune_y = []
    tune_s = []
    point_records: List[Dict[str, object]] = []
    estimated_point_time_s = inputs.delay_after_rf_s + max(inputs.n_tune_samples - 1, 0) * inputs.delay_between_tune_reads_s
    for point_index, rf_hz in enumerate(rf_points_hz, start=1):
        if progress_logger is not None:
            remaining_points = len(rf_points_hz) - point_index
            progress_logger(
                "RF sweep point %d/%d: target %.6f (step %.6f, est. %.1f s remaining)"
                % (
                    point_index,
                    len(rf_points_hz),
                    float(rf_hz),
                    float(delta_hz[point_index - 1]),
                    max(remaining_points, 0) * estimated_point_time_s,
                )
            )
        ramp_rf(adapter, pvs.rf_setpoint, float(rf_hz))
        if inputs.delay_after_rf_s > 0.0:
            time.sleep(inputs.delay_after_rf_s)
        sampled = sample_tunes(
            adapter,
            pvs,
            inputs.n_tune_samples,
            delay_between_reads_s=inputs.delay_between_tune_reads_s,
        )
        point_records.append(
            {
                "rf_target_hz": float(rf_hz),
                "rf_readback_hz": float(adapter.get(pvs.rf_setpoint, rf_hz) or rf_hz),
                "tune_x_samples_khz": sampled["raw_x"],
                "tune_y_samples_khz": sampled["raw_y"],
                "tune_s_samples_raw": sampled["raw_s_pv"],
                "tune_s_samples_khz": sampled["raw_s"],
                "tune_x_mean_khz": sampled["x"],
                "tune_y_mean_khz": sampled["y"],
                "tune_s_mean_khz": sampled["s"],
                "tune_x_mean_unitless": _unitless_tune_from_khz(sampled["x"]),
                "tune_y_mean_unitless": _unitless_tune_from_khz(sampled["y"]),
                "tune_s_mean_unitless": _unitless_tune_from_khz(sampled["s"]),
                "machine_context": _measurement_point_context_from_adapter(adapter, pvs),
            }
        )
        tune_x.append(sampled["x"])
        tune_y.append(sampled["y"])
        tune_s.append(sampled["s"])
    ramp_rf(adapter, pvs.rf_setpoint, frf0_hz)
    fit_order = min(inputs.fit_order, len(delta_hz) - 1)
    fit_x_coeffs = np.polyfit(delta_hz, tune_x, fit_order)
    fit_y_coeffs = np.polyfit(delta_hz, tune_y, fit_order)
    fit_s_coeffs = np.polyfit(delta_hz, tune_s, fit_order)
    fit_x = np.poly1d(fit_x_coeffs)
    fit_y = np.poly1d(fit_y_coeffs)
    fit_s = np.poly1d(fit_s_coeffs)
    # Porting fix: the legacy expression was written as `1.0/(48.0/constants.c)/1000`
    # and annotated with `frev = 6246 kHz`. The comment matches `c / 48 / 1000`,
    # so use that intended value here.
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
        rf_points_hz=np.array(rf_points_hz, dtype=float),
        delta_hz=np.array(delta_hz, dtype=float),
        tune_x_khz=np.array(tune_x, dtype=float),
        tune_y_khz=np.array(tune_y, dtype=float),
        tune_s_khz=np.array(tune_s, dtype=float),
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
    )


def disable_feedback_for_measurement(adapter, pvs: BetaguiPVs) -> Dict[str, float]:
    """Snapshot and disable feedback/orbit correction."""
    snapshot = {}
    if pvs.feedback_x:
        snapshot[pvs.feedback_x] = float(adapter.get(pvs.feedback_x, 0.0) or 0.0)
    if pvs.feedback_y:
        snapshot[pvs.feedback_y] = float(adapter.get(pvs.feedback_y, 0.0) or 0.0)
    if pvs.feedback_s:
        snapshot[pvs.feedback_s] = float(adapter.get(pvs.feedback_s, 0.0) or 0.0)
    if pvs.orbit_mode and pvs.orbit_mode_readback:
        snapshot[pvs.orbit_mode] = float(adapter.get(pvs.orbit_mode_readback, 0.0) or 0.0)
    # WRITE PATH: on live hardware this disables feedback/orbit correction.
    if pvs.feedback_x:
        adapter.put(pvs.feedback_x, 0)
    if pvs.feedback_y:
        adapter.put(pvs.feedback_y, 0)
    if pvs.feedback_s:
        adapter.put(pvs.feedback_s, 0)
    if pvs.orbit_mode:
        adapter.put(pvs.orbit_mode, 0)
    return snapshot


def restore_feedback_after_measurement(adapter, snapshot: Dict[str, float]):
    """Restore the values returned by disable_feedback_for_measurement()."""
    for pv_name, value in snapshot.items():
        # WRITE PATH: on live hardware this restores feedback/orbit correction.
        adapter.put(pv_name, value)


def apply_sextupole_response(adapter, delta_chrom: Sequence[float], response_matrix: np.ndarray, mat_status: int, pvs: BetaguiPVs) -> Dict[str, float]:
    """Apply the legacy matrix logic in a testable function.

    Returns a dict of increments that were applied.
    """

    delta = np.asarray(delta_chrom, dtype=float).reshape(-1)
    matrix = np.asarray(response_matrix, dtype=float)
    increments = np.dot(matrix, delta[: matrix.shape[0]])
    applied: Dict[str, float] = {}

    def add_current(pv_name: str, increment: float):
        if not pv_name:
            return
        current = float(adapter.get(pv_name, 0.0) or 0.0)
        new_value = current + float(increment)
        # WRITE PATH: on live hardware this changes sextupole current setpoints.
        adapter.put(pv_name, new_value)
        applied[pv_name] = float(increment)

    add_current(pvs.sext_s1p2, increments[0])
    if mat_status in (1, 3):
        add_current(pvs.sext_s1p1, increments[0])
        add_current(pvs.sext_s2p1, increments[1])
    add_current(pvs.sext_s2p2k, increments[1])
    add_current(pvs.sext_s2p2l, increments[1])
    if matrix.shape[0] == 3:
        if mat_status == 3:
            add_current(pvs.sext_s3p1, increments[2])
        add_current(pvs.sext_s3p2, increments[2])
    return applied


def measure_chromaticity_with_feedback_control(
    adapter,
    pvs: BetaguiPVs,
    inputs: MeasurementInputs,
    alpha0: Optional[float] = None,
    harmonic_number: int = 80,
    progress_logger=None,
) -> MeasurementResult:
    """Legacy-like wrapper that disables/restores feedback around measurement."""
    snapshot = disable_feedback_for_measurement(adapter, pvs)
    try:
        result = measure_chromaticity(
            adapter=adapter,
            pvs=pvs,
            inputs=inputs,
            alpha0=alpha0,
            harmonic_number=harmonic_number,
            progress_logger=progress_logger,
        )
        result.feedback_snapshot = {str(key): float(value) for key, value in snapshot.items()}
        return result
    finally:
        restore_feedback_after_measurement(adapter, snapshot)


# ------------------------------------------------------------------------------
# Legacy Port Core
# ------------------------------------------------------------------------------

LARGE_FONT = ("Verdana", 11)
DEFAULT_FONT = ("Helvetica", 12)
NHARMONIC = 80
BPM_POSITIONS = [
    1.2034,
    2.1040,
    4.2490,
    5.2290,
    6.2040,
    8.1872,
    9.0466,
    14.9534,
    15.8540,
    17.9990,
    18.9790,
    19.9540,
    21.9372,
    22.7966,
    25.2034,
    26.1040,
    28.2490,
    29.2290,
    30.2040,
    32.1872,
    33.0466,
    38.9534,
    39.8540,
    41.9990,
    42.9790,
    43.9540,
    45.9372,
    46.7966,
]
class UnavailableAdapter:
    """Read-only placeholder used when live EPICS is unavailable."""

    def get(self, name: str, default=None):
        return default

    def put(self, name: str, value):
        return False


class GuardedAdapter:
    """Thin live-EPICS wrapper with optional write suppression."""

    def __init__(self, adapter, allow_machine_writes: bool, logger, event_recorder=None):
        self._adapter = adapter
        self.allow_machine_writes = allow_machine_writes
        self._logger = logger
        self._event_recorder = event_recorder

    def get(self, name: str, default=None):
        try:
            return self._adapter.get(name, default)
        except Exception as exc:  # pragma: no cover - depends on external EPICS
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
            except Exception as exc:  # pragma: no cover - depends on external EPICS
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
    allow_machine_writes: bool = False
    auto_load_default_matrix: bool = True
    log_root: Optional[Path] = None


@dataclass
class RuntimeState:
    config: RuntimeConfig
    pvs: BetaguiPVs = field(default_factory=BetaguiPVs.legacy)
    adapter: Optional[GuardedAdapter] = None
    session_logger: Optional[SessionLogger] = None
    messages: List[str] = field(default_factory=list)
    stop_requested: bool = False
    frf0: float = 0.0
    ini_sext: List[float] = field(default_factory=list)
    ini_fdb: List[float] = field(default_factory=list)
    ini_orbit: float = 0.0
    saved_settings_valid: bool = False
    B: np.ndarray = field(default_factory=lambda: np.zeros((3, 3)))
    bump_option: int = 4
    bump_dim: int = 3
    mat_status: int = 4
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
    config = config or RuntimeConfig()
    state = RuntimeState(config=config, pvs=BetaguiPVs.legacy())
    try:
        state.session_logger = SessionLogger.create(config.log_root, "betagui_gui")
    except Exception as exc:
        print("Could not create session logger: %s" % exc)
        state.session_logger = None
    if state.session_logger is not None:
        state.log("Session log directory: %s" % state.session_logger.session_dir)
        state.write_payload(
            "session_metadata.json",
            {
                "script": "control_room/betagui.py",
                "cwd": str(Path.cwd()),
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "python": sys.version,
                "platform": platform.platform(),
                "allow_machine_writes": config.allow_machine_writes,
            },
        )
        state.record_event(
            "session_start",
            script="control_room/betagui.py",
            cwd=str(Path.cwd()),
            hostname=socket.gethostname(),
            allow_machine_writes=config.allow_machine_writes,
        )
    try:
        base_adapter = EpicsAdapter()
        state.log("Using live EPICS adapter.")
    except EpicsUnavailableError as exc:
        state.log(str(exc))
        base_adapter = UnavailableAdapter()

    state.adapter = GuardedAdapter(
        adapter=base_adapter,
        allow_machine_writes=config.allow_machine_writes,
        logger=state.log,
        event_recorder=state.record_event,
    )
    save_setting(state)
    if config.auto_load_default_matrix:
        load_default_matrix(state)
    return state


def _get_float(state: RuntimeState, pv_name: str, default: float = 0.0) -> float:
    if not pv_name:
        return default
    value = state.adapter.get(pv_name, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        state.log("Non-numeric value from %s: %r" % (pv_name, value))
        return default


def _sextupole_snapshot(state: RuntimeState) -> Dict[str, float]:
    names = [
        ("S1P1", state.pvs.sext_s1p1),
        ("S1P2", state.pvs.sext_s1p2),
        ("S2P1", state.pvs.sext_s2p1),
        ("S2P2", state.pvs.sext_s2p2),
        ("S2P2K", state.pvs.sext_s2p2k),
        ("S2P2L", state.pvs.sext_s2p2l),
        ("S3P1", state.pvs.sext_s3p1),
        ("S3P2", state.pvs.sext_s3p2),
    ]
    return {label: _get_float(state, pv_name, 0.0) for label, pv_name in names if pv_name}


def _machine_snapshot(state: RuntimeState) -> Dict[str, object]:
    tune_x_raw = _get_float(state, state.pvs.tune_x, 0.0)
    tune_y_raw = _get_float(state, state.pvs.tune_y, 0.0)
    tune_s_raw = _get_float(state, state.pvs.tune_s, 0.0)
    tune_x_khz = _tune_x_khz_from_pv(tune_x_raw)
    tune_y_khz = _tune_y_khz_from_pv(tune_y_raw)
    tune_s_khz = _tune_s_khz_from_pv(tune_s_raw)
    return {
        "timestamp": time.time(),
        "rf_hz": _get_float(state, state.pvs.rf_setpoint, 0.0),
        "tune_x_raw": tune_x_raw,
        "tune_y_raw": tune_y_raw,
        "tune_s_raw": tune_s_raw,
        "tune_x_khz": tune_x_khz,
        "tune_y_khz": tune_y_khz,
        "tune_s_khz": tune_s_khz,
        "tune_x_unitless": _unitless_tune_from_khz(tune_x_khz),
        "tune_y_unitless": _unitless_tune_from_khz(tune_y_khz),
        "tune_s_unitless": _unitless_tune_from_khz(tune_s_khz),
        "optics_mode": _get_float(state, state.pvs.optics_mode, 0.0),
        "orbit_mode_readback": _get_float(state, state.pvs.orbit_mode_readback, 0.0),
        "feedback_x": _get_float(state, state.pvs.feedback_x, 0.0),
        "feedback_y": _get_float(state, state.pvs.feedback_y, 0.0),
        "feedback_s": _get_float(state, state.pvs.feedback_s, 0.0),
        "cavity_voltage_kv": _get_float(state, state.pvs.cavity_voltage, 0.0),
        "beam_energy_mev": _get_float(state, state.pvs.beam_energy, 0.0),
        "beam_current": _get_float(state, state.pvs.beam_current, 0.0),
        "lifetime_10h": _get_float(state, state.pvs.beam_lifetime_10h, 0.0),
        "lifetime_100h": _get_float(state, state.pvs.beam_lifetime_100h, 0.0),
        "calculated_lifetime": _get_float(state, state.pvs.calculated_lifetime, 0.0),
        "qpd1_sigma_x": _get_float(state, state.pvs.qpd1_sigma_x, 0.0),
        "qpd1_sigma_y": _get_float(state, state.pvs.qpd1_sigma_y, 0.0),
        "qpd0_sigma_x": _get_float(state, state.pvs.qpd0_sigma_x, 0.0),
        "qpd0_sigma_y": _get_float(state, state.pvs.qpd0_sigma_y, 0.0),
        "dose_rate": _get_float(state, state.pvs.dose_rate, 0.0),
        "white_noise": _get_float(state, state.pvs.white_noise, 0.0),
        "sextupoles": _sextupole_snapshot(state),
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
        "beam_current": snapshot["beam_current"],
        "lifetime_10h": snapshot["lifetime_10h"],
        "lifetime_100h": snapshot["lifetime_100h"],
        "calculated_lifetime": snapshot["calculated_lifetime"],
        "qpd1_sigma_x": snapshot["qpd1_sigma_x"],
        "qpd1_sigma_y": snapshot["qpd1_sigma_y"],
        "qpd0_sigma_x": snapshot["qpd0_sigma_x"],
        "qpd0_sigma_y": snapshot["qpd0_sigma_y"],
        "dose_rate": snapshot["dose_rate"],
        "white_noise": snapshot["white_noise"],
        "sextupoles": snapshot["sextupoles"],
    }


def _measurement_point_context_from_adapter(adapter, pvs: BetaguiPVs) -> Dict[str, object]:
    tune_x_raw = float(adapter.get(pvs.tune_x, 0.0) or 0.0)
    tune_y_raw = float(adapter.get(pvs.tune_y, 0.0) or 0.0)
    tune_s_raw = float(adapter.get(pvs.tune_s, 0.0) or 0.0)
    tune_x_khz = _tune_x_khz_from_pv(tune_x_raw)
    tune_y_khz = _tune_y_khz_from_pv(tune_y_raw)
    tune_s_khz = _tune_s_khz_from_pv(tune_s_raw)
    snapshot = {
        "rf_hz": float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0),
        "tune_x_raw": tune_x_raw,
        "tune_y_raw": tune_y_raw,
        "tune_s_raw": tune_s_raw,
        "tune_x_khz": tune_x_khz,
        "tune_y_khz": tune_y_khz,
        "tune_s_khz": tune_s_khz,
        "tune_x_unitless": _unitless_tune_from_khz(tune_x_khz),
        "tune_y_unitless": _unitless_tune_from_khz(tune_y_khz),
        "tune_s_unitless": _unitless_tune_from_khz(tune_s_khz),
        "optics_mode": float(adapter.get(pvs.optics_mode, 0.0) or 0.0),
        "orbit_mode_readback": float(adapter.get(pvs.orbit_mode_readback, 0.0) or 0.0),
        "feedback_x": float(adapter.get(pvs.feedback_x, 0.0) or 0.0),
        "feedback_y": float(adapter.get(pvs.feedback_y, 0.0) or 0.0),
        "feedback_s": float(adapter.get(pvs.feedback_s, 0.0) or 0.0),
        "cavity_voltage_kv": float(adapter.get(pvs.cavity_voltage, 0.0) or 0.0),
        "beam_energy_mev": float(adapter.get(pvs.beam_energy, 0.0) or 0.0),
        "beam_current": float(adapter.get(pvs.beam_current, 0.0) or 0.0),
        "lifetime_10h": float(adapter.get(pvs.beam_lifetime_10h, 0.0) or 0.0),
        "lifetime_100h": float(adapter.get(pvs.beam_lifetime_100h, 0.0) or 0.0),
        "calculated_lifetime": float(adapter.get(pvs.calculated_lifetime, 0.0) or 0.0),
        "qpd1_sigma_x": float(adapter.get(pvs.qpd1_sigma_x, 0.0) or 0.0),
        "qpd1_sigma_y": float(adapter.get(pvs.qpd1_sigma_y, 0.0) or 0.0),
        "qpd0_sigma_x": float(adapter.get(pvs.qpd0_sigma_x, 0.0) or 0.0),
        "qpd0_sigma_y": float(adapter.get(pvs.qpd0_sigma_y, 0.0) or 0.0),
        "dose_rate": float(adapter.get(pvs.dose_rate, 0.0) or 0.0),
        "white_noise": float(adapter.get(pvs.white_noise, 0.0) or 0.0),
        "sextupoles": {
            label: float(adapter.get(name, 0.0) or 0.0)
            for label, name in [
                ("S1P1", pvs.sext_s1p1),
                ("S1P2", pvs.sext_s1p2),
                ("S2P1", pvs.sext_s2p1),
                ("S2P2", pvs.sext_s2p2),
                ("S2P2K", pvs.sext_s2p2k),
                ("S2P2L", pvs.sext_s2p2l),
                ("S3P1", pvs.sext_s3p1),
                ("S3P2", pvs.sext_s3p2),
            ]
            if name
        },
    }
    return snapshot


def save_setting(state: RuntimeState):
    """Save current machine values for later reset.

    A valid reset point requires at least a readable RF value. If that critical
    read is missing, keep the previous saved state instead of silently storing
    zeros that would later drive RF to 0 on reset.
    """
    raw_rf = state.adapter.get(state.pvs.rf_setpoint, None)
    if raw_rf in (None, ""):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is unavailable.")
        state.record_event("save_setting", success=False, reason="rf_unavailable")
        return False
    try:
        frf0 = float(raw_rf)
    except (TypeError, ValueError):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is non-numeric (%r)." % (raw_rf,))
        state.record_event("save_setting", success=False, reason="rf_non_numeric", raw_rf=raw_rf)
        return False

    state.ini_sext = [_get_float(state, name, 0.0) for name in state.pvs.sextupole_names()]
    state.ini_fdb = [
        _get_float(state, state.pvs.feedback_x, 0.0),
        _get_float(state, state.pvs.feedback_y, 0.0),
        _get_float(state, state.pvs.feedback_s, 0.0),
    ]
    state.frf0 = frf0
    state.ini_orbit = _get_float(state, state.pvs.orbit_mode_readback, 0.0)
    state.saved_settings_valid = True
    state.log("Saved current settings.")
    state.record_event(
        "save_setting",
        success=True,
        frf0=state.frf0,
        ini_fdb=state.ini_fdb,
        ini_orbit=state.ini_orbit,
        ini_sext=state.ini_sext,
        snapshot=_machine_snapshot(state),
    )
    return True


def bumppolyfit(x, p1, p2):
    """Legacy helper retained for compatibility with later scan work."""
    return p1 * x * x + p2 * x


def set_frf_slowly(state: RuntimeState, target_frf_in_hz: float, n_steps: int = 10, delay_s: float = 0.2):
    """WRITE PATH: ramps the RF setpoint."""
    start_frf_in_hz = _get_float(state, state.pvs.rf_setpoint, target_frf_in_hz)
    rf_steps = np.linspace(start_frf_in_hz, target_frf_in_hz, n_steps)
    for value in rf_steps:
        state.adapter.put(state.pvs.rf_setpoint, float(value))
        if state.can_write_machine and delay_s > 0.0:
            time.sleep(delay_s)
    state.log("RF now at PV value %.6f" % float(rf_steps[-1]))


def set_Isextupole_slowly(state: RuntimeState, sname: str, target_current: float, n_steps: int = 10, delay_s: float = 0.2):
    """WRITE PATH: legacy helper name kept for sextupole current ramps."""
    start_current = _get_float(state, sname, target_current)
    for value in np.linspace(start_current, target_current, n_steps):
        state.adapter.put(sname, float(value))
        if state.can_write_machine and delay_s > 0.0:
            time.sleep(delay_s)


def set_sext_degauss(state: RuntimeState, sextlist: Sequence[str], target: float):
    """WRITE PATH: legacy helper name retained for future control-room studies.

    The original helper is present but not exercised by the main chromaticity
    workflow. Keep the name and behavior simple here so later debugging can
    still compare side by side with the Python 2 file.
    """
    for pv_name in sextlist:
        set_Isextupole_slowly(state, pv_name, target)


def set_all2ini(state: RuntimeState):
    """WRITE PATH: restore RF, sextupoles, feedback, orbit, and phase modulation."""
    if not state.saved_settings_valid:
        state.log("Reset is unavailable: no valid saved settings are stored.")
        state.record_event("reset_skipped", reason="no_valid_saved_settings")
        return False
    state.log("Resetting saved parameters.")
    before_snapshot = _machine_snapshot(state)
    set_frf_slowly(state, state.frf0)
    for pv_name, value in zip(state.pvs.sextupole_names(), state.ini_sext):
        if pv_name:
            state.adapter.put(pv_name, value)
    if state.pvs.feedback_x:
        state.adapter.put(state.pvs.feedback_x, state.ini_fdb[0])
    if state.pvs.feedback_y:
        state.adapter.put(state.pvs.feedback_y, state.ini_fdb[1])
    if state.pvs.feedback_s:
        state.adapter.put(state.pvs.feedback_s, state.ini_fdb[2])
    if state.pvs.orbit_mode:
        state.adapter.put(state.pvs.orbit_mode, state.ini_orbit)
    if state.pvs.phase_modulation:
        state.adapter.put(state.pvs.phase_modulation, "disabled")
    state.record_event(
        "reset_completed",
        before_snapshot=before_snapshot,
        after_snapshot=_machine_snapshot(state),
    )
    return True


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
    if "tune_s_mean_khz" in details:
        state.log(
            "alpha0 inputs: tuneSyn raw=%r, tuneSyn_khz=%.6f, Qs=%.6f, Ucav=%.3f kV, E=%.3f MeV"
            % (
                details.get("tune_s_samples_raw", ["?"])[0] if details.get("tune_s_samples_raw") else "?",
                float(details["tune_s_mean_khz"]),
                float(details["tune_s_mean_unitless"]),
                float(details["cavity_voltage_v"]) / 1000.0,
                float(details["beam_energy_ev"]) / 1.0e6,
            )
        )
    state.record_event("alpha0_calculated", details=details, snapshot=_machine_snapshot(state))
    return alpha0


def BPDM():
    """Legacy BPM helper kept close to the original behavior."""
    return BPM_POSITIONS, [0.0 for _ in BPM_POSITIONS]


def set_all_sexts(state: RuntimeState, delta_chrom: Sequence[float]):
    """WRITE PATH: apply inverse response matrix to sextupole currents."""
    before_snapshot = _sextupole_snapshot(state)
    try:
        applied = apply_sextupole_response(
            adapter=state.adapter,
            delta_chrom=delta_chrom,
            response_matrix=state.B,
            mat_status=state.mat_status,
            pvs=state.pvs,
        )
    except Exception as exc:
        state.log("Could not apply sextupole correction: %s" % exc)
        state.record_event("sextupole_correction_failed", delta_chrom=list(delta_chrom), error=str(exc))
        return {}
    state.log("Applied sextupole increments: %s" % applied)
    state.record_event(
        "sextupole_correction",
        delta_chrom=list(delta_chrom),
        applied=applied,
        before_snapshot=before_snapshot,
        after_snapshot=_sextupole_snapshot(state),
    )
    return applied


def _secondary_scan_groups(state: RuntimeState) -> List[Tuple[str, List[str]]]:
    """Return the four sextupole groups used by the legacy secondary window."""
    s2p2_group = []
    if state.pvs.sext_s2p2:
        s2p2_group.append(state.pvs.sext_s2p2)
    else:
        for name in (state.pvs.sext_s2p2k, state.pvs.sext_s2p2l):
            if name:
                s2p2_group.append(name)
    groups = [
        ("S1", [name for name in (state.pvs.sext_s1p1, state.pvs.sext_s1p2) if name]),
        ("S2P1", [name for name in (state.pvs.sext_s2p1,) if name]),
        ("S2P2", s2p2_group),
        ("S3", [name for name in (state.pvs.sext_s3p1, state.pvs.sext_s3p2) if name]),
    ]
    return groups


def _set_group_current(state: RuntimeState, pv_names: Sequence[str], target_current: float):
    """WRITE PATH: set all PVs in a sextupole family/group to one current."""
    for pv_name in pv_names:
        state.adapter.put(pv_name, float(target_current))


def _family_reference_currents(state: RuntimeState) -> List[float]:
    groups = _secondary_scan_groups(state)
    references = []
    for _, pv_names in groups:
        if not pv_names:
            references.append(0.0)
            continue
        references.append(_get_float(state, pv_names[0], 0.0))
    return references


def _fit_bumppoly_terms(x_values: np.ndarray, y_values: np.ndarray) -> np.ndarray:
    """Fit y = p1*x^2 + p2*x with zero intercept, matching the legacy intent."""
    design = np.column_stack((x_values * x_values, x_values))
    coeffs, _, _, _ = np.linalg.lstsq(design, y_values, rcond=None)
    return np.asarray(coeffs, dtype=float)


def measure_poly_response_matrix(
    state: RuntimeState,
    entry_values: Dict[str, str],
    scan_ranges: Sequence[Tuple[float, float]],
    output_dir: Path,
) -> Optional[np.ndarray]:
    """WRITE PATH: legacy secondary-window polynomial response measurement.

    Porting note:
    The original code calls a missing helper `setcur(...)` and later uses a
    float index when choosing the reference row. This port keeps the same
    workflow but repairs those two execution blockers explicitly.
    """
    if not state.can_write_machine:
        state.log("Polynomial scan measurement needs write access.")
        return None

    groups = _secondary_scan_groups(state)
    if len(scan_ranges) != len(groups):
        state.log("Expected %d scan ranges, got %d." % (len(groups), len(scan_ranges)))
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = _family_reference_currents(state)
    matrix = np.zeros((3, len(groups) * 2))
    state.stop_requested = False
    state.log("Starting legacy-style polynomial sextupole scan.")
    state.record_event(
        "poly_scan_started",
        output_dir=str(output_dir),
        scan_ranges=scan_ranges,
        baseline=baseline,
    )

    try:
        for family_index, ((family_name, pv_names), (delta_min, delta_max)) in enumerate(zip(groups, scan_ranges)):
            if state.stop_requested:
                state.log("Polynomial scan stopped before family %s." % family_name)
                return None
            if not pv_names:
                state.log("No PVs configured for family %s." % family_name)
                return None

            fit_points = max(int(round(delta_max - delta_min)) + 1, 2)
            current_range = np.linspace(
                float(delta_min) + baseline[family_index],
                float(delta_max) + baseline[family_index],
                fit_points,
            )
            bump_data = np.zeros((fit_points, len(groups) + 3))

            for row_index, target_current in enumerate(current_range):
                if state.stop_requested:
                    state.log("Polynomial scan stopped during family %s." % family_name)
                    return None
                _set_group_current(state, pv_names, float(target_current))
                family_currents = _family_reference_currents(state)
                xi_mea = MeaChrom(state, entry_values)
                if xi_mea is None:
                    state.log("Polynomial scan aborted during family %s." % family_name)
                    return None
                bump_data[row_index, :] = family_currents + list(xi_mea)

            raw_path = output_dir / ("bumpdataS%d.txt" % (family_index + 1))
            np.savetxt(raw_path, bump_data)

            # Porting fix: the legacy code tries to subtract a reference row
            # with a float index. Use the row closest to the starting current.
            reference_row = int(np.argmin(np.abs(bump_data[:, family_index] - baseline[family_index])))
            normalized = bump_data - bump_data[reference_row, :]

            x_values = normalized[:, family_index]
            for xi_index in range(3):
                coeffs = _fit_bumppoly_terms(x_values, normalized[:, len(groups) + xi_index])
                matrix[xi_index, family_index * 2] = coeffs[0]
                matrix[xi_index, family_index * 2 + 1] = coeffs[1]

            # Restore the scanned family to its starting current before moving on.
            _set_group_current(state, pv_names, baseline[family_index])

        np.savetxt(output_dir / "ploy_co_mat.txt", matrix)
        state.log("Saved polynomial response matrix to %s." % (output_dir / "ploy_co_mat.txt"))
        state.record_event(
            "poly_scan_completed",
            output_dir=str(output_dir),
            matrix=matrix.tolist(),
        )
        return matrix
    finally:
        for (_, pv_names), current in zip(groups, baseline):
            _set_group_current(state, pv_names, current)


def start_poly(state: RuntimeState, entry_values: Dict[str, str], scan_ranges, output_dir: Path):
    """Legacy callback name kept for easier comparison with original/betagui.py."""
    return measure_poly_response_matrix(state, entry_values, scan_ranges, output_dir)


def _scan_output_dir() -> Path:
    timestamp = time.strftime("%H:%M:%S_%d%b%Y")
    return Path.cwd() / timestamp


def _candidate_settings_from_poly_matrix(
    baseline_currents: Sequence[float],
    scan_ranges: Sequence[Tuple[float, float, int]],
    xi_ranges: Sequence[Tuple[float, float]],
    matrix: np.ndarray,
) -> np.ndarray:
    """Generate candidate sextupole settings from the legacy polynomial model."""
    if matrix.shape != (3, 8):
        raise ValueError("Polynomial matrix must have shape (3, 8).")
    if len(scan_ranges) != 4:
        raise ValueError("Expected four sextupole scan ranges.")
    if len(baseline_currents) != 7:
        raise ValueError("Expected seven baseline sextupole currents.")

    axes = []
    for delta_min, delta_max, count in scan_ranges:
        axes.append(np.linspace(float(delta_min), float(delta_max), int(count)))

    rows = []
    for sa in axes[0]:
        for sb in axes[1]:
            for sc in axes[2]:
                for sd in axes[3]:
                    dxix = (
                        sa * sa * matrix[0, 0]
                        + sa * matrix[0, 1]
                        + sb * sb * matrix[0, 2]
                        + sb * matrix[0, 3]
                        + sc * sc * matrix[0, 4]
                        + sc * matrix[0, 5]
                        + sd * sd * matrix[0, 6]
                        + sd * matrix[0, 7]
                    )
                    dxiy = (
                        sa * sa * matrix[1, 0]
                        + sa * matrix[1, 1]
                        + sb * sb * matrix[1, 2]
                        + sb * matrix[1, 3]
                        + sc * sc * matrix[1, 4]
                        + sc * matrix[1, 5]
                        + sd * sd * matrix[1, 6]
                        + sd * matrix[1, 7]
                    )
                    if not (xi_ranges[0][0] < dxix < xi_ranges[0][1]):
                        continue
                    if not (xi_ranges[1][0] < dxiy < xi_ranges[1][1]):
                        continue
                    rows.append(
                        [
                            baseline_currents[0] + sa,
                            baseline_currents[1] + sa,
                            baseline_currents[2] + sb,
                            baseline_currents[3] + sc,
                            baseline_currents[4] + sc,
                            baseline_currents[5] + sd,
                            baseline_currents[6] + sd,
                        ]
                    )

    if not rows:
        return np.zeros((0, 7))
    return np.asarray(rows, dtype=float)


def _collect_scan_diagnostics(state: RuntimeState) -> np.ndarray:
    """Read the legacy diagnostic channels used by the secondary scan."""
    s2p2_reference = state.pvs.sext_s2p2 or state.pvs.sext_s2p2k
    return np.array(
        [
            _get_float(state, state.pvs.sext_s1p1, 0.0),
            _get_float(state, state.pvs.sext_s2p1, 0.0),
            _get_float(state, s2p2_reference, 0.0),
            _get_float(state, state.pvs.sext_s3p1, 0.0),
            time.time(),
            _get_float(state, state.pvs.beam_energy, 0.0),
            _get_float(state, state.pvs.beam_current, 0.0),
            _get_float(state, state.pvs.qpd1_sigma_x, 0.0),
            _get_float(state, state.pvs.qpd1_sigma_y, 0.0),
            _get_float(state, state.pvs.qpd0_sigma_x, 0.0),
            _get_float(state, state.pvs.qpd0_sigma_y, 0.0),
            _get_float(state, state.pvs.tune_x, 0.0),
            _get_float(state, state.pvs.tune_y, 0.0),
            _get_float(state, state.pvs.tune_s, 0.0),
            _get_float(state, state.pvs.orbit_mode_readback, 0.0),
            _get_float(state, state.pvs.white_noise, 0.0),
        ],
        dtype=float,
    )


def generate_scan_table(
    state: RuntimeState,
    scan_ranges: Sequence[Tuple[float, float, int]],
    xi_ranges: Sequence[Tuple[float, float]],
    poly_matrix_path: Path,
    output_dir: Optional[Path] = None,
) -> Optional[np.ndarray]:
    """WRITE PATH: generate and optionally execute the legacy scan-table workflow.

    Porting notes:
    - the legacy code uses the minimum value for both endpoints of the S2P2 and
      S3 ranges, so those axes never scan
    - it also writes six output columns even though the machine state involves
      seven sextupole setpoints in the main workflow
    This port fixes both blockers and writes a seven-column candidate table.
    """
    try:
        matrix = np.asarray(np.loadtxt(poly_matrix_path), dtype=float)
    except Exception as exc:
        state.log("Could not load polynomial matrix %s: %s" % (poly_matrix_path, exc))
        return None

    baseline = [_get_float(state, name, 0.0) for name in state.pvs.sextupole_names()]
    try:
        candidates = _candidate_settings_from_poly_matrix(
            baseline_currents=baseline,
            scan_ranges=scan_ranges,
            xi_ranges=xi_ranges,
            matrix=matrix,
        )
    except Exception as exc:
        state.log("Could not generate scan candidates: %s" % exc)
        return None

    if len(candidates) == 0:
        state.log("No suitable sextupole settings found for the requested xi ranges.")
        return candidates

    output_dir = output_dir or _scan_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    np.savetxt(output_dir / "sext_setting.txt", candidates)
    state.log("Saved %d scan candidates to %s." % (len(candidates), output_dir / "sext_setting.txt"))
    state.record_event(
        "scan_table_candidates",
        output_dir=str(output_dir),
        candidate_count=int(len(candidates)),
        xi_ranges=xi_ranges,
        scan_ranges=scan_ranges,
    )

    if not state.can_write_machine:
        state.log("Scan-table execution needs write access; candidates only were saved.")
        return candidates

    original_currents = baseline[:]
    try:
        for row in candidates:
            if state.stop_requested:
                state.log("Stopped while executing the scan table.")
                break
            # WRITE PATH: step the machine to each candidate family setting.
            state.adapter.put(state.pvs.sext_s1p1, row[0])
            state.adapter.put(state.pvs.sext_s1p2, row[1])
            state.adapter.put(state.pvs.sext_s2p1, row[2])
            if state.pvs.sext_s2p2:
                state.adapter.put(state.pvs.sext_s2p2, row[3])
            if state.pvs.sext_s2p2k:
                state.adapter.put(state.pvs.sext_s2p2k, row[3])
            if state.pvs.sext_s2p2l:
                state.adapter.put(state.pvs.sext_s2p2l, row[4])
            state.adapter.put(state.pvs.sext_s3p1, row[5])
            state.adapter.put(state.pvs.sext_s3p2, row[6])

            samples = [_collect_scan_diagnostics(state)]
            for _ in range(10):
                time.sleep(0.5)
                samples.append(_collect_scan_diagnostics(state))

            file_name = (
                "%.2fs%.2fs%.2fs%.2fs.dat"
                % (
                    _get_float(state, state.pvs.sext_s1p1, 0.0),
                    _get_float(state, state.pvs.sext_s2p1, 0.0),
                    _get_float(state, state.pvs.sext_s2p2 or state.pvs.sext_s2p2k, 0.0),
                    _get_float(state, state.pvs.sext_s3p1, 0.0),
                )
            )
            np.savetxt(output_dir / file_name, np.asarray(samples, dtype=float))
    finally:
        for pv_name, value in zip(state.pvs.sextupole_names(), original_currents):
            if pv_name:
                state.adapter.put(pv_name, value)

    return candidates


def gen_scan_tab(state: RuntimeState, scan_ranges, xi_ranges, poly_matrix_path: Path, output_dir: Optional[Path] = None):
    """Legacy callback name kept for easier comparison with original/betagui.py."""
    return generate_scan_table(state, scan_ranges, xi_ranges, poly_matrix_path, output_dir)


def matrix_mode_for_shape(shape: Tuple[int, int]) -> Optional[int]:
    if shape == (2, 2):
        return 1
    if shape == (3, 3):
        return 3
    return None


def load_matrix_file(state: RuntimeState, path: Path) -> bool:
    """Load either legacy saved format or a raw square matrix."""
    if not path.exists():
        state.log("Matrix file not found: %s" % path)
        return False
    try:
        data = np.loadtxt(path)
    except Exception as exc:
        state.log("Could not load matrix file %s: %s" % (path, exc))
        return False
    if data.ndim != 2:
        state.log("Unsupported matrix format in %s" % path)
        return False

    if data.shape[0] == data.shape[1] + 1:
        mat_status = int(data[0, 0])
        bump_dim = data.shape[0] - 1
        matrix = np.asarray(data[1 : bump_dim + 1, :], dtype=float)
    elif data.shape[0] == data.shape[1]:
        matrix = np.asarray(data, dtype=float)
        mode = matrix_mode_for_shape(matrix.shape)
        if mode is None:
            state.log("Unsupported raw matrix shape in %s: %s" % (path, matrix.shape))
            return False
        mat_status = mode
        bump_dim = matrix.shape[0]
    else:
        state.log("Unsupported matrix shape in %s: %s" % (path, data.shape))
        return False

    state.B = matrix
    state.mat_status = mat_status
    state.bump_dim = bump_dim
    state.bump_option = mat_status
    state.log("Loaded matrix from %s with shape %s." % (path, matrix.shape))
    state.record_event(
        "matrix_loaded",
        path=str(path),
        shape=list(matrix.shape),
        mat_status=mat_status,
        bump_dim=bump_dim,
        matrix=matrix.tolist(),
    )
    return True


def save_matrix_file(state: RuntimeState, path: Path) -> bool:
    """Save matrix in the same tagged format as the legacy GUI."""
    buf_sign = {
        1: np.array([[1.0, 1.0]]),
        2: np.array([[2.0, 2.0]]),
        3: np.array([[3.0, 3.0, 3.0]]),
        4: np.array([[4.0, 4.0, 4.0]]),
    }
    if state.mat_status not in buf_sign:
        state.log("Unknown matrix status: %r" % (state.mat_status,))
        return False
    try:
        payload = np.vstack((buf_sign[state.mat_status], state.B))
        np.savetxt(path, payload)
    except Exception as exc:
        state.log("Could not save matrix to %s: %s" % (path, exc))
        return False
    state.log("Saved matrix to %s." % path)
    state.record_event(
        "matrix_saved",
        path=str(path),
        mat_status=state.mat_status,
        matrix=state.B.tolist(),
    )
    return True


def load_default_matrix(state: RuntimeState):
    """Load the embedded legacy matrix without depending on external files."""
    apply_embedded_default_matrix(state)


def _measurement_inputs_from_dict(values: Dict[str, str]) -> MeasurementInputs:
    return MeasurementInputs(
        n_tune_samples=int(values["ntimes"]),
        n_rf_points=int(values["Npoints"]),
        delta_x_min_mm=float(values["dfmin"]),
        delta_x_max_mm=float(values["dfmax"]),
        fit_order=int(values["fit_order"]),
        delay_after_rf_s=float(values["delay_set_rf"]),
        delay_between_tune_reads_s=float(values["delay_mea_Tunes"]),
    )


def _log_measurement_plan(state: RuntimeState, inputs: MeasurementInputs, alpha0_text: str):
    estimated_duration_s = inputs.n_rf_points * (
        inputs.delay_after_rf_s + max(inputs.n_tune_samples - 1, 0) * inputs.delay_between_tune_reads_s
    )
    state.log(
        "RF sweep plan: %d points, %d tune samples per point."
        % (inputs.n_rf_points, inputs.n_tune_samples)
    )
    state.log("Estimated sweep time: about %.1f s plus EPICS overhead." % estimated_duration_s)
    if alpha0_text == "dynamic":
        state.log("alpha0 source: dynamic from live PVs.")
    else:
        state.log("alpha0 source: fixed value %s." % alpha0_text)


def preview_rf_sweep(state: RuntimeState, entry_values: Dict[str, str]) -> Dict[str, object]:
    """Build a read-only preview of the RF sweep that MeaChrom would run."""
    inputs = _measurement_inputs_from_dict(entry_values)
    frf0_hz = float(state.adapter.get(state.pvs.rf_setpoint, 0.0) or 0.0)
    optics_mode = state.adapter.get(state.pvs.optics_mode, 0) if state.pvs.optics_mode else 0
    dmax = optics_mode_to_dmax(optics_mode)
    alpha0_text = entry_values.get("alpha0", "dynamic").strip()
    if alpha0_text and alpha0_text != "dynamic":
        alpha0 = float(alpha0_text)
        alpha0_source = "fixed"
    else:
        alpha0 = calculate_alpha0(state.adapter, state.pvs, harmonic_number=NHARMONIC)
        alpha0_source = "dynamic"
    rf_points_hz = build_rf_range(
        frf0_hz=frf0_hz,
        alpha0=alpha0,
        dmax=dmax,
        delta_x_min_mm=inputs.delta_x_min_mm,
        delta_x_max_mm=inputs.delta_x_max_mm,
        n_points=inputs.n_rf_points,
    )
    step_sizes_hz = np.diff(rf_points_hz) if len(rf_points_hz) > 1 else np.array([], dtype=float)
    return {
        "inputs": inputs,
        "alpha0": float(alpha0),
        "alpha0_source": alpha0_source,
        "frf0_hz": float(frf0_hz),
        "optics_mode": float(optics_mode or 0.0),
        "dmax": float(dmax),
        "rf_points_hz": np.asarray(rf_points_hz, dtype=float),
        "step_sizes_hz": np.asarray(step_sizes_hz, dtype=float),
    }


def MeaChrom(state: RuntimeState, entry_values: Dict[str, str]) -> Optional[List[float]]:
    """Legacy-style chromaticity measurement wrapper."""
    state.stop_requested = False
    measurement_name = state.next_measurement_name("chromaticity")
    start_snapshot = _machine_snapshot(state)
    state.log("Starting chromaticity measurement.")
    state.record_event(
        "chromaticity_measurement_started",
        measurement=measurement_name,
        entry_values=entry_values,
        start_snapshot=start_snapshot,
    )
    try:
        inputs = _measurement_inputs_from_dict(entry_values)
    except Exception as exc:
        state.log("Invalid measurement inputs: %s" % exc)
        state.record_event(
            "chromaticity_measurement_failed",
            measurement=measurement_name,
            error=str(exc),
            stage="parse_inputs",
        )
        return None

    if not state.can_write_machine:
        state.log("Chromaticity measurement needs write access.")
        state.record_event(
            "chromaticity_measurement_failed",
            measurement=measurement_name,
            error="write_access_required",
            stage="permission_check",
        )
        return None

    alpha0_text = entry_values.get("alpha0", "dynamic").strip()
    alpha0 = None
    if alpha0_text and alpha0_text != "dynamic":
        try:
            alpha0 = float(alpha0_text)
        except ValueError:
            state.log("Invalid alpha0 entry: %r" % alpha0_text)
            state.record_event(
                "chromaticity_measurement_failed",
                measurement=measurement_name,
                error="invalid_alpha0",
                alpha0_text=alpha0_text,
                stage="alpha0_parse",
            )
            return None
    _log_measurement_plan(state, inputs, alpha0_text)

    try:
        result = measure_chromaticity_with_feedback_control(
            adapter=state.adapter,
            pvs=state.pvs,
            inputs=inputs,
            alpha0=alpha0,
            harmonic_number=NHARMONIC,
            progress_logger=state.log,
        )
    except Exception as exc:
        state.log("Chromaticity measurement failed: %s" % exc)
        failure_payload = {
            "measurement": measurement_name,
            "error": str(exc),
            "entry_values": entry_values,
            "start_snapshot": start_snapshot,
        }
        payload_path = state.write_payload("measurements/%s_failed.json" % measurement_name, failure_payload)
        state.record_event(
            "chromaticity_measurement_failed",
            measurement=measurement_name,
            error=str(exc),
            payload_path=payload_path,
        )
        return None

    set_frf_slowly(state, state.frf0)
    state.log(
        "Measured chromaticity: xi_x=%.4f, xi_y=%.4f, xi_s=%.4f"
        % (result.xi[0], result.xi[1], result.xi[2])
    )
    state.last_result = result  # porting change: cache latest result for plotting
    payload = {
        "measurement": measurement_name,
        "entry_values": entry_values,
        "inputs": {
            "n_tune_samples": inputs.n_tune_samples,
            "n_rf_points": inputs.n_rf_points,
            "delta_x_min_mm": inputs.delta_x_min_mm,
            "delta_x_max_mm": inputs.delta_x_max_mm,
            "fit_order": inputs.fit_order,
            "delay_after_rf_s": inputs.delay_after_rf_s,
            "delay_between_tune_reads_s": inputs.delay_between_tune_reads_s,
        },
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
    }
    payload_path = state.write_payload("measurements/%s.json" % measurement_name, payload)
    state.record_event(
        "chromaticity_measurement_completed",
        measurement=measurement_name,
        xi=result.xi,
        alpha0=result.alpha0,
        payload_path=payload_path,
    )
    return result.xi


def measure_response_matrix(state: RuntimeState, entry_values: Dict[str, str]) -> Optional[np.ndarray]:
    """WRITE PATH: step sextupoles and measure the response matrix."""
    measurement_name = state.next_measurement_name("response_matrix")
    state.log("Starting response matrix measurement.")
    state.record_event(
        "response_matrix_started",
        measurement=measurement_name,
        entry_values=entry_values,
        bump_option=state.bump_option,
        start_snapshot=_machine_snapshot(state),
    )
    if not state.can_write_machine:
        state.log("Response matrix measurement needs write access.")
        state.record_event("response_matrix_failed", measurement=measurement_name, error="write_access_required")
        return None

    nsext_p2 = [
        [state.pvs.sext_s1p2],
        [state.pvs.sext_s2p2k, state.pvs.sext_s2p2l],
        [state.pvs.sext_s3p2],
    ]
    nsext_s = [
        [state.pvs.sext_s1p1, state.pvs.sext_s1p2],
        [state.pvs.sext_s2p1, state.pvs.sext_s2p2k, state.pvs.sext_s2p2l],
        [state.pvs.sext_s3p1, state.pvs.sext_s3p2],
    ]
    bump_dim = 2 if state.bump_option in (1, 2) else 3
    nsext = nsext_s if state.bump_option in (1, 3) else nsext_p2
    a_matrix = np.zeros((bump_dim, bump_dim))

    for index in range(bump_dim):
        if state.stop_requested:
            state.log("Matrix measurement stopped.")
            state.record_event("response_matrix_stopped", measurement=measurement_name, axis=index)
            return None
        state.log("Measuring matrix axis %d/%d." % (index + 1, bump_dim))
        group = nsext[index]
        for pv_name in group:
            state.adapter.put(pv_name, _get_float(state, pv_name) - 1.0)
        xi_1 = MeaChrom(state, entry_values)
        for pv_name in group:
            state.adapter.put(pv_name, _get_float(state, pv_name) + 1.0)
        xi_2 = MeaChrom(state, entry_values)
        if xi_1 is None or xi_2 is None:
            state.log("Matrix measurement aborted during axis %d." % index)
            state.record_event("response_matrix_failed", measurement=measurement_name, axis=index, error="chromaticity_measurement_failed")
            return None
        a_matrix[index, :] = (np.asarray(xi_2) - np.asarray(xi_1))[0:bump_dim]
        state.record_event(
            "response_matrix_axis",
            measurement=measurement_name,
            axis=index,
            xi_minus=xi_1,
            xi_plus=xi_2,
            row=a_matrix[index, :].tolist(),
        )

    try:
        state.B = np.linalg.inv(a_matrix.T)
    except np.linalg.LinAlgError as exc:
        state.log("Response matrix inversion failed: %s" % exc)
        state.record_event("response_matrix_failed", measurement=measurement_name, error=str(exc), stage="invert")
        return None
    state.bump_dim = bump_dim
    state.mat_status = state.bump_option
    state.log("Measured response matrix with shape %s." % (state.B.shape,))
    payload_path = state.write_payload(
        "measurements/%s.json" % measurement_name,
        {
            "measurement": measurement_name,
            "bump_option": state.bump_option,
            "a_matrix": a_matrix.tolist(),
            "inverse_matrix": state.B.tolist(),
            "end_snapshot": _machine_snapshot(state),
        },
    )
    state.record_event(
        "response_matrix_completed",
        measurement=measurement_name,
        matrix=state.B.tolist(),
        payload_path=payload_path,
    )
    return state.B


def start_bump(state: RuntimeState, entry_values: Dict[str, str]) -> Optional[np.ndarray]:
    """Legacy callback name kept for easier comparison with original/betagui.py."""
    return measure_response_matrix(state, entry_values)


class mainwindow(tk.Frame if TK_AVAILABLE else object):
    """Tkinter GUI for the ported tool."""

    def __init__(self, master, state: RuntimeState):
        if not TK_AVAILABLE:  # pragma: no cover - depends on host packages
            raise RuntimeError("tkinter is not available.")
        super().__init__(master)
        self.master = master
        self.state = state
        self.last_result: Optional[MeasurementResult] = None
        self.grid(sticky="nsew")
        self.entry_vars: Dict[str, tk.StringVar] = {}
        self.matrix_cells: List[List[tk.Text]] = []
        self.cor_step_vars: List[tk.StringVar] = []
        self.cor_readouts: List[tk.Text] = []
        self.correction_buttons: List[tk.Button] = []
        self.status_text = None
        self.fig = None
        self.ax_orbit = None
        self.ax_x = None
        self.ax_y = None
        self.ax_s = None
        self.canvas = None
        self.dev_window = None
        self._last_result_marker = None
        self._build_widgets()
        self._refresh_matrix_display()
        self._refresh_mode_state()
        self._drain_log()

    def _build_widgets(self):
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        left = tk.Frame(self)
        left.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=8, pady=8)
        center = tk.Frame(self)
        center.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        status = tk.Frame(self)
        status.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        plot = tk.Frame(self)
        plot.grid(row=2, column=1, sticky="nsew", padx=8, pady=(0, 8))
        plot.rowconfigure(0, weight=1)
        plot.columnconfigure(0, weight=1)

        self._build_input_panel(left)
        self._build_matrix_panel(center)
        self._build_status_panel(status)
        self._build_plot_panel(plot)

    def _build_input_panel(self, parent):
        tk.Label(parent, text="Inputs", font=LARGE_FONT).grid(row=0, column=0, columnspan=2, sticky="ew")
        default_alpha0 = "dynamic"
        labels = [
            ("ntimes", "N of Q measurements", "7"),
            ("Npoints", "Ndfrf", "11"),
            ("dfmin", "dfrfmin w.r.t Xdisp /mm", "-2"),
            ("dfmax", "dfrfmax w.r.t Xdisp /mm", "2"),
            ("fit_order", "fit ordr", "1"),
            ("delay_set_rf", "delay after setting rf /s", "5"),
            ("delay_mea_Tunes", "t between Q measurements /s", "1"),
            ("alpha0", "alpha0", default_alpha0),
        ]
        for row, (key, label, value) in enumerate(labels, start=1):
            tk.Label(parent, text=label, anchor="w").grid(row=row, column=0, sticky="ew", pady=1)
            var = tk.StringVar(value=value)
            self.entry_vars[key] = var
            tk.Entry(parent, textvariable=var, justify="center", width=12).grid(row=row, column=1, sticky="ew", pady=1)

        self.measure_button = tk.Button(parent, text="Measure the chromaticity", command=self._on_measure)
        self.measure_button.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        self.alpha_button = tk.Button(parent, text="Measure alpha0", command=self._on_alpha)
        self.alpha_button.grid(row=10, column=0, columnspan=2, sticky="ew", pady=2)
        self.preview_button = tk.Button(parent, text="Preview RF sweep", command=self._on_preview_measure)
        self.preview_button.grid(row=11, column=0, columnspan=2, sticky="ew", pady=2)
        self.matrix_button = tk.Button(parent, text="Measure matrix", command=self._on_measure_matrix)
        self.matrix_button.grid(row=12, column=0, columnspan=2, sticky="ew", pady=2)
        self.reset_button = tk.Button(parent, text="reset", command=self._on_reset)
        self.reset_button.grid(row=13, column=0, columnspan=2, sticky="ew", pady=2)
        self.save_state_button = tk.Button(parent, text="Save current setting", command=self._on_save_setting)
        self.save_state_button.grid(row=14, column=0, columnspan=2, sticky="ew", pady=2)
        self.stop_button = tk.Button(parent, text="Stop", command=self._on_stop)
        self.stop_button.grid(row=15, column=0, columnspan=2, sticky="ew", pady=2)
        self.scan_button = tk.Button(parent, text="sext scan", command=self._on_open_scan_window)
        self.scan_button.grid(row=16, column=0, columnspan=2, sticky="ew", pady=2)
        self.dev_button = tk.Button(parent, text="dev / PV window", command=self._on_open_dev_window)
        self.dev_button.grid(row=17, column=0, columnspan=2, sticky="ew", pady=2)

    def _build_matrix_panel(self, parent):
        top = tk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew")
        tk.Button(top, text="Load matrix", command=self._on_load_matrix).grid(row=0, column=0, sticky="ew", padx=2)
        tk.Button(top, text="Save matrix", command=self._on_save_matrix).grid(row=0, column=1, sticky="ew", padx=2)

        mode_frame = tk.LabelFrame(parent, text="Bump mode")
        mode_frame.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.bump_var = tk.IntVar(value=self.state.bump_option)
        for row, (text, value) in enumerate((("2D", 1), ("2D(P2)", 2), ("3D", 3), ("3D(P2)", 4))):
            tk.Radiobutton(mode_frame, text=text, value=value, variable=self.bump_var, command=self._on_bump_mode).grid(row=row, column=0, sticky="w")

        matrix_frame = tk.LabelFrame(parent, text="response matrix")
        matrix_frame.grid(row=2, column=0, sticky="ew")
        self.matrix_cells = []
        for row in range(3):
            row_cells = []
            for col in range(3):
                widget = tk.Text(matrix_frame, height=1, width=10)
                widget.grid(row=row, column=col, padx=2, pady=2)
                row_cells.append(widget)
            self.matrix_cells.append(row_cells)

        correction_frame = tk.LabelFrame(parent, text="dξ readout / correction")
        correction_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        labels = ("xi_x", "xi_y", "xi_s")
        self.cor_step_vars = []
        self.cor_readouts = []
        for row, axis_name in enumerate(labels):
            tk.Label(correction_frame, text=axis_name).grid(row=row, column=0, padx=2)
            step_var = tk.StringVar(value="0.0")
            self.cor_step_vars.append(step_var)
            tk.Entry(correction_frame, textvariable=step_var, width=8, justify="center").grid(row=row, column=1, padx=2)
            minus_button = tk.Button(correction_frame, text="-", command=lambda idx=row: self._on_change_sext(idx, -1))
            minus_button.grid(row=row, column=2, padx=2)
            self.correction_buttons.append(minus_button)
            plus_button = tk.Button(correction_frame, text="+", command=lambda idx=row: self._on_change_sext(idx, 1))
            plus_button.grid(row=row, column=3, padx=2)
            self.correction_buttons.append(plus_button)
            readout = tk.Text(correction_frame, height=1, width=8)
            readout.grid(row=row, column=4, padx=2)
            readout.insert("1.0", "0.0")
            self.cor_readouts.append(readout)

    def _build_status_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.status_text = tk.Text(parent, height=8, width=90, wrap="word")
        scrollbar = tk.Scrollbar(parent, command=self.status_text.yview)
        self.status_text.configure(yscrollcommand=scrollbar.set)
        self.status_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_plot_panel(self, parent):
        if MATPLOTLIB_AVAILABLE:
            self.fig = Figure(figsize=(8, 5))
            self.ax_orbit = self.fig.add_subplot(211)
            self.ax_x = self.fig.add_subplot(234)
            self.ax_y = self.fig.add_subplot(235)
            self.ax_s = self.fig.add_subplot(236)
            self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
            self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        else:
            tk.Label(
                parent,
                text="matplotlib is unavailable; plots are disabled in this session.",
            ).grid(row=0, column=0, sticky="w")

    def _entry_values(self) -> Dict[str, str]:
        return {key: var.get() for key, var in self.entry_vars.items()}

    def _set_status_text(self):
        if self.status_text is None:
            return
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert(tk.END, "\n".join(self.state.messages[-200:]))
        self.status_text.see(tk.END)

    def _drain_log(self):
        self._set_status_text()
        self._refresh_matrix_display()
        if (
            self.dev_window is not None
            and getattr(self.dev_window, "window", None) is not None
            and self.dev_window.window.winfo_exists()
        ):
            self.dev_window.refresh()
        result = getattr(self.state, "last_result", None)
        marker = id(result) if result is not None else None
        if marker != self._last_result_marker:
            self._last_result_marker = marker
            self._update_plot(result)
            if result is not None:
                for widget, value in zip(self.cor_readouts, result.xi):
                    widget.delete("1.0", tk.END)
                    widget.insert("1.0", "%5.4f" % value)
        self.after(500, self._drain_log)

    def _refresh_mode_state(self):
        if self.state.can_write_machine:
            return
        self.measure_button.config(state="disabled")
        self.matrix_button.config(state="disabled")
        self.reset_button.config(state="disabled")
        for button in self.correction_buttons:
            button.config(state="disabled")

    def _refresh_matrix_display(self):
        for row in range(3):
            for col in range(3):
                widget = self.matrix_cells[row][col]
                widget.delete("1.0", tk.END)
                if row < self.state.B.shape[0] and col < self.state.B.shape[1]:
                    widget.insert("1.0", "%5.3f" % self.state.B[row, col])
                else:
                    widget.insert("1.0", " ")

    def _update_plot(self, result: Optional[MeasurementResult]):
        if result is None or self.fig is None:
            return
        positions, bpms = BPDM()
        self.ax_orbit.clear()
        self.ax_orbit.plot(positions, bpms, "r-")
        self.ax_orbit.set_title("Orbit readback along the ring")
        self.ax_orbit.set_xlabel("BPM position [m]")
        self.ax_orbit.set_ylabel("Orbit displacement [arb.]")
        plots = (
            (self.ax_x, result.delta_hz, result.tune_x_khz, result.fit_x, "Horizontal tune vs RF", "Tune X frequency [kHz]"),
            (self.ax_y, result.delta_hz, result.tune_y_khz, result.fit_y, "Vertical tune vs RF", "Tune Y frequency [kHz]"),
            (self.ax_s, result.delta_hz, result.tune_s_khz, result.fit_s, "Longitudinal tune vs RF", "Synchrotron frequency [kHz]"),
        )
        for axis, delta_hz, tune_values, fit_poly, title, y_label in plots:
            axis.clear()
            axis.plot(delta_hz, tune_values, "ro")
            axis.plot(delta_hz, fit_poly(delta_hz), "b-")
            axis.set_title(title)
            axis.set_xlabel("RF offset [PV units]")
            axis.set_ylabel(y_label)
        self.fig.tight_layout()
        self.canvas.draw()

    def _run_background(self, func, *args):
        def runner():
            try:
                func(*args)
            except Exception as exc:  # pragma: no cover - last-resort GUI guard
                self.state.log("Unhandled background error: %s" % exc)

        worker = threading.Thread(target=runner, daemon=True)
        worker.start()

    def _show_info_dialog(self, title: str, lines: Sequence[str]):
        if messagebox is None:
            self.state.log("%s\n%s" % (title, "\n".join(lines)))
            return
        messagebox.showinfo(title, "\n".join(lines), parent=self.master)

    def _confirm_live_write(self, title: str, lines: Sequence[str]) -> bool:
        if not self.state.can_write_machine:
            return True
        if messagebox is None:
            self.state.log("Write confirmation dialog unavailable for %s." % title)
            return False
        return bool(messagebox.askokcancel(title, "\n".join(lines), parent=self.master))

    def _measurement_preview_lines(self, preview: Dict[str, object]) -> List[str]:
        rf_points_hz = preview["rf_points_hz"]
        step_sizes_hz = preview["step_sizes_hz"]
        step_min = float(np.min(step_sizes_hz)) if len(step_sizes_hz) else 0.0
        step_max = float(np.max(step_sizes_hz)) if len(step_sizes_hz) else 0.0
        alpha0 = float(preview["alpha0"])
        source = preview["alpha0_source"]
        lines = [
            "Current RF PV value: %.6f" % float(preview["frf0_hz"]),
            "alpha0: %.8f (%s)" % (alpha0, source),
            "Optics mode: %s" % preview["optics_mode"],
            "dmax: %.6f m" % float(preview["dmax"]),
            "RF sweep points: %d" % len(rf_points_hz),
            "RF min PV value: %.6f" % float(rf_points_hz[0]),
            "RF max PV value: %.6f" % float(rf_points_hz[-1]),
            "RF step PV value: %.6f .. %.6f" % (step_min, step_max),
            "",
            "This action will write:",
            "- feedback X/Y/S -> 0",
            "- orbit correction mode -> 0",
            "- RF setpoint sweep over the points above",
            "- RF restore to saved RF after measurement",
            "- feedback/orbit restore after measurement",
        ]
        if len(rf_points_hz) <= 12:
            lines.append("")
            lines.append("RF points [PV units]:")
            lines.extend(["- %.6f" % float(value) for value in rf_points_hz])
        return lines

    def _preview_measurement(self) -> Optional[Dict[str, object]]:
        try:
            preview = preview_rf_sweep(self.state, self._entry_values())
        except Exception as exc:
            self.state.log("Could not preview RF sweep: %s" % exc)
            return None
        return preview

    def _on_measure(self):
        preview = self._preview_measurement()
        if preview is None:
            return
        lines = self._measurement_preview_lines(preview)
        if not self._confirm_live_write("Confirm chromaticity measurement", lines):
            self.state.log("Chromaticity measurement cancelled by user.")
            return
        self._run_background(MeaChrom, self.state, self._entry_values())

    def _on_alpha(self):
        def worker():
            self.state.log("Starting alpha0 calculation.")
            alpha0 = cal_alpha0(self.state)
            if alpha0 is not None:
                self.after(0, lambda: self.entry_vars["alpha0"].set(str(alpha0)))

        self._run_background(worker)

    def _on_preview_measure(self):
        preview = self._preview_measurement()
        if preview is None:
            return
        self._show_info_dialog("RF sweep preview", self._measurement_preview_lines(preview))

    def _on_measure_matrix(self):
        lines = [
            "This action will step sextupole currents and run repeated chromaticity measurements.",
            "It will therefore write sextupole setpoints, feedback/orbit disable commands, and RF sweep commands.",
            "Use conservative settings first and keep a saved baseline snapshot.",
        ]
        if not self._confirm_live_write("Confirm response matrix measurement", lines):
            self.state.log("Response matrix measurement cancelled by user.")
            return
        self._run_background(start_bump, self.state, self._entry_values())

    def _on_reset(self):
        if not self._confirm_live_write(
            "Confirm reset",
            [
                "This action will restore saved RF, sextupoles, feedback, orbit mode, and phase modulation settings.",
            ],
        ):
            self.state.log("Reset cancelled by user.")
            return
        def worker():
            if set_all2ini(self.state):
                self.after(0, self._reset_readouts)

        self._run_background(worker)

    def _on_save_setting(self):
        self._run_background(save_setting, self.state)

    def _on_stop(self):
        self.state.stop_requested = True
        self.state.log("Stop requested.")

    def _on_open_scan_window(self):
        SecondaryScanWindow(self.master, self.state, self._entry_values)

    def _on_open_dev_window(self):
        if (
            self.dev_window is not None
            and getattr(self.dev_window, "window", None) is not None
            and self.dev_window.window.winfo_exists()
        ):
            self.dev_window.window.lift()
            self.dev_window.window.focus_set()
            self.dev_window.refresh(force=True)
            return
        self.dev_window = DevToolsWindow(self.master, self.state)
        self.dev_window.refresh(force=True)

    def _on_load_matrix(self):
        if filedialog is None:
            self.state.log("File dialogs are unavailable in this session.")
            return
        filename = filedialog.askopenfilename(defaultextension=".txt")
        if not filename:
            return
        if load_matrix_file(self.state, Path(filename)):
            self._refresh_matrix_display()

    def _on_save_matrix(self):
        if filedialog is None:
            self.state.log("File dialogs are unavailable in this session.")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".txt")
        if not filename:
            return
        save_matrix_file(self.state, Path(filename))

    def _on_bump_mode(self):
        self.state.bump_option = int(self.bump_var.get())
        self.state.log("Selected bump option %d." % self.state.bump_option)

    def _on_change_sext(self, axis_index: int, sign: int):
        steps = [0.0, 0.0, 0.0]
        try:
            steps[axis_index] = sign * float(self.cor_step_vars[axis_index].get())
        except ValueError as exc:
            self.state.log("Invalid correction step: %s" % exc)
            return
        if steps[axis_index] == 0.0:
            self.state.log("Correction step is zero; no sextupole change was applied.")
            return
        if not self._confirm_live_write(
            "Confirm sextupole correction",
            [
                "This action will change sextupole set currents through the response matrix.",
                "Requested dXi step: %r" % steps,
            ],
        ):
            self.state.log("Sextupole correction cancelled by user.")
            return
        set_all_sexts(self.state, steps)
        widget = self.cor_readouts[axis_index]
        try:
            current = float(widget.get("1.0", tk.END).strip() or "0.0")
        except ValueError:
            current = 0.0
        widget.delete("1.0", tk.END)
        widget.insert("1.0", "%5.4f" % (current + steps[axis_index]))

    def _reset_readouts(self):
        for widget in self.cor_readouts:
            widget.delete("1.0", tk.END)
            widget.insert("1.0", "0.0")


class SecondaryScanWindow:
    """Secondary sextupole scan window, kept close to the legacy layout."""

    def __init__(self, master, state: RuntimeState, entry_values_callback):
        self.state = state
        self.entry_values_callback = entry_values_callback
        self.window = tk.Toplevel(master)
        self.window.title("Legacy sextupole scan")
        self.poly_vars: List[List[tk.StringVar]] = []
        self.scan_vars: List[List[tk.StringVar]] = []
        self.xi_vars: List[List[tk.StringVar]] = []
        self._build()

    def _build(self):
        top = tk.Frame(self.window, bg="#B6AFA9")
        top.grid(row=0, column=0, sticky="ew")
        tk.Button(top, text="Stop", width=10, command=self._on_stop).grid(row=0, column=0, padx=5, pady=5)
        tk.Button(top, text="Close window", command=self.window.destroy).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        poly = tk.Frame(self.window, bg="#A2B5CD")
        poly.grid(row=1, column=0, sticky="nsew")
        tk.Label(poly, text="Poly Matrix").grid(row=1, column=1, padx=5, pady=5)

        poly_defaults = [[-2, 2], [-4, 0], [-2, 2], [-2, 2]]
        family_labels = ["S1", "S2P1", "S2P2", "S3"]
        col_labels = ["dImin /A", "dImax /A"]
        for row_index, family_name in enumerate(family_labels):
            tk.Label(poly, text=family_name, width=6).grid(row=row_index + 2, column=0, padx=5, pady=5)
            row_vars = []
            for col_index in range(2):
                if row_index == 0:
                    tk.Label(poly, text=col_labels[col_index], width=8).grid(row=1, column=col_index + 1, padx=5, pady=5)
                var = tk.StringVar(value=str(poly_defaults[row_index][col_index]))
                tk.Entry(poly, textvariable=var, justify="center", width=8).grid(
                    row=row_index + 2, column=col_index + 1, padx=5, pady=5, sticky="ew"
                )
                row_vars.append(var)
            self.poly_vars.append(row_vars)
        tk.Button(poly, text="Measure", command=self._on_measure_poly).grid(
            row=3, column=3, columnspan=2, rowspan=2, padx=20, pady=5, sticky="ew"
        )

        scan = tk.Frame(self.window, bg="#A4DCD1")
        scan.grid(row=2, column=0, sticky="nsew")
        tk.Label(scan, text="scan setupoles").grid(row=0, column=3, padx=5, pady=5)

        scan_defaults = [[-2, 2, 5], [-4, 0, 5], [-2, 2, 5], [-2, 2, 5]]
        scan_col_labels = ["dImin /A", "dImax /A", "N"]
        for row_index, family_name in enumerate(family_labels):
            tk.Label(scan, text=family_name, width=10).grid(row=row_index + 4, column=0, padx=5, pady=5)
            row_vars = []
            for col_index in range(3):
                if row_index == 0:
                    tk.Label(scan, text=scan_col_labels[col_index], width=8).grid(
                        row=3, column=col_index + 2, padx=5, pady=5
                    )
                var = tk.StringVar(value=str(scan_defaults[row_index][col_index]))
                tk.Entry(scan, textvariable=var, justify="center", width=8).grid(
                    row=row_index + 4, column=col_index + 2, padx=5, pady=5, sticky="ew"
                )
                row_vars.append(var)
            self.scan_vars.append(row_vars)

        tk.Label(scan, text="dXi x range", width=10).grid(row=1, column=0, padx=5, pady=5)
        tk.Label(scan, text="dXi y range", width=10).grid(row=2, column=0, padx=5, pady=5)
        xi_defaults = [["-2", "2"], ["-2", "2"]]
        for row_index in range(2):
            row_vars = []
            for col_index in range(2):
                var = tk.StringVar(value=xi_defaults[row_index][col_index])
                tk.Entry(scan, textvariable=var, justify="center", width=8).grid(
                    row=row_index + 1, column=col_index + 2, padx=5, pady=5, sticky="ew"
                )
                row_vars.append(var)
            self.xi_vars.append(row_vars)

        tk.Button(scan, text="Scan", width=5, command=self._on_generate_scan).grid(
            row=1, column=4, columnspan=1, padx=5, pady=5, sticky="ew"
        )

    def _poly_ranges(self) -> List[Tuple[float, float]]:
        ranges = []
        for row_vars in self.poly_vars:
            ranges.append((float(row_vars[0].get()), float(row_vars[1].get())))
        return ranges

    def _scan_ranges(self) -> List[Tuple[float, float, int]]:
        ranges = []
        for row_vars in self.scan_vars:
            ranges.append((float(row_vars[0].get()), float(row_vars[1].get()), int(row_vars[2].get())))
        return ranges

    def _xi_ranges(self) -> List[Tuple[float, float]]:
        return [
            (float(self.xi_vars[0][0].get()), float(self.xi_vars[0][1].get())),
            (float(self.xi_vars[1][0].get()), float(self.xi_vars[1][1].get())),
        ]

    def _on_stop(self):
        self.state.stop_requested = True
        self.state.log("Stop requested.")

    def _on_measure_poly(self):
        if filedialog is None:
            self.state.log("File dialogs are unavailable in this session.")
            return
        directory = filedialog.askdirectory(title="choose a directory for the fine bump data")
        if not directory:
            return
        worker = threading.Thread(
            target=start_poly,
            args=(self.state, self.entry_values_callback(), self._poly_ranges(), Path(directory)),
            daemon=True,
        )
        worker.start()

    def _on_generate_scan(self):
        if filedialog is None:
            self.state.log("File dialogs are unavailable in this session.")
            return
        file_name = filedialog.askopenfilename(title="choose the fine bump data")
        if not file_name:
            return
        worker = threading.Thread(
            target=gen_scan_tab,
            args=(self.state, self._scan_ranges(), self._xi_ranges(), Path(file_name)),
            daemon=True,
        )
        worker.start()


class DevToolsWindow:
    """Optional test window for live PV readback and small RF command checks."""

    def __init__(self, master, state: RuntimeState):
        self.master = master
        self.state = state
        self.window = tk.Toplevel(master)
        self.window.title("betagui dev / PV window")
        self.window.geometry("760x560")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.last_refresh_ts = 0.0
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.rf_delta_var = tk.StringVar(value="10.0")
        self.rf_status_var = tk.StringVar(value="RF test idle.")
        self.current_rf_var = tk.StringVar(value="RF: ?")
        self._after_id = None
        self._build()

    def _build(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        controls = tk.LabelFrame(self.window, text="RF test")
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        tk.Label(controls, textvariable=self.current_rf_var).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        tk.Label(controls, text="delta Hz").grid(row=0, column=1, padx=4, pady=4)
        tk.Entry(controls, textvariable=self.rf_delta_var, width=10, justify="center").grid(row=0, column=2, padx=4, pady=4)
        tk.Button(controls, text="Refresh RF", command=self._refresh_rf_status).grid(row=0, column=3, padx=4, pady=4)
        tk.Button(controls, text="Shift RF +delta", command=lambda: self._shift_rf(+1.0)).grid(row=0, column=4, padx=4, pady=4)
        tk.Button(controls, text="Shift RF -delta", command=lambda: self._shift_rf(-1.0)).grid(row=0, column=5, padx=4, pady=4)
        tk.Button(controls, text="Restore saved RF", command=self._restore_saved_rf).grid(row=0, column=6, padx=4, pady=4)
        tk.Checkbutton(
            controls,
            text="auto refresh",
            variable=self.auto_refresh_var,
            command=self._toggle_auto_refresh,
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="w")
        tk.Button(controls, text="Refresh now", command=lambda: self.refresh(force=True)).grid(row=1, column=2, padx=4, pady=(0, 4))
        tk.Label(controls, textvariable=self.rf_status_var, anchor="w").grid(row=1, column=3, columnspan=4, padx=4, pady=(0, 4), sticky="ew")

        pv_frame = tk.LabelFrame(self.window, text="live PV readback")
        pv_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        pv_frame.columnconfigure(0, weight=1)
        pv_frame.rowconfigure(0, weight=1)
        self.pv_readout_text = tk.Text(pv_frame, height=28, width=90, wrap="none")
        pv_scroll_y = tk.Scrollbar(pv_frame, command=self.pv_readout_text.yview)
        pv_scroll_x = tk.Scrollbar(pv_frame, command=self.pv_readout_text.xview, orient="horizontal")
        self.pv_readout_text.configure(yscrollcommand=pv_scroll_y.set, xscrollcommand=pv_scroll_x.set)
        self.pv_readout_text.grid(row=0, column=0, sticky="nsew")
        pv_scroll_y.grid(row=0, column=1, sticky="ns")
        pv_scroll_x.grid(row=1, column=0, sticky="ew")

    def _toggle_auto_refresh(self):
        if self.auto_refresh_var.get():
            self._schedule_refresh()
        else:
            self._cancel_refresh()

    def _schedule_refresh(self):
        self._cancel_refresh()
        if self.window.winfo_exists() and self.auto_refresh_var.get():
            self._after_id = self.window.after(1000, self._auto_refresh_tick)

    def _cancel_refresh(self):
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _auto_refresh_tick(self):
        self._after_id = None
        self.refresh(force=True)
        self._schedule_refresh()

    def _refresh_rf_status(self):
        current_rf = _get_float(self.state, self.state.pvs.rf_setpoint, 0.0)
        self.current_rf_var.set("RF PV value: %.6f" % current_rf)
        self.rf_status_var.set("RF readback refreshed.")

    def _shift_rf(self, sign: float):
        try:
            delta_hz = sign * float(self.rf_delta_var.get())
        except ValueError as exc:
            self.state.log("Invalid RF delta: %s" % exc)
            self.rf_status_var.set("Invalid RF delta.")
            return
        current_rf = _get_float(self.state, self.state.pvs.rf_setpoint, 0.0)
        target_rf = current_rf + delta_hz
        if self.state.can_write_machine and messagebox is not None:
            confirmed = messagebox.askokcancel(
                "Confirm RF test shift",
                "\n".join(
                    [
                        "Current RF PV value: %.6f" % current_rf,
                        "Delta RF PV value: %.6f" % delta_hz,
                        "Target RF PV value: %.6f" % target_rf,
                    ]
                ),
                parent=self.window,
            )
            if not confirmed:
                self.state.log("Developer RF test cancelled by user.")
                self.rf_status_var.set("RF shift cancelled.")
                return
        self.state.log("Developer RF test: %.6f -> %.6f Hz" % (current_rf, target_rf))
        self.state.record_event(
            "developer_rf_shift",
            current_rf_hz=current_rf,
            delta_hz=delta_hz,
            target_rf_hz=target_rf,
            safe_mode=not self.state.can_write_machine,
        )
        set_frf_slowly(self.state, target_rf, n_steps=1, delay_s=0.0)
        self._refresh_rf_status()
        self.refresh(force=True)

    def _restore_saved_rf(self):
        if not self.state.saved_settings_valid:
            self.state.log("Developer RF restore skipped: no valid saved RF.")
            self.rf_status_var.set("No valid saved RF.")
            return
        if self.state.can_write_machine and messagebox is not None:
            confirmed = messagebox.askokcancel(
                "Confirm RF restore",
                "Restore RF to PV value %.6f?" % self.state.frf0,
                parent=self.window,
            )
            if not confirmed:
                self.state.log("Developer RF restore cancelled by user.")
                self.rf_status_var.set("RF restore cancelled.")
                return
        self.state.log("Developer RF restore to %.6f Hz" % self.state.frf0)
        self.state.record_event(
            "developer_rf_restore",
            target_rf_hz=self.state.frf0,
            safe_mode=not self.state.can_write_machine,
        )
        set_frf_slowly(self.state, self.state.frf0, n_steps=1, delay_s=0.0)
        self._refresh_rf_status()
        self.refresh(force=True)

    def refresh(self, force: bool = False):
        if not self.window.winfo_exists():
            return
        now = time.time()
        if not force and now - self.last_refresh_ts < 1.0:
            return
        self.last_refresh_ts = now
        snapshot = _machine_snapshot(self.state)
        lines = [
            "rf_setpoint_hz      %r" % snapshot["rf_hz"],
            "tune_x_raw          %r" % snapshot["tune_x_raw"],
            "tune_x_khz          %r" % snapshot["tune_x_khz"],
            "tune_x              %.6f" % float(snapshot["tune_x_unitless"]),
            "tune_y_raw          %r" % snapshot["tune_y_raw"],
            "tune_y_khz          %r" % snapshot["tune_y_khz"],
            "tune_y              %.6f" % float(snapshot["tune_y_unitless"]),
            "tune_s_raw          %r" % snapshot["tune_s_raw"],
            "tune_s_khz          %r" % snapshot["tune_s_khz"],
            "tune_s              %.6f" % float(snapshot["tune_s_unitless"]),
            "optics_mode         %r" % snapshot["optics_mode"],
            "orbit_mode_rb       %r" % snapshot["orbit_mode_readback"],
            "feedback_x          %r" % snapshot["feedback_x"],
            "feedback_y          %r" % snapshot["feedback_y"],
            "feedback_s          %r" % snapshot["feedback_s"],
            "cavity_voltage_kv   %r" % snapshot["cavity_voltage_kv"],
            "beam_energy_mev     %r" % snapshot["beam_energy_mev"],
            "beam_current        %r" % snapshot["beam_current"],
            "lifetime_10h        %r" % snapshot["lifetime_10h"],
            "lifetime_100h       %r" % snapshot["lifetime_100h"],
            "calc_lifetime       %r" % snapshot["calculated_lifetime"],
            "qpd1_sigma_x        %r" % snapshot["qpd1_sigma_x"],
            "qpd1_sigma_y        %r" % snapshot["qpd1_sigma_y"],
            "qpd0_sigma_x        %r" % snapshot["qpd0_sigma_x"],
            "qpd0_sigma_y        %r" % snapshot["qpd0_sigma_y"],
            "dose_rate           %r" % snapshot["dose_rate"],
            "white_noise         %r" % snapshot["white_noise"],
            "",
            "sextupoles:",
        ]
        for label, value in sorted(snapshot["sextupoles"].items()):
            lines.append("  %-16s %r" % (label, value))
        self.pv_readout_text.delete("1.0", tk.END)
        self.pv_readout_text.insert("1.0", "\n".join(lines))
        self.current_rf_var.set("RF PV value: %.6f" % float(snapshot["rf_hz"]))

    def _on_close(self):
        self._cancel_refresh()
        self.window.destroy()


def launch_gui(state: RuntimeState, window_title: str = "Chromaticity tool pos alpha@MLS (Python 3 port)") -> int:
    if not TK_AVAILABLE:
        state.log("tkinter is unavailable; GUI cannot start.")
        return 1

    try:
        root = tk.Tk()
    except Exception as exc:  # pragma: no cover - depends on display environment
        state.log("Could not start Tk root window: %s" % exc)
        return 1

    previous_sigint = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum, frame):
        state.log("Interrupt received; closing GUI.")
        try:
            root.after(0, root.destroy)
        except Exception:
            pass

    def keep_signal_pump_alive():
        if root.winfo_exists():
            root.after(200, keep_signal_pump_alive)

    signal.signal(signal.SIGINT, handle_sigint)
    root.title(window_title)
    mainwindow(root, state)
    root.after(200, keep_signal_pump_alive)
    try:
        root.mainloop()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
    return 0


EMBEDDED_DEFAULT_MATRIX_3D = [[0.24684105483769192, 1.1897771955134735, -44.1644998707413], [0.9817088245196021, 2.429842058611793, -21.565740268504335], [-1.796015552664779, -0.023487736658141446, -24.225114231922447]]
EMBEDDED_DEFAULT_MATRIX_2D = [[3.5300306881590235, 1.4739499128541276], [2.7340959004637297, 2.8729317626729616]]


def apply_embedded_default_matrix(state):
    """Load the bundled legacy response matrix into the runtime state."""
    if int(getattr(state, "bump_option", 3)) in (1, 2):
        state.B = np.asarray(EMBEDDED_DEFAULT_MATRIX_2D, dtype=float)
        state.mat_status = 1
        state.bump_dim = 2
        state.bump_option = 1
    else:
        state.B = np.asarray(EMBEDDED_DEFAULT_MATRIX_3D, dtype=float)
        state.mat_status = 3
        state.bump_dim = 3
        state.bump_option = 3
    state.log("Loaded embedded default matrix with shape %s." % (state.B.shape,))
    state.record_event(
        "matrix_loaded",
        path="embedded_default",
        shape=list(state.B.shape),
        mat_status=state.mat_status,
        bump_dim=state.bump_dim,
        matrix=state.B.tolist(),
    )


WINDOW_TITLE = "Chromaticity tool pos alpha@MLS"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Standalone legacy-style control-room GUI.")
    parser.add_argument(
        "--safe",
        action="store_true",
        help="Read-only preflight mode. Live reads are allowed but machine writes are suppressed.",
    )
    parser.add_argument(
        "--no-default-matrix",
        action="store_true",
        help="Skip loading the embedded default response matrix on startup.",
    )
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
            auto_load_default_matrix=False,
            log_root=Path(args.log_dir) if args.log_dir else None,
        )
    )
    state.record_event(
        "process_arguments",
        argv=list(argv) if argv is not None else sys.argv[1:],
        safe=args.safe,
        no_default_matrix=args.no_default_matrix,
    )
    if not args.no_default_matrix:
        apply_embedded_default_matrix(state)
    return launch_gui(state, window_title=WINDOW_TITLE)


if __name__ == "__main__":
    raise SystemExit(main())
