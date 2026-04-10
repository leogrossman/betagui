#!/usr/bin/env python3
"""Optional read-only SSMB monitoring window for the control-room GUI."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover - depends on host packages
    tk = None
    ttk = None

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on host packages
    FigureCanvasTkAgg = None
    Figure = None
    MATPLOTLIB_AVAILABLE = False


E_REST_MEV = 0.51099895
REVOLUTION_FREQUENCY_KHZ = 299792458.0 / 48.0 / 1000.0
POLL_INTERVAL_SECONDS = 1.0
ROLLING_HISTORY_LENGTH = 60
PLOT_HISTORY_LENGTH = 300
SEVERITY_COLORS = {
    "GREEN": "#c7efcf",
    "YELLOW": "#fff4b2",
    "RED": "#f6b0ae",
    "UNKNOWN": "#d9d9d9",
    "INFO": "#d7e7ff",
}
STATUS_THRESHOLDS = {
    "eta": {"green": 2e-5, "yellow": 1e-4},
    "alpha0_low": {"green_min": 1e-5, "green_max": 5e-2},
    "tune_jitter_xy": {"green": 1e-4, "yellow": 5e-4},
    "tune_jitter_s": {"green": 1e-5, "yellow": 5e-5},
    "rf_jitter": {"green": 0.02, "yellow": 0.10},
    "xi": {"green": 1.0, "yellow": 3.0},
    "resonance_distance": {"green": 0.03, "yellow": 0.01},
    "lifetime": {"green": 5.0, "yellow": 1.0},
    "coupling_corr": {"green": 0.20, "yellow": 0.50},
}
OPTIONAL_READBACK_PVS = {
    "u125_1": "U125IL2RP",
}
TREND_CHOICES = [
    ("eta", "η"),
    ("alpha0", "α0"),
    ("tune_x", "Qx"),
    ("tune_y", "Qy"),
    ("tune_s", "Qs"),
    ("tune_s_khz", "f_s [kHz]"),
    ("rf_pv", "RF PV"),
    ("rf_jitter", "RF jitter"),
    ("tune_x_jitter", "Qx jitter"),
    ("tune_y_jitter", "Qy jitter"),
    ("tune_s_jitter", "Qs jitter"),
    ("coupling_xs", "corr(Qx,Qs)"),
    ("coupling_ys", "corr(Qy,Qs)"),
    ("beam_current", "Beam current"),
    ("white_noise", "White noise"),
    ("xi_x", "ξx"),
    ("xi_y", "ξy"),
    ("xi_s", "ξs"),
    ("u125_1", "U125/1"),
]


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tune_s_khz_from_pv(raw_value: float) -> float:
    return float(raw_value) / 1000.0


def _unitless_tune_from_khz(freq_khz: float) -> float:
    return float(freq_khz) / REVOLUTION_FREQUENCY_KHZ


def _severity_from_thresholds(value: Optional[float], green: float, yellow: float) -> str:
    if value is None:
        return "UNKNOWN"
    value = abs(value)
    if value < green:
        return "GREEN"
    if value < yellow:
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
    u125_1: Optional[float] = None
    lifetime_10h: Optional[float] = None
    lifetime_100h: Optional[float] = None
    lifetime_calc: Optional[float] = None
    sigma_x_1: Optional[float] = None
    sigma_y_1: Optional[float] = None
    sigma_x_0: Optional[float] = None
    sigma_y_0: Optional[float] = None
    resonance_dx: Optional[float] = None
    resonance_dy: Optional[float] = None
    tune_x_jitter: Optional[float] = None
    tune_y_jitter: Optional[float] = None
    tune_s_jitter: Optional[float] = None
    rf_jitter: Optional[float] = None
    coupling_xs: Optional[float] = None
    coupling_ys: Optional[float] = None
    xi_x: Optional[float] = None
    xi_y: Optional[float] = None
    xi_s: Optional[float] = None


class _PollWorker(threading.Thread):
    def __init__(self, state, result_queue, stop_event):
        super().__init__(daemon=True)
        self.state = state
        self.result_queue = result_queue
        self.stop_event = stop_event
        self.rf_history = deque(maxlen=ROLLING_HISTORY_LENGTH)
        self.tx_history = deque(maxlen=ROLLING_HISTORY_LENGTH)
        self.ty_history = deque(maxlen=ROLLING_HISTORY_LENGTH)
        self.ts_history = deque(maxlen=ROLLING_HISTORY_LENGTH)

    def run(self):
        while not self.stop_event.is_set():
            self.result_queue.put(self._collect_sample())
            self.stop_event.wait(POLL_INTERVAL_SECONDS)

    def _std(self, values):
        if len(values) < 2:
            return None
        mean = sum(values) / len(values)
        variance = sum((item - mean) ** 2 for item in values) / len(values)
        return math.sqrt(variance)

    def _corr(self, xs, ys):
        points = [(float(x), float(y)) for x, y in zip(xs, ys) if x is not None and y is not None]
        if len(points) < 4:
            return None
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(y_values) / len(y_values)
        x_var = sum((value - x_mean) ** 2 for value in x_values) / len(x_values)
        y_var = sum((value - y_mean) ** 2 for value in y_values) / len(y_values)
        if x_var <= 0.0 or y_var <= 0.0:
            return None
        covariance = sum((x - x_mean) * (y - y_mean) for x, y in points) / len(points)
        return covariance / math.sqrt(x_var * y_var)

    def _collect_sample(self):
        pvs = self.state.pvs
        adapter = self.state.adapter
        now = time.time()

        rf_pv = _safe_float(adapter.get(pvs.rf_setpoint, None), None)
        tune_x_raw = _safe_float(adapter.get(pvs.tune_x, None), None)
        tune_y_raw = _safe_float(adapter.get(pvs.tune_y, None), None)
        tune_s_raw = _safe_float(adapter.get(pvs.tune_s, None), None)
        tune_x_khz = tune_x_raw
        tune_y_khz = tune_y_raw
        tune_s_khz = _tune_s_khz_from_pv(tune_s_raw) if tune_s_raw is not None else None
        tune_x = _unitless_tune_from_khz(tune_x_khz) if tune_x_khz is not None else None
        tune_y = _unitless_tune_from_khz(tune_y_khz) if tune_y_khz is not None else None
        tune_s = _unitless_tune_from_khz(tune_s_khz) if tune_s_khz is not None else None

        cavity_voltage_kv = _safe_float(adapter.get(pvs.cavity_voltage, None), None)
        beam_energy_mev = _safe_float(adapter.get(pvs.beam_energy, None), None)
        lifetime_10h = _safe_float(adapter.get(getattr(pvs, "beam_lifetime_10h", None), None), None)
        lifetime_100h = _safe_float(adapter.get(getattr(pvs, "beam_lifetime_100h", None), None), None)
        lifetime_calc = _safe_float(adapter.get(getattr(pvs, "calculated_lifetime", None), None), None)
        sigma_x_1 = _safe_float(adapter.get(getattr(pvs, "qpd1_sigma_x", None), None), None)
        sigma_y_1 = _safe_float(adapter.get(getattr(pvs, "qpd1_sigma_y", None), None), None)
        sigma_x_0 = _safe_float(adapter.get(getattr(pvs, "qpd0_sigma_x", None), None), None)
        sigma_y_0 = _safe_float(adapter.get(getattr(pvs, "qpd0_sigma_y", None), None), None)
        alpha0 = None
        eta = None
        if tune_s is not None and tune_s > 0.0 and cavity_voltage_kv and beam_energy_mev:
            alpha0 = (tune_s ** 2) * 2.0 * math.pi * (beam_energy_mev * 1e6) / (80.0 * cavity_voltage_kv * 1000.0)
            gamma = beam_energy_mev / E_REST_MEV
            eta = alpha0 - 1.0 / (gamma * gamma)

        for history, value in (
            (self.rf_history, rf_pv),
            (self.tx_history, tune_x),
            (self.ty_history, tune_y),
            (self.ts_history, tune_s),
        ):
            if value is not None:
                history.append(float(value))

        last_result = getattr(self.state, "last_result", None)
        xi_x = float(last_result.xi[0]) if last_result is not None else None
        xi_y = float(last_result.xi[1]) if last_result is not None else None
        xi_s = float(last_result.xi[2]) if last_result is not None else None

        def _nearest_resonance_distance(tune_value):
            if tune_value is None:
                return None
            frac = tune_value % 1.0
            candidates = [0.0, 0.5, 1.0]
            return min(abs(frac - candidate) for candidate in candidates)

        return MonitorSample(
            timestamp=now,
            rf_pv=rf_pv,
            alpha0=alpha0,
            eta=eta,
            tune_x=tune_x,
            tune_y=tune_y,
            tune_s=tune_s,
            tune_x_khz=tune_x_khz,
            tune_y_khz=tune_y_khz,
            tune_s_khz=tune_s_khz,
            tune_x_raw=tune_x_raw,
            tune_y_raw=tune_y_raw,
            tune_s_raw=tune_s_raw,
            feedback_x=_safe_float(adapter.get(pvs.feedback_x, None), None),
            feedback_y=_safe_float(adapter.get(pvs.feedback_y, None), None),
            feedback_s=_safe_float(adapter.get(pvs.feedback_s, None), None),
            cavity_voltage_kv=cavity_voltage_kv,
            beam_energy_mev=beam_energy_mev,
            beam_current=_safe_float(adapter.get(getattr(pvs, "beam_current", None), None), None),
            white_noise=_safe_float(adapter.get(getattr(pvs, "white_noise", None), None), None),
            optics_mode=_safe_float(adapter.get(pvs.optics_mode, None), None),
            u125_1=_safe_float(adapter.get(OPTIONAL_READBACK_PVS["u125_1"], None), None),
            lifetime_10h=lifetime_10h,
            lifetime_100h=lifetime_100h,
            lifetime_calc=lifetime_calc,
            sigma_x_1=sigma_x_1,
            sigma_y_1=sigma_y_1,
            sigma_x_0=sigma_x_0,
            sigma_y_0=sigma_y_0,
            resonance_dx=_nearest_resonance_distance(tune_x),
            resonance_dy=_nearest_resonance_distance(tune_y),
            tune_x_jitter=self._std(self.tx_history),
            tune_y_jitter=self._std(self.ty_history),
            tune_s_jitter=self._std(self.ts_history),
            rf_jitter=self._std(self.rf_history),
            coupling_xs=self._corr(self.tx_history, self.ts_history),
            coupling_ys=self._corr(self.ty_history, self.ts_history),
            xi_x=xi_x,
            xi_y=xi_y,
            xi_s=xi_s,
        )


class SSMBMonitorWindow:
    def __init__(self, master, state):
        if tk is None:
            raise RuntimeError("tkinter is unavailable.")
        self.master = master
        self.state = state
        self.window = tk.Toplevel(master)
        self.window.title("SSMB monitor")
        self.window.geometry("1080x720")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = _PollWorker(state, self.result_queue, self.stop_event)
        self.current_sample = None
        self.history = deque(maxlen=PLOT_HISTORY_LENGTH)
        self.row_labels: Dict[str, Dict[str, tk.Label]] = {}
        self.summary_var = tk.StringVar(value="SSMB STATUS: UNKNOWN")
        self.trend_var_1 = tk.StringVar(value="eta")
        self.trend_var_2 = tk.StringVar(value="xi_x")
        self.raw_text = None
        self.fig = None
        self.ax_top = None
        self.ax_bottom = None
        self.canvas = None
        self._build()
        self.worker.start()
        self._tick()

    def _build(self):
        self.window.columnconfigure(0, weight=1)
        self.window.columnconfigure(1, weight=1)
        self.window.rowconfigure(1, weight=1)

        header = tk.Frame(self.window)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        tk.Label(header, textvariable=self.summary_var, font=("Helvetica", 14, "bold")).pack(side="left")

        left = tk.Frame(self.window)
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        right = tk.Frame(self.window)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_status_table(left)
        self._build_raw_panel(left)
        self._build_plot_panel(right)

    def _build_status_table(self, parent):
        frame = tk.LabelFrame(parent, text="SSMB diagnostics")
        frame.grid(row=0, column=0, sticky="ew")
        rows = [
            ("η", "eta"),
            ("α0", "alpha0"),
            ("RF PV", "rf_pv"),
            ("Qs", "tune_s"),
            ("f_s [kHz]", "tune_s_khz"),
            ("Qx", "tune_x"),
            ("Qy", "tune_y"),
            ("dQx-res", "resonance_dx"),
            ("dQy-res", "resonance_dy"),
            ("corr(Qx,Qs)", "coupling_xs"),
            ("corr(Qy,Qs)", "coupling_ys"),
            ("ξx", "xi_x"),
            ("ξy", "xi_y"),
            ("ξs", "xi_s"),
            ("U125/1", "u125_1"),
            ("τcalc", "lifetime_calc"),
            ("τ10h", "lifetime_10h"),
            ("τ100h", "lifetime_100h"),
            ("σx QPD1", "sigma_x_1"),
            ("σy QPD1", "sigma_y_1"),
            ("RF jitter", "rf_jitter"),
            ("Qx jitter", "tune_x_jitter"),
            ("Qy jitter", "tune_y_jitter"),
            ("Qs jitter", "tune_s_jitter"),
            ("Feedback", "feedback"),
        ]
        for row_index, (label_text, key) in enumerate(rows):
            tk.Label(frame, text=label_text, anchor="w", width=12).grid(row=row_index, column=0, sticky="ew", padx=4, pady=2)
            value_label = tk.Label(frame, text="UNKNOWN", anchor="w", width=18)
            value_label.grid(row=row_index, column=1, sticky="ew", padx=4, pady=2)
            state_label = tk.Label(frame, text="UNKNOWN", anchor="center", width=10, bg=SEVERITY_COLORS["UNKNOWN"])
            state_label.grid(row=row_index, column=2, sticky="ew", padx=4, pady=2)
            self.row_labels[key] = {"value": value_label, "state": state_label}

        self.diagnostics_text = tk.Text(frame, height=8, width=50, wrap="word")
        self.diagnostics_text.grid(row=len(rows), column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 4))

    def _build_raw_panel(self, parent):
        frame = tk.LabelFrame(parent, text="Raw / interpreted values")
        frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.raw_text = tk.Text(frame, height=18, width=58, wrap="none")
        raw_scroll = tk.Scrollbar(frame, command=self.raw_text.yview)
        self.raw_text.configure(yscrollcommand=raw_scroll.set)
        self.raw_text.grid(row=0, column=0, sticky="nsew")
        raw_scroll.grid(row=0, column=1, sticky="ns")

    def _build_plot_panel(self, parent):
        controls = tk.LabelFrame(parent, text="Live trends")
        controls.grid(row=0, column=0, sticky="ew")
        labels = {key: text for key, text in TREND_CHOICES}
        tk.Label(controls, text="Top trend").grid(row=0, column=0, padx=4, pady=4)
        tk.Label(controls, text="Bottom trend").grid(row=1, column=0, padx=4, pady=4)
        if ttk is not None:
            ttk.Combobox(
                controls,
                textvariable=self.trend_var_1,
                values=[key for key, _text in TREND_CHOICES],
                width=18,
                state="readonly",
            ).grid(row=0, column=1, padx=4, pady=4)
            ttk.Combobox(
                controls,
                textvariable=self.trend_var_2,
                values=[key for key, _text in TREND_CHOICES],
                width=18,
                state="readonly",
            ).grid(row=1, column=1, padx=4, pady=4)
        else:
            tk.OptionMenu(controls, self.trend_var_1, *labels.keys()).grid(row=0, column=1, padx=4, pady=4)
            tk.OptionMenu(controls, self.trend_var_2, *labels.keys()).grid(row=1, column=1, padx=4, pady=4)

        plot_frame = tk.LabelFrame(parent, text="History")
        plot_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        if MATPLOTLIB_AVAILABLE:
            self.fig = Figure(figsize=(5.5, 5.5))
            self.ax_top = self.fig.add_subplot(211)
            self.ax_bottom = self.fig.add_subplot(212)
            self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
            self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        else:
            tk.Label(plot_frame, text="matplotlib unavailable; live trend plots are disabled.").grid(
                row=0, column=0, sticky="w", padx=8, pady=8
            )

    def _tick(self):
        if not self.window.winfo_exists():
            return
        while True:
            try:
                self.current_sample = self.result_queue.get_nowait()
            except queue.Empty:
                break
            self.history.append(self.current_sample)
        if self.current_sample is not None:
            self._render(self.current_sample)
        self.window.after(500, self._tick)

    def _set_row(self, key: str, value_text: str, severity: str):
        row = self.row_labels[key]
        row["value"].config(text=value_text)
        row["state"].config(text=severity, bg=SEVERITY_COLORS.get(severity, SEVERITY_COLORS["UNKNOWN"]))

    def _xi_state(self, value: Optional[float]) -> str:
        if value is None:
            return "UNKNOWN"
        absolute = abs(value)
        if absolute < STATUS_THRESHOLDS["xi"]["green"]:
            return "GREEN"
        if absolute < STATUS_THRESHOLDS["xi"]["yellow"]:
            return "YELLOW"
        return "RED"

    def _feedback_state(self, sample: MonitorSample) -> str:
        if None in (sample.feedback_x, sample.feedback_y, sample.feedback_s):
            return "UNKNOWN"
        if (sample.feedback_x, sample.feedback_y, sample.feedback_s) == (1.0, 1.0, 1.0):
            return "GREEN"
        return "YELLOW"

    def _lifetime_state(self, value: Optional[float]) -> str:
        if value is None:
            return "UNKNOWN"
        if value > STATUS_THRESHOLDS["lifetime"]["green"]:
            return "GREEN"
        if value > STATUS_THRESHOLDS["lifetime"]["yellow"]:
            return "YELLOW"
        return "RED"

    def _resonance_state(self, distance: Optional[float]) -> str:
        if distance is None:
            return "UNKNOWN"
        if distance > STATUS_THRESHOLDS["resonance_distance"]["green"]:
            return "GREEN"
        if distance > STATUS_THRESHOLDS["resonance_distance"]["yellow"]:
            return "YELLOW"
        return "RED"

    def _render(self, sample: MonitorSample):
        eta_state = _severity_from_thresholds(sample.eta, STATUS_THRESHOLDS["eta"]["green"], STATUS_THRESHOLDS["eta"]["yellow"])
        alpha0_state = (
            "GREEN"
            if sample.alpha0 is not None
            and STATUS_THRESHOLDS["alpha0_low"]["green_min"] < sample.alpha0 < STATUS_THRESHOLDS["alpha0_low"]["green_max"]
            else "YELLOW"
        )
        qx_state = _severity_from_thresholds(sample.tune_x_jitter, STATUS_THRESHOLDS["tune_jitter_xy"]["green"], STATUS_THRESHOLDS["tune_jitter_xy"]["yellow"])
        qy_state = _severity_from_thresholds(sample.tune_y_jitter, STATUS_THRESHOLDS["tune_jitter_xy"]["green"], STATUS_THRESHOLDS["tune_jitter_xy"]["yellow"])
        qs_state = _severity_from_thresholds(sample.tune_s_jitter, STATUS_THRESHOLDS["tune_jitter_s"]["green"], STATUS_THRESHOLDS["tune_jitter_s"]["yellow"])
        rf_state = _severity_from_thresholds(sample.rf_jitter, STATUS_THRESHOLDS["rf_jitter"]["green"], STATUS_THRESHOLDS["rf_jitter"]["yellow"])
        feedback_state = self._feedback_state(sample)
        resonance_x_state = self._resonance_state(sample.resonance_dx)
        resonance_y_state = self._resonance_state(sample.resonance_dy)
        lifetime_state = self._lifetime_state(sample.lifetime_calc)
        coupling_x_state = _severity_from_thresholds(sample.coupling_xs, STATUS_THRESHOLDS["coupling_corr"]["green"], STATUS_THRESHOLDS["coupling_corr"]["yellow"])
        coupling_y_state = _severity_from_thresholds(sample.coupling_ys, STATUS_THRESHOLDS["coupling_corr"]["green"], STATUS_THRESHOLDS["coupling_corr"]["yellow"])

        severities = [
            eta_state,
            alpha0_state,
            qx_state,
            qy_state,
            qs_state,
            rf_state,
            resonance_x_state,
            resonance_y_state,
            coupling_x_state,
            coupling_y_state,
            lifetime_state,
        ]
        score = max(0, 100 - 20 * severities.count("RED") - 8 * severities.count("YELLOW"))
        if score >= 80:
            status = "OK"
        elif score >= 55:
            status = "MARGINAL"
        else:
            status = "FAIL"
        self.summary_var.set("SSMB STATUS: %s    score=%d" % (status, score))

        self._set_row("eta", "%.6e" % sample.eta if sample.eta is not None else "UNKNOWN", eta_state)
        self._set_row("alpha0", "%.8f" % sample.alpha0 if sample.alpha0 is not None else "UNKNOWN", alpha0_state)
        self._set_row("rf_pv", "%.6f" % sample.rf_pv if sample.rf_pv is not None else "UNKNOWN", "INFO")
        self._set_row("tune_s", "%.6f" % sample.tune_s if sample.tune_s is not None else "UNKNOWN", qs_state)
        self._set_row("tune_s_khz", "%.6f" % sample.tune_s_khz if sample.tune_s_khz is not None else "UNKNOWN", qs_state)
        self._set_row("tune_x", "%.6f" % sample.tune_x if sample.tune_x is not None else "UNKNOWN", qx_state)
        self._set_row("tune_y", "%.6f" % sample.tune_y if sample.tune_y is not None else "UNKNOWN", qy_state)
        self._set_row("resonance_dx", "%.5f" % sample.resonance_dx if sample.resonance_dx is not None else "UNKNOWN", resonance_x_state)
        self._set_row("resonance_dy", "%.5f" % sample.resonance_dy if sample.resonance_dy is not None else "UNKNOWN", resonance_y_state)
        self._set_row("coupling_xs", "%.3f" % sample.coupling_xs if sample.coupling_xs is not None else "UNKNOWN", coupling_x_state)
        self._set_row("coupling_ys", "%.3f" % sample.coupling_ys if sample.coupling_ys is not None else "UNKNOWN", coupling_y_state)
        self._set_row("xi_x", "%.4f" % sample.xi_x if sample.xi_x is not None else "UNKNOWN", self._xi_state(sample.xi_x))
        self._set_row("xi_y", "%.4f" % sample.xi_y if sample.xi_y is not None else "UNKNOWN", self._xi_state(sample.xi_y))
        self._set_row("xi_s", "%.4f" % sample.xi_s if sample.xi_s is not None else "UNKNOWN", self._xi_state(sample.xi_s))
        self._set_row("u125_1", "%.4f" % sample.u125_1 if sample.u125_1 is not None else "UNKNOWN", "INFO")
        self._set_row("lifetime_calc", "%.4f" % sample.lifetime_calc if sample.lifetime_calc is not None else "UNKNOWN", lifetime_state)
        self._set_row("lifetime_10h", "%.4f" % sample.lifetime_10h if sample.lifetime_10h is not None else "UNKNOWN", self._lifetime_state(sample.lifetime_10h))
        self._set_row("lifetime_100h", "%.4f" % sample.lifetime_100h if sample.lifetime_100h is not None else "UNKNOWN", self._lifetime_state(sample.lifetime_100h))
        self._set_row("sigma_x_1", "%.3f" % sample.sigma_x_1 if sample.sigma_x_1 is not None else "UNKNOWN", "INFO")
        self._set_row("sigma_y_1", "%.3f" % sample.sigma_y_1 if sample.sigma_y_1 is not None else "UNKNOWN", "INFO")
        self._set_row("rf_jitter", "%.6f" % sample.rf_jitter if sample.rf_jitter is not None else "UNKNOWN", rf_state)
        self._set_row("tune_x_jitter", "%.6e" % sample.tune_x_jitter if sample.tune_x_jitter is not None else "UNKNOWN", qx_state)
        self._set_row("tune_y_jitter", "%.6e" % sample.tune_y_jitter if sample.tune_y_jitter is not None else "UNKNOWN", qy_state)
        self._set_row("tune_s_jitter", "%.6e" % sample.tune_s_jitter if sample.tune_s_jitter is not None else "UNKNOWN", qs_state)
        self._set_row(
            "feedback",
            "%s/%s/%s" % (sample.feedback_x, sample.feedback_y, sample.feedback_s),
            feedback_state,
        )

        raw_lines = [
            "RF PV               %r" % sample.rf_pv,
            "Qx raw              %r" % sample.tune_x_raw,
            "Qx [kHz]            %r" % sample.tune_x_khz,
            "Qx                  %r" % sample.tune_x,
            "Qy raw              %r" % sample.tune_y_raw,
            "Qy [kHz]            %r" % sample.tune_y_khz,
            "Qy                  %r" % sample.tune_y,
            "tuneSyn raw         %r" % sample.tune_s_raw,
            "f_s [kHz]           %r" % sample.tune_s_khz,
            "Qs                  %r" % sample.tune_s,
            "Ucav [kV]           %r" % sample.cavity_voltage_kv,
            "E [MeV]             %r" % sample.beam_energy_mev,
            "Beam current        %r" % sample.beam_current,
            "White noise         %r" % sample.white_noise,
            "Optics mode         %r" % sample.optics_mode,
            "U125/1             %r" % sample.u125_1,
            "Lifetime 10h        %r" % sample.lifetime_10h,
            "Lifetime 100h       %r" % sample.lifetime_100h,
            "Lifetime calc       %r" % sample.lifetime_calc,
            "QPD1 sigma x        %r" % sample.sigma_x_1,
            "QPD1 sigma y        %r" % sample.sigma_y_1,
            "QPD0 sigma x        %r" % sample.sigma_x_0,
            "QPD0 sigma y        %r" % sample.sigma_y_0,
        ]
        self.raw_text.delete("1.0", tk.END)
        self.raw_text.insert("1.0", "\n".join(raw_lines))

        issues = self._inferred_faults(sample)
        self.diagnostics_text.delete("1.0", tk.END)
        self.diagnostics_text.insert("1.0", "\n".join(issues))
        self._update_plots()

    def _inferred_faults(self, sample: MonitorSample) -> List[str]:
        issues = []
        if sample.eta is not None and abs(sample.eta) > STATUS_THRESHOLDS["eta"]["yellow"]:
            issues.append("- |η| is too large for comfortable SSMB operation")
        if sample.alpha0 is not None and sample.alpha0 > 1e-3:
            issues.append("- α0 is above the usual low-alpha SSMB regime")
        if sample.tune_s_jitter is not None and sample.tune_s_jitter > STATUS_THRESHOLDS["tune_jitter_s"]["yellow"]:
            issues.append("- synchrotron tune jitter is high")
        if sample.resonance_dx is not None and sample.resonance_dx < STATUS_THRESHOLDS["resonance_distance"]["yellow"]:
            issues.append("- Qx is very close to an integer / half-integer resonance")
        if sample.resonance_dy is not None and sample.resonance_dy < STATUS_THRESHOLDS["resonance_distance"]["yellow"]:
            issues.append("- Qy is very close to an integer / half-integer resonance")
        if sample.rf_jitter is not None and sample.rf_jitter > STATUS_THRESHOLDS["rf_jitter"]["yellow"]:
            issues.append("- RF readback jitter is high")
        if sample.xi_x is not None and abs(sample.xi_x) > STATUS_THRESHOLDS["xi"]["yellow"]:
            issues.append("- horizontal chromaticity is far from zero")
        if sample.xi_y is not None and abs(sample.xi_y) > STATUS_THRESHOLDS["xi"]["yellow"]:
            issues.append("- vertical chromaticity is far from zero")
        if sample.lifetime_calc is not None and sample.lifetime_calc < STATUS_THRESHOLDS["lifetime"]["yellow"]:
            issues.append("- calculated beam lifetime is low")
        if sample.coupling_xs is not None and abs(sample.coupling_xs) > STATUS_THRESHOLDS["coupling_corr"]["yellow"]:
            issues.append("- rolling Qx/Qs correlation is high; check transverse-longitudinal coupling or common RF drive")
        if sample.coupling_ys is not None and abs(sample.coupling_ys) > STATUS_THRESHOLDS["coupling_corr"]["yellow"]:
            issues.append("- rolling Qy/Qs correlation is high; check transverse-longitudinal coupling or common RF drive")
        if sample.feedback_x == 0.0 or sample.feedback_y == 0.0 or sample.feedback_s == 0.0:
            issues.append("- one or more feedback loops are disabled")
        if not issues:
            issues.append("- no immediate SSMB red flags from current readbacks")
        return issues

    def _series(self, key: str):
        values = []
        for sample in self.history:
            values.append(getattr(sample, key, None))
        return values

    def _plot_metric(self, axis, key: str):
        axis.clear()
        if not self.history:
            axis.set_title("No data yet")
            return
        xs = [sample.timestamp - self.history[0].timestamp for sample in self.history]
        ys = [value for value in self._series(key)]
        filtered = [(x, y) for x, y in zip(xs, ys) if y is not None]
        title_lookup = dict(TREND_CHOICES)
        if not filtered:
            axis.set_title("%s (no data)" % title_lookup.get(key, key))
            return
        x_vals = [item[0] for item in filtered]
        y_vals = [item[1] for item in filtered]
        axis.plot(x_vals, y_vals, "b-", linewidth=1.6)
        axis.set_title(title_lookup.get(key, key))
        axis.set_xlabel("Time [s]")
        axis.grid(True, alpha=0.3)

    def _update_plots(self):
        if not MATPLOTLIB_AVAILABLE or self.fig is None:
            return
        self._plot_metric(self.ax_top, self.trend_var_1.get())
        self._plot_metric(self.ax_bottom, self.trend_var_2.get())
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def close(self):
        self.stop_event.set()
        self.window.destroy()


def open_window(master, state):
    return SSMBMonitorWindow(master, state)
