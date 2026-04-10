"""Small measurement helpers extracted from the legacy chromaticity tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

SPEED_OF_LIGHT_M_PER_S = 299792458.0


try:
    from .epics_adapter import BetaguiPVs
except ImportError:  # pragma: no cover - allows PYTHONPATH=src usage
    from epics_adapter import BetaguiPVs


@dataclass
class MeasurementInputs:
    n_tune_samples: int = 7
    n_rf_points: int = 11
    delta_x_min_mm: float = -2.0
    delta_x_max_mm: float = 2.0
    fit_order: int = 1
    delay_after_rf_s: float = 5.0
    delay_between_tune_reads_s: float = 1.0
    alpha0_mode: str = "dynamic"


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


def sample_tunes(adapter, pvs: BetaguiPVs, n_samples: int) -> Dict[str, float]:
    if not pvs.tune_x or not pvs.tune_y:
        raise ValueError("This profile requires at least X and Y tune PVs.")
    tune_x = [float(adapter.get(pvs.tune_x, 0.0) or 0.0) for _ in range(n_samples)]
    tune_y = [float(adapter.get(pvs.tune_y, 0.0) or 0.0) for _ in range(n_samples)]
    if pvs.tune_s:
        tune_s = [float(adapter.get(pvs.tune_s, 0.0) or 0.0) for _ in range(n_samples)]
    else:
        tune_s = [0.0 for _ in range(n_samples)]
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
        sampled = sample_tunes(adapter, pvs, inputs.n_tune_samples)
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
