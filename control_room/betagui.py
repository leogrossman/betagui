#!/usr/bin/env python3
"""Standalone legacy-style control-room GUI.

By default this behaves like the legacy script and allows live writes.
Use ``--safe`` for read-only preflight.
"""

# ------------------------------------------------------------------------------
# Imports
# ------------------------------------------------------------------------------

import argparse
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import tkinter as tk
    from tkinter import filedialog

    TK_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host packages
    tk = None
    filedialog = None
    TK_AVAILABLE = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host packages
    FigureCanvasTkAgg = None
    Figure = None
    MATPLOTLIB_AVAILABLE = False


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
pvfreqS = "TUNEZRP:measZ"
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


def optics_mode_to_dmax(optics_mode) -> float:
    if optics_mode == 1:
        return 1.5
    if optics_mode == 3:
        return 1.0
    return 2.0


def calculate_alpha0(adapter, pvs: BetaguiPVs, harmonic_number: int = 80, samples: int = 10) -> float:
    if not pvs.tune_s or not pvs.rf_setpoint or not pvs.cavity_voltage or not pvs.beam_energy:
        raise ValueError("Dynamic alpha0 requires tune_s, RF, cavity voltage, and beam energy PVs.")
    freq_samples = [float(adapter.get(pvs.tune_s, 0.0) or 0.0) for _ in range(samples)]
    freq_s_khz = float(np.mean(freq_samples))
    rf_hz = float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0)
    cavity_voltage_v = float(adapter.get(pvs.cavity_voltage, 0.0) or 0.0) * 1000.0
    energy_ev = float(adapter.get(pvs.beam_energy, 0.0) or 0.0) * 1e6
    if rf_hz == 0.0 or cavity_voltage_v == 0.0:
        raise ValueError("RF frequency and cavity voltage must be non-zero.")
    return (freq_s_khz * 1000.0) ** 2 / (rf_hz * 1000.0) ** 2 * 2.0 * np.pi * harmonic_number * energy_ev / cavity_voltage_v


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
    for sample_index in range(n_samples):
        tune_x.append(float(adapter.get(pvs.tune_x, 0.0) or 0.0))
        tune_y.append(float(adapter.get(pvs.tune_y, 0.0) or 0.0))
        if pvs.tune_s:
            tune_s.append(float(adapter.get(pvs.tune_s, 0.0) or 0.0))
        else:
            tune_s.append(0.0)
        if sample_index != n_samples - 1 and delay_between_reads_s > 0.0:
            time.sleep(delay_between_reads_s)
    return {
        "x": average_tune_samples(tune_x),
        "y": average_tune_samples(tune_y),
        "s": average_tune_samples(tune_s),
    }


def measure_chromaticity(adapter, pvs: BetaguiPVs, inputs: MeasurementInputs, alpha0: Optional[float] = None, harmonic_number: int = 80) -> MeasurementResult:
    if not pvs.rf_setpoint:
        raise ValueError("No RF PV configured for this profile.")
    frf0_hz = float(adapter.get(pvs.rf_setpoint, 0.0) or 0.0)
    if alpha0 is None:
        alpha0 = calculate_alpha0(adapter, pvs, harmonic_number=harmonic_number)
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
    for rf_hz in rf_points_hz:
        ramp_rf(adapter, pvs.rf_setpoint, float(rf_hz))
        if inputs.delay_after_rf_s > 0.0:
            time.sleep(inputs.delay_after_rf_s)
        sampled = sample_tunes(
            adapter,
            pvs,
            inputs.n_tune_samples,
            delay_between_reads_s=inputs.delay_between_tune_reads_s,
        )
        tune_x.append(sampled["x"])
        tune_y.append(sampled["y"])
        tune_s.append(sampled["s"])
    ramp_rf(adapter, pvs.rf_setpoint, frf0_hz)
    fit_order = min(inputs.fit_order, len(delta_hz) - 1)
    fit_x = np.poly1d(np.polyfit(delta_hz, tune_x, fit_order))
    fit_y = np.poly1d(np.polyfit(delta_hz, tune_y, fit_order))
    fit_s = np.poly1d(np.polyfit(delta_hz, tune_s, fit_order))
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


