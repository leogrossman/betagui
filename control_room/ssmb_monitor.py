#!/usr/bin/env python3
"""Optional read-only SSMB monitoring window for the control-room GUI."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional

try:
    import tkinter as tk
except ImportError:  # pragma: no cover - depends on host packages
    tk = None


E_REST_MEV = 0.51099895
REVOLUTION_FREQUENCY_KHZ = 299792458.0 / 48.0 / 1000.0


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tune_s_khz_from_pv(raw_value: float) -> float:
    return raw_value / 1000.0


def _unitless_tune_from_khz(freq_khz: float) -> float:
    return freq_khz / REVOLUTION_FREQUENCY_KHZ


def _severity_from_thresholds(value: Optional[float], green: float, yellow: float, invert: bool = False) -> str:
    if value is None:
        return "UNKNOWN"
    val = abs(value)
    if invert:
        if val > green:
            return "GREEN"
        if val > yellow:
            return "YELLOW"
        return "RED"
    if val < green:
        return "GREEN"
    if val < yellow:
        return "YELLOW"
    return "RED"


@dataclass
class MonitorSample:
    timestamp: float
    rf_pv: Optional[float]
    alpha0: Optional[float]
    eta: Optional[float]
    tune_x: Optional[float]
    tune_y: Optional[float]
    tune_s: Optional[float]
    tune_x_khz: Optional[float]
    tune_y_khz: Optional[float]
    tune_s_khz: Optional[float]
    tune_x_raw: Optional[float]
    tune_y_raw: Optional[float]
    tune_s_raw: Optional[float]
    feedback_x: Optional[float]
    feedback_y: Optional[float]
    feedback_s: Optional[float]
    cavity_voltage_kv: Optional[float]
    beam_energy_mev: Optional[float]
    beam_current: Optional[float]
    white_noise: Optional[float]
    optics_mode: Optional[float]
    tune_x_jitter: Optional[float] = None
    tune_y_jitter: Optional[float] = None
    tune_s_jitter: Optional[float] = None
    rf_jitter: Optional[float] = None


class _PollWorker(threading.Thread):
    def __init__(self, state, result_queue, stop_event):
        super().__init__(daemon=True)
        self.state = state
        self.result_queue = result_queue
        self.stop_event = stop_event
        self.rf_history = deque(maxlen=20)
        self.tx_history = deque(maxlen=20)
        self.ty_history = deque(maxlen=20)
        self.ts_history = deque(maxlen=20)

    def run(self):
        while not self.stop_event.is_set():
            sample = self._collect_sample()
            self.result_queue.put(sample)
            self.stop_event.wait(1.0)

    def _collect_sample(self):
        pvs = self.state.pvs
        adapter = self.state.adapter
        now = time.time()
        rf_pv = _safe_float(adapter.get(pvs.rf_setpoint, None), None)
        tx_raw = _safe_float(adapter.get(pvs.tune_x, None), None)
        ty_raw = _safe_float(adapter.get(pvs.tune_y, None), None)
        ts_raw = _safe_float(adapter.get(pvs.tune_s, None), None)
        tx_khz = tx_raw
        ty_khz = ty_raw
        ts_khz = _tune_s_khz_from_pv(ts_raw) if ts_raw is not None else None
        tx = _unitless_tune_from_khz(tx_khz) if tx_khz is not None else None
        ty = _unitless_tune_from_khz(ty_khz) if ty_khz is not None else None
        ts = _unitless_tune_from_khz(ts_khz) if ts_khz is not None else None
        ucav_kv = _safe_float(adapter.get(pvs.cavity_voltage, None), None)
        energy_mev = _safe_float(adapter.get(pvs.beam_energy, None), None)
        alpha0 = None
        eta = None
        if ts is not None and ts > 0.0 and ucav_kv and energy_mev:
            alpha0 = (ts ** 2) * 2.0 * math.pi * (energy_mev * 1e6) / (80.0 * (ucav_kv * 1000.0))
            gamma = energy_mev / E_REST_MEV
            eta = alpha0 - 1.0 / (gamma * gamma)

        for history, value in (
            (self.rf_history, rf_pv),
            (self.tx_history, tx),
            (self.ty_history, ty),
            (self.ts_history, ts),
        ):
            if value is not None:
                history.append(float(value))

        def _std(values):
            if len(values) < 2:
                return None
            mean = sum(values) / len(values)
            variance = sum((item - mean) ** 2 for item in values) / len(values)
            return math.sqrt(variance)

        return MonitorSample(
            timestamp=now,
            rf_pv=rf_pv,
            alpha0=alpha0,
            eta=eta,
            tune_x=tx,
            tune_y=ty,
            tune_s=ts,
            tune_x_khz=tx_khz,
            tune_y_khz=ty_khz,
            tune_s_khz=ts_khz,
            tune_x_raw=tx_raw,
            tune_y_raw=ty_raw,
            tune_s_raw=ts_raw,
            feedback_x=_safe_float(adapter.get(pvs.feedback_x, None), None),
            feedback_y=_safe_float(adapter.get(pvs.feedback_y, None), None),
            feedback_s=_safe_float(adapter.get(pvs.feedback_s, None), None),
            cavity_voltage_kv=ucav_kv,
            beam_energy_mev=energy_mev,
            beam_current=_safe_float(adapter.get(getattr(pvs, "beam_current", None), None), None),
            white_noise=_safe_float(adapter.get(getattr(pvs, "white_noise", None), None), None),
            optics_mode=_safe_float(adapter.get(pvs.optics_mode, None), None),
            tune_x_jitter=_std(self.tx_history),
            tune_y_jitter=_std(self.ty_history),
            tune_s_jitter=_std(self.ts_history),
            rf_jitter=_std(self.rf_history),
        )


class SSMBMonitorWindow:
    def __init__(self, master, state):
        if tk is None:
            raise RuntimeError("tkinter is unavailable.")
        self.master = master
        self.state = state
        self.window = tk.Toplevel(master)
        self.window.title("SSMB monitor")
        self.window.geometry("640x560")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = _PollWorker(state, self.result_queue, self.stop_event)
        self.current_sample = None
        self.status_text = tk.Text(self.window, wrap="word", height=30, width=80)
        self.status_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.worker.start()
        self._tick()

    def _tick(self):
        if not self.window.winfo_exists():
            return
        while True:
            try:
                self.current_sample = self.result_queue.get_nowait()
            except queue.Empty:
                break
        if self.current_sample is not None:
            self._render(self.current_sample)
        self.window.after(500, self._tick)

    def _line(self, label: str, value, severity: str):
        return "%-18s %-16s %s" % (label, value, severity)

    def _render(self, sample: MonitorSample):
        severity = []
        eta_state = _severity_from_thresholds(sample.eta, 2e-5, 1e-4)
        alpha0_state = "GREEN" if sample.alpha0 is not None and 1e-5 < sample.alpha0 < 5e-2 else "YELLOW"
        rf_state = _severity_from_thresholds(sample.rf_jitter, 0.02, 0.10)
        tx_state = _severity_from_thresholds(sample.tune_x_jitter, 1e-4, 5e-4)
        ty_state = _severity_from_thresholds(sample.tune_y_jitter, 1e-4, 5e-4)
        ts_state = _severity_from_thresholds(sample.tune_s_jitter, 1e-5, 5e-5)
        feedback_state = "GREEN" if (sample.feedback_x, sample.feedback_y, sample.feedback_s) == (1.0, 1.0, 1.0) else "YELLOW"

        for state in (eta_state, alpha0_state, rf_state, tx_state, ty_state, ts_state):
            severity.append(state)

        score = max(0, 100 - 20 * severity.count("RED") - 8 * severity.count("YELLOW"))
        if score >= 80:
            status = "OK"
        elif score >= 55:
            status = "MARGINAL"
        else:
            status = "FAIL"

        lines = [
            "SSMB STATUS: %s   score=%d" % (status, score),
            "",
            "[ Longitudinal ]",
            self._line("eta", "%.6e" % sample.eta if sample.eta is not None else "UNKNOWN", eta_state),
            self._line("alpha0", "%.8f" % sample.alpha0 if sample.alpha0 is not None else "UNKNOWN", alpha0_state),
            self._line("Qs", "%.6f" % sample.tune_s if sample.tune_s is not None else "UNKNOWN", ts_state),
            self._line("f_s [kHz]", "%.6f" % sample.tune_s_khz if sample.tune_s_khz is not None else "UNKNOWN", ts_state),
            self._line("RF jitter", "%.6f" % sample.rf_jitter if sample.rf_jitter is not None else "UNKNOWN", rf_state),
            "",
            "[ Transverse ]",
            self._line("Qx", "%.6f" % sample.tune_x if sample.tune_x is not None else "UNKNOWN", tx_state),
            self._line("Qy", "%.6f" % sample.tune_y if sample.tune_y is not None else "UNKNOWN", ty_state),
            self._line("Qx jitter", "%.6e" % sample.tune_x_jitter if sample.tune_x_jitter is not None else "UNKNOWN", tx_state),
            self._line("Qy jitter", "%.6e" % sample.tune_y_jitter if sample.tune_y_jitter is not None else "UNKNOWN", ty_state),
            self._line("xi_x", "%.4f" % self._last_xi(0) if self._last_xi(0) is not None else "UNKNOWN", self._xi_state(0)),
            self._line("xi_y", "%.4f" % self._last_xi(1) if self._last_xi(1) is not None else "UNKNOWN", self._xi_state(1)),
            "",
            "[ Machine / raw ]",
            self._line("RF PV", "%.6f" % sample.rf_pv if sample.rf_pv is not None else "UNKNOWN", "INFO"),
            self._line("tuneX raw", "%.6f" % sample.tune_x_raw if sample.tune_x_raw is not None else "UNKNOWN", "INFO"),
            self._line("tuneY raw", "%.6f" % sample.tune_y_raw if sample.tune_y_raw is not None else "UNKNOWN", "INFO"),
            self._line("tuneSyn raw", "%.6f" % sample.tune_s_raw if sample.tune_s_raw is not None else "UNKNOWN", "INFO"),
            self._line("Ucav [kV]", "%.3f" % sample.cavity_voltage_kv if sample.cavity_voltage_kv is not None else "UNKNOWN", "INFO"),
            self._line("E [MeV]", "%.3f" % sample.beam_energy_mev if sample.beam_energy_mev is not None else "UNKNOWN", "INFO"),
            self._line("Beam current", "%.6f" % sample.beam_current if sample.beam_current is not None else "UNKNOWN", "INFO"),
            self._line("Feedback", "%s/%s/%s" % (sample.feedback_x, sample.feedback_y, sample.feedback_s), feedback_state),
            "",
            "[ Diagnostics ]",
        ]
        lines.extend(self._inferred_faults(sample))
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert("1.0", "\n".join(lines))

    def _last_xi(self, index: int):
        result = getattr(self.state, "last_result", None)
        if result is None:
            return None
        return float(result.xi[index])

    def _xi_state(self, index: int):
        value = self._last_xi(index)
        if value is None:
            return "UNKNOWN"
        abs_value = abs(value)
        if abs_value < 1.0:
            return "GREEN"
        if abs_value < 3.0:
            return "YELLOW"
        return "RED"

    def _inferred_faults(self, sample: MonitorSample):
        issues = []
        if sample.eta is not None and abs(sample.eta) > 1e-4:
            issues.append("- slip factor too large for comfortable SSMB operation")
        if sample.tune_s_jitter is not None and sample.tune_s_jitter > 5e-5:
            issues.append("- synchrotron tune jitter is high")
        if sample.rf_jitter is not None and sample.rf_jitter > 0.10:
            issues.append("- RF readback jitter is high")
        if self._last_xi(0) is not None and abs(self._last_xi(0)) > 3.0:
            issues.append("- horizontal chromaticity is far from zero")
        if self._last_xi(1) is not None and abs(self._last_xi(1)) > 3.0:
            issues.append("- vertical chromaticity is far from zero")
        if not issues:
            issues.append("- no immediate SSMB red flags from current readbacks")
        return issues

    def close(self):
        self.stop_event.set()
        self.window.destroy()


def open_window(master, state):
    return SSMBMonitorWindow(master, state)
