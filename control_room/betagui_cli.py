#!/usr/bin/env python3
"""Standalone legacy-profile control-room CLI for chromaticity measurement.

By default this behaves like the legacy script and allows live writes.
Use ``--safe`` for read-only preflight.
"""

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

SPEED_OF_LIGHT_M_PER_S = 299792458.0
NHARMONIC = 80


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
    tune_s: Optional[str] = "TUNEZRP:measZ"
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


def optics_mode_to_dmax(optics_mode) -> float:
    if optics_mode == 1:
        return 1.5
    if optics_mode == 3:
        return 1.0
    return 2.0


def calculate_alpha0(adapter, pvs: BetaguiPVs, harmonic_number: int = NHARMONIC, samples: int = 10) -> float:
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
    }


class GuardedAdapter:
    def __init__(self, adapter, allow_machine_writes: bool, logger):
        self._adapter = adapter
        self.allow_machine_writes = allow_machine_writes
        self._logger = logger

    def get(self, name: str, default=None):
        try:
            return self._adapter.get(name, default)
        except Exception as exc:
            self._logger("Read failed for %s: %s" % (name, exc))
            return default

    def put(self, name: str, value):
        if self.allow_machine_writes:
            try:
                return self._adapter.put(name, value)
            except Exception as exc:
                self._logger("Write failed for %s: %s" % (name, exc))
                return False
        self._logger("Suppressed live write to %s -> %r" % (name, value))
        return False


@dataclass
class RuntimeConfig:
    allow_machine_writes: bool = True


@dataclass
class RuntimeState:
    config: RuntimeConfig
    pvs: BetaguiPVs = field(default_factory=BetaguiPVs)
    adapter: Optional[GuardedAdapter] = None
    messages: List[str] = field(default_factory=list)
    frf0: float = 0.0
    ini_fdb: List[float] = field(default_factory=list)
    ini_orbit: float = 0.0
    saved_settings_valid: bool = False
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
    state = RuntimeState(config=config or RuntimeConfig())
    try:
        base_adapter = EpicsAdapter()
        state.log("Using live EPICS adapter.")
    except EpicsUnavailableError as exc:
        state.log(str(exc))
        base_adapter = UnavailableAdapter()
    state.adapter = GuardedAdapter(base_adapter, state.config.allow_machine_writes, state.log)
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


def save_setting(state: RuntimeState):
    raw_rf = state.adapter.get(state.pvs.rf_setpoint, None)
    if raw_rf in (None, ""):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is unavailable.")
        return False
    try:
        state.frf0 = float(raw_rf)
    except (TypeError, ValueError):
        state.saved_settings_valid = False
        state.log("Could not save current settings: RF setpoint is non-numeric (%r)." % (raw_rf,))
        return False
    state.ini_fdb = [
        _get_float(state, state.pvs.feedback_x, 0.0),
        _get_float(state, state.pvs.feedback_y, 0.0),
        _get_float(state, state.pvs.feedback_s, 0.0),
    ]
    state.ini_orbit = _get_float(state, state.pvs.orbit_mode_readback, 0.0)
    state.saved_settings_valid = True
    state.log("Saved current settings.")
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
        alpha0 = calculate_alpha0(state.adapter, state.pvs, harmonic_number=NHARMONIC)
    except Exception as exc:
        state.log("Could not calculate alpha0: %s" % exc)
        return None
    state.log("alpha0 = %.8f" % alpha0)
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
    if alpha0 is None:
        alpha0 = calculate_alpha0(state.adapter, state.pvs, harmonic_number=NHARMONIC)
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
            tune_x.append(sampled["x"])
            tune_y.append(sampled["y"])
            tune_s.append(sampled["s"])
    finally:
        state.adapter.put(state.pvs.rf_setpoint, frf0_hz)
        restore_feedback_after_measurement(state, snapshot)
    fit_order = min(inputs.fit_order, len(delta_hz) - 1)
    fit_x = np.poly1d(np.polyfit(delta_hz, tune_x, fit_order))
    fit_y = np.poly1d(np.polyfit(delta_hz, tune_y, fit_order))
    fit_s = np.poly1d(np.polyfit(delta_hz, tune_s, fit_order))
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
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state = create_runtime(RuntimeConfig(allow_machine_writes=not args.safe))
    if args.safe:
        print("Legacy-profile read-only preflight")
        print("  rf =", state.adapter.get(state.pvs.rf_setpoint))
        print("  tune_x =", state.adapter.get(state.pvs.tune_x))
        print("  tune_y =", state.adapter.get(state.pvs.tune_y))
        print("  tune_s =", state.adapter.get(state.pvs.tune_s))
        if args.check_alpha0:
            try:
                alpha0 = calculate_alpha0(state.adapter, state.pvs, harmonic_number=NHARMONIC)
            except Exception as exc:
                state.log("Could not calculate alpha0: %s" % exc)
                alpha0 = None
            print("  alpha0 =", alpha0)
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
    try:
        result = measure_chromaticity(state, inputs, alpha0=alpha0)
    except Exception as exc:
        state.log("Chromaticity measurement failed: %s" % exc)
        return 1
    set_frf_slowly(state, state.frf0)
    state.last_result = result
    print("Measured xi:")
    print("  xi_x = %.6f" % result.xi[0])
    print("  xi_y = %.6f" % result.xi[1])
    print("  xi_s = %.6f" % result.xi[2])
    print("  alpha0 = %.8f" % result.alpha0)
    if args.output:
        output_path = Path(args.output)
        np.savetxt(output_path, np.asarray(result.xi, dtype=float))
        print("Saved xi to %s" % output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