def measure_chromaticity_with_feedback_control(adapter, pvs: BetaguiPVs, inputs: MeasurementInputs, alpha0: Optional[float] = None, harmonic_number: int = 80) -> MeasurementResult:
    """Legacy-like wrapper that disables/restores feedback around measurement."""
    snapshot = disable_feedback_for_measurement(adapter, pvs)
    try:
        return measure_chromaticity(
            adapter=adapter,
            pvs=pvs,
            inputs=inputs,
            alpha0=alpha0,
            harmonic_number=harmonic_number,
        )
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

    def __init__(self, adapter, allow_machine_writes: bool, logger):
        self._adapter = adapter
        self.allow_machine_writes = allow_machine_writes
        self._logger = logger

    def get(self, name: str, default=None):
        try:
            return self._adapter.get(name, default)
        except Exception as exc:  # pragma: no cover - depends on external EPICS
            self._logger("Read failed for %s: %s" % (name, exc))
            return default

    def put(self, name: str, value):
        if self.allow_machine_writes:
            try:
                return self._adapter.put(name, value)
            except Exception as exc:  # pragma: no cover - depends on external EPICS
                self._logger("Write failed for %s: %s" % (name, exc))
                return False
        self._logger("Suppressed live write to %s -> %r" % (name, value))
        return False


@dataclass
class RuntimeConfig:
    allow_machine_writes: bool = False
    auto_load_default_matrix: bool = True


@dataclass
class RuntimeState:
    config: RuntimeConfig
    pvs: BetaguiPVs = field(default_factory=BetaguiPVs.legacy)
    adapter: Optional[GuardedAdapter] = None
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

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (timestamp, message)
        self.messages.append(line)
        print(line)

    @property
    def can_write_machine(self) -> bool:
        return self.config.allow_machine_writes


def create_runtime(config: Optional[RuntimeConfig] = None) -> RuntimeState:
    config = config or RuntimeConfig()
    state = RuntimeState(config=config, pvs=BetaguiPVs.legacy())
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
        return False
    try:
        frf0 = float(raw_rf)
    except (TypeError, ValueError):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is non-numeric (%r)." % (raw_rf,))
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
    state.log("RF now at %.6f Hz" % float(rf_steps[-1]))


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
        return False
    state.log("Resetting saved parameters.")
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
    return True


def cal_alpha0(state: RuntimeState) -> Optional[float]:
    try:
        alpha0 = calculate_alpha0(state.adapter, state.pvs, harmonic_number=NHARMONIC)
    except Exception as exc:
        state.log("Could not calculate alpha0: %s" % exc)
        return None
    state.log("alpha0 = %.8f" % alpha0)
    return alpha0


def BPDM():
    """Legacy BPM helper kept close to the original behavior."""
    return BPM_POSITIONS, [0.0 for _ in BPM_POSITIONS]


def set_all_sexts(state: RuntimeState, delta_chrom: Sequence[float]):
    """WRITE PATH: apply inverse response matrix to sextupole currents."""
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
        return {}
    state.log("Applied sextupole increments: %s" % applied)
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
    state.log(
        "RF sweep plan: %d points, %d tune samples per point."
        % (inputs.n_rf_points, inputs.n_tune_samples)
    )
    if alpha0_text == "dynamic":
        state.log("alpha0 source: dynamic from live PVs.")
    else:
        state.log("alpha0 source: fixed value %s." % alpha0_text)


def MeaChrom(state: RuntimeState, entry_values: Dict[str, str]) -> Optional[List[float]]:
    """Legacy-style chromaticity measurement wrapper."""
    state.stop_requested = False
    state.log("Starting chromaticity measurement.")
    try:
        inputs = _measurement_inputs_from_dict(entry_values)
    except Exception as exc:
        state.log("Invalid measurement inputs: %s" % exc)
        return None

    if not state.can_write_machine:
        state.log("Chromaticity measurement needs write access.")
        return None

    alpha0_text = entry_values.get("alpha0", "dynamic").strip()
    alpha0 = None
    if alpha0_text and alpha0_text != "dynamic":
        try:
            alpha0 = float(alpha0_text)
        except ValueError:
            state.log("Invalid alpha0 entry: %r" % alpha0_text)
            return None
    _log_measurement_plan(state, inputs, alpha0_text)

    try:
        result = measure_chromaticity_with_feedback_control(
            adapter=state.adapter,
            pvs=state.pvs,
            inputs=inputs,
            alpha0=alpha0,
            harmonic_number=NHARMONIC,
        )
    except Exception as exc:
        state.log("Chromaticity measurement failed: %s" % exc)
        return None

    set_frf_slowly(state, state.frf0)
    state.log("Measured xi = %s" % [round(value, 4) for value in result.xi])
    state.last_result = result  # porting change: cache latest result for plotting
    return result.xi


def measure_response_matrix(state: RuntimeState, entry_values: Dict[str, str]) -> Optional[np.ndarray]:
    """WRITE PATH: step sextupoles and measure the response matrix."""
    state.log("Starting response matrix measurement.")
    if not state.can_write_machine:
        state.log("Response matrix measurement needs write access.")
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
            return None
        a_matrix[index, :] = (np.asarray(xi_2) - np.asarray(xi_1))[0:bump_dim]

    try:
        state.B = np.linalg.inv(a_matrix.T)
    except np.linalg.LinAlgError as exc:
        state.log("Response matrix inversion failed: %s" % exc)
        return None
    state.bump_dim = bump_dim
    state.mat_status = state.bump_option
    state.log("Measured response matrix with shape %s." % (state.B.shape,))
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
        self.matrix_button = tk.Button(parent, text="Measure matrix", command=self._on_measure_matrix)
        self.matrix_button.grid(row=11, column=0, columnspan=2, sticky="ew", pady=2)
        self.reset_button = tk.Button(parent, text="reset", command=self._on_reset)
        self.reset_button.grid(row=12, column=0, columnspan=2, sticky="ew", pady=2)
        self.save_state_button = tk.Button(parent, text="Save current setting", command=self._on_save_setting)
        self.save_state_button.grid(row=13, column=0, columnspan=2, sticky="ew", pady=2)
        self.stop_button = tk.Button(parent, text="Stop", command=self._on_stop)
        self.stop_button.grid(row=14, column=0, columnspan=2, sticky="ew", pady=2)
        self.scan_button = tk.Button(parent, text="sext scan", command=self._on_open_scan_window)
        self.scan_button.grid(row=15, column=0, columnspan=2, sticky="ew", pady=2)

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
        labels = ("x", "y", "s")
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
        self.ax_orbit.set_xlabel("BPM position")
        self.ax_orbit.set_ylabel("Orbit displacement")
        plots = (
            (self.ax_x, result.delta_hz, result.tune_x_khz, result.fit_x, "fx"),
            (self.ax_y, result.delta_hz, result.tune_y_khz, result.fit_y, "fy"),
            (self.ax_s, result.delta_hz, result.tune_s_khz, result.fit_s, "fs"),
        )
        for axis, delta_hz, tune_values, fit_poly, label in plots:
            axis.clear()
            axis.plot(delta_hz, tune_values, "ro")
            axis.plot(delta_hz, fit_poly(delta_hz), "b-")
            axis.set_xlabel("dfrf")
            axis.set_ylabel(label)
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

    def _on_measure(self):
        self._run_background(MeaChrom, self.state, self._entry_values())

    def _on_alpha(self):
        def worker():
            self.state.log("Starting alpha0 calculation.")
            alpha0 = cal_alpha0(self.state)
            if alpha0 is not None:
                self.after(0, lambda: self.entry_vars["alpha0"].set(str(alpha0)))

        self._run_background(worker)

    def _on_measure_matrix(self):
        self._run_background(start_bump, self.state, self._entry_values())

    def _on_reset(self):
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
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state = create_runtime(
        RuntimeConfig(
            allow_machine_writes=not args.safe,
            auto_load_default_matrix=False,
        )
    )
    if not args.no_default_matrix:
        apply_embedded_default_matrix(state)
    return launch_gui(state, window_title=WINDOW_TITLE)


if __name__ == "__main__":
    raise SystemExit(main())
