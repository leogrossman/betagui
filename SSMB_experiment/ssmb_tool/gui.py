from __future__ import annotations

import argparse
import collections
import json
import math
import os
import queue
import signal
import shutil
import threading
import time
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from .config import LoggerConfig, SSMB_ROOT, parse_labeled_pvs
from .epics_io import EpicsAdapter, EpicsUnavailableError, ReadOnlyEpicsAdapter
from .inventory import spec_index
from .lattice import LatticeElement
from .live_monitor import (
    build_monitor_sections,
    build_theory_sections,
    format_channel_snapshot,
    format_monitor_summary,
    format_oscillation_study,
    summarize_live_monitor,
    trend_definitions,
)
from .log_now import BPM_NONLINEAR_MM, BPM_WARNING_MM, build_specs, estimate_passive_session_bytes, estimate_sample_breakdown, inventory_overview_lines, run_stage0_logger
from .sweep import RF_PV_NAME, SweepRuntimeConfig, build_plan_from_hz, estimate_sweep_session_bytes, preview_lines, run_rf_sweep_session

try:  # pragma: no cover - depends on host GUI packages
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on host GUI packages
    tk = None
    filedialog = None
    messagebox = None
    ttk = None


HISTORY_TAIL_READ_BYTES = 2 * 1024 * 1024
HISTORY_COMPACT_BYTES = 8 * 1024 * 1024
LIVE_MONITOR_EXCLUDED_TAGS = {"ring", "quadrupole", "sextupole", "octupole"}
LIVE_MONITOR_PLOT_WINDOW_S = 60.0
DETAIL_PLOT_WINDOW_S = 60.0
LONG_STUDY_PLOT_WINDOW_S = 600.0
DEFAULT_PLOT_MAX_POINTS = 320
LONG_STUDY_PLOT_MAX_POINTS = 480
MONITOR_DASHBOARD_RENDER_MIN_S = 1.0
MONITOR_WINDOW_RENDER_MIN_S = 1.0
MONITOR_WINDOW_REFRESH_MS = 2000


def _parse_text_mapping(text: str) -> dict[str, str]:
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return parse_labeled_pvs(items)


def _filter_live_monitor_specs(specs, extra_labels: Sequence[str]):
    selected = set(extra_labels or ())
    filtered = []
    for spec in specs:
        if spec.label in selected:
            filtered.append(spec)
            continue
        if spec.kind == "waveform":
            continue
        if any(tag in LIVE_MONITOR_EXCLUDED_TAGS for tag in (spec.tags or ())):
            continue
        filtered.append(spec)
    return filtered


def _downsample_tail(values, max_points: int):
    if max_points <= 0 or len(values) <= max_points:
        return list(values)
    step = max(1, int(math.ceil(len(values) / float(max_points))))
    sampled = list(values[::step])
    if sampled[-1] != values[-1]:
        sampled.append(values[-1])
    return sampled


class SSMBGui:
    def __init__(self, root: "tk.Tk", allow_writes: bool = True, start_safe_mode: bool = True):
        self.root = root
        self.allow_writes = allow_writes
        self.start_safe_mode = start_safe_mode
        self.queue: "queue.Queue[object]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_stop_event: Optional[threading.Event] = None
        self.monitor_history = collections.deque(maxlen=2400)
        self._monitor_message_lock = threading.Lock()
        self._pending_monitor_payload = None
        self._monitor_update_queued = False
        self._pending_dashboard_summary = None
        self._dashboard_render_scheduled = False
        self._last_dashboard_render_monotonic = 0.0
        self.monitor_window: Optional["tk.Toplevel"] = None
        self.monitor_dashboard_sections = []
        self.monitor_active_section_key = None
        self._monitor_window_auto_refresh_job = None
        self._updating_monitor_section_tree = False
        self._updating_monitor_plot_selector = False
        self.theory_window: Optional["tk.Toplevel"] = None
        self.oscillation_window: Optional["tk.Toplevel"] = None
        self.lattice_window: Optional["tk.Toplevel"] = None
        self.bump_lab_window: Optional["tk.Toplevel"] = None
        self.ssmb_study_window: Optional["tk.Toplevel"] = None
        self.bump_lab_thread: Optional[threading.Thread] = None
        self.bump_lab_stop_event: Optional[threading.Event] = None
        self.lattice_context = None
        self.lattice_specs = None
        self.latest_monitor_sample = None
        self.latest_monitor_summary = None
        self.lattice_device_items = []
        self.selected_lattice_item_name = None
        self.live_spec_lookup = {}
        self.bump_lab_plot_canvases = {}
        self.ssmb_study_canvases = []
        self.oscillation_selected_candidate_key = None
        self.stage0_stop_event: Optional[threading.Event] = None
        self._monitor_cache_append_count = 0
        self._shutdown_started = False
        self._build_vars()
        self._build_ui()
        self._apply_profile()
        self._refresh_inventory()
        self.root.after(50, self._finish_startup)
        self.root.after(100, self._drain_queue)
        self.root.after(250, self._signal_heartbeat)

    def _finish_startup(self) -> None:
        self._debug("startup: loading cached monitor history")
        self._load_monitor_history_cache()
        try:
            self._place_window_on_screen(self.root, 1380, 900, x=50, y=50)
            self.root.deiconify()
            self.root.update_idletasks()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(600, lambda: self._clear_topmost(self.root))
            self.root.focus_force()
        except Exception as exc:
            self._debug("root focus/lift failed: %s" % exc)
        try:
            self._debug(
                "startup: root geometry=%s state=%s mapped=%s screen=%sx%s vroot=(%s,%s %sx%s)"
                % (
                    self.root.winfo_geometry(),
                    self.root.state(),
                    self.root.winfo_ismapped(),
                    self.root.winfo_screenwidth(),
                    self.root.winfo_screenheight(),
                    self.root.winfo_vrootx(),
                    self.root.winfo_vrooty(),
                    self.root.winfo_vrootwidth(),
                    self.root.winfo_vrootheight(),
                )
            )
        except Exception:
            pass
        self._debug("startup: gui ready (open popups from main window as needed)")

    def _clear_topmost(self, window) -> None:
        try:
            if window is not None and window.winfo_exists():
                window.attributes("-topmost", False)
        except Exception:
            pass

    def _signal_heartbeat(self) -> None:
        try:
            if self.root is None or not self.root.winfo_exists():
                return
            self.root.after(250, self._signal_heartbeat)
        except Exception:
            return

    def _place_window_on_screen(self, window, width: int, height: int, x: Optional[int] = None, y: Optional[int] = None, relative_to_root: bool = False) -> None:
        try:
            if relative_to_root and self.root is not None and self.root.winfo_exists():
                self.root.update_idletasks()
                base_x = int(self.root.winfo_x())
                base_y = int(self.root.winfo_y())
                pos_x = base_x + (x if x is not None else 60)
                pos_y = base_y + (y if y is not None else 60)
            else:
                pos_x = 50 if x is None else int(x)
                pos_y = 50 if y is None else int(y)
            pos_x = max(0, pos_x)
            pos_y = max(0, pos_y)
            window.geometry("%dx%d+%d+%d" % (int(width), int(height), pos_x, pos_y))
        except Exception as exc:
            self._debug("window placement failed: %s" % exc)

    def _build_vars(self) -> None:
        self.duration_var = tk.StringVar(value="60")
        self.sample_hz_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="0.5")
        self.label_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
        self.laser_shots_var = tk.StringVar(value="0")
        self.output_dir_var = tk.StringVar(value=str(SSMB_ROOT / ".ssmb_local" / "ssmb_stage0"))
        self.include_bpm_buffer_var = tk.BooleanVar(value=True)
        self.include_candidate_bpm_var = tk.BooleanVar(value=True)
        self.include_ring_bpm_var = tk.BooleanVar(value=True)
        self.include_quadrupole_var = tk.BooleanVar(value=False)
        self.include_sextupole_var = tk.BooleanVar(value=True)
        self.include_octupole_var = tk.BooleanVar(value=True)
        self.heavy_mode_var = tk.BooleanVar(value=False)
        self.safe_mode_var = tk.BooleanVar(value=self.start_safe_mode)
        self.log_profile_var = tk.StringVar(value="ssmb_standard")

        self.center_rf_var = tk.StringVar(value="")
        self.delta_min_hz_var = tk.StringVar(value="-100")
        self.delta_max_hz_var = tk.StringVar(value="100")
        self.points_var = tk.StringVar(value="5")
        self.settle_var = tk.StringVar(value="1.0")
        self.samples_per_point_var = tk.StringVar(value="1")
        self.sample_spacing_var = tk.StringVar(value="0.0")
        self.monitor_interval_var = tk.StringVar(value="0.5")
        self.monitor_history_span_var = tk.StringVar(value="600")
        self.rolling_window_var = tk.StringVar(value="120")
        self.monitor_log_scale_var = tk.BooleanVar(value=False)
        self.monitor_candidate_keys_var = tk.StringVar(value="")
        self.oscillation_ignore_rf_var = tk.BooleanVar(value=False)
        self.monitor_extra_labels_var = tk.StringVar(value="")
        self.bump_lab_poll_var = tk.StringVar(value="0.5")
        self.bump_lab_bpm_vars = {
            "BPMZ1K1RP:rdX": tk.BooleanVar(value=True),
            "BPMZ1L2RP:rdX": tk.BooleanVar(value=True),
            "BPMZ1K3RP:rdX": tk.BooleanVar(value=True),
            "BPMZ1L4RP:rdX": tk.BooleanVar(value=True),
        }
        self.bump_lab_steerer_vars = {
            "HS1P2K3RP:setCur": tk.StringVar(value="0.03226"),
            "HS3P1L4RP:setCur": tk.StringVar(value="0.014116"),
            "HS3P2L4RP:setCur": tk.StringVar(value="0.014123"),
            "HS1P1K1RP:setCur": tk.StringVar(value="0.031103"),
        }

    def _build_ui(self) -> None:
        self.root.title("SSMB Experiment Logger / RF Sweep")
        self.root.geometry("1380x900")

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        control = ttk.Frame(outer)
        control.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        safety_frame = ttk.Frame(control)
        safety_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(safety_frame, text="Machine Safety").pack(anchor="w")
        self.safe_mode_button = tk.Checkbutton(
            safety_frame,
            text="SAFE MODE ON",
            variable=self.safe_mode_var,
            indicatoron=False,
            onvalue=True,
            offvalue=False,
            bg="#2e7d32",
            fg="white",
            selectcolor="#2e7d32",
            activebackground="#388e3c",
            activeforeground="white",
            relief="raised",
            padx=12,
            pady=8,
            command=self._on_safe_mode_changed,
        )
        self.safe_mode_button.pack(fill="x")
        self.safe_mode_hint = ttk.Label(
            safety_frame,
            text="Writes are blocked. Turn this off explicitly before RF sweep or experimental bump control.",
            wraplength=340,
            justify="left",
        )
        self.safe_mode_hint.pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(control)
        self.control_notebook = notebook
        notebook.pack(fill="both", expand=False)

        monitor_frame = ttk.Frame(notebook, padding=8)
        logger_frame = ttk.Frame(notebook, padding=8)
        sweep_frame = ttk.Frame(notebook, padding=8)
        self.monitor_tab = monitor_frame
        self.logger_tab = logger_frame
        self.sweep_tab = sweep_frame
        notebook.add(monitor_frame, text="Live Monitor")
        notebook.add(logger_frame, text="Measurement Logger")
        notebook.add(sweep_frame, text="RF Sweep")

        self._build_monitor_tab(monitor_frame)
        self._build_logger_tab(logger_frame)
        self._build_sweep_tab(sweep_frame)
        self._update_safe_mode_visuals()

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=0)
        right.rowconfigure(5, weight=1)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Logged Channel Overview").grid(row=0, column=0, sticky="w")
        self.inventory_text = tk.Text(right, wrap="none", height=18)
        self.inventory_text.grid(row=1, column=0, sticky="nsew")
        self.inventory_text.configure(state="disabled")

        ttk.Label(right, text="BPM Nonlinearity Watch").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.bpm_status_text = tk.Text(right, wrap="none", height=10)
        self.bpm_status_text.grid(row=3, column=0, sticky="nsew")
        self.bpm_status_text.configure(state="disabled")
        self.bpm_status_text.tag_configure("green", foreground="#1b5e20")
        self.bpm_status_text.tag_configure("yellow", foreground="#8d6e00")
        self.bpm_status_text.tag_configure("red", foreground="#b71c1c")

        ttk.Label(right, text="Session / Run Log").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.log_text = tk.Text(right, wrap="word")
        self.log_text.grid(row=5, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _build_logger_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        for label, var in (
            ("Duration [s]", self.duration_var),
            ("Sample rate [Hz]", self.sample_hz_var),
            ("Timeout [s]", self.timeout_var),
            ("Session label", self.label_var),
            ("Operator note", self.note_var),
            ("Laser shots / run", self.laser_shots_var),
            ("Output root", self.output_dir_var),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=var, width=42).grid(row=row, column=1, sticky="ew", pady=2)
            row += 1

        preset_row = ttk.Frame(frame)
        preset_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(preset_row, text="Preset: low-alpha full log", command=self._preset_low_alpha).pack(side="left")
        ttk.Button(preset_row, text="Preset: bump OFF", command=lambda: self._preset_bump("bump_off")).pack(side="left", padx=4)
        ttk.Button(preset_row, text="Preset: bump ON", command=lambda: self._preset_bump("bump_on")).pack(side="left")
        row += 1

        ttk.Label(frame, text="Logging profile").grid(row=row, column=0, sticky="w")
        profile_combo = ttk.Combobox(frame, textvariable=self.log_profile_var, values=("minimal", "ssmb_standard", "heavy"), width=18, state="readonly")
        profile_combo.grid(row=row, column=1, sticky="w", pady=2)
        profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_profile())
        row += 1

        ttk.Checkbutton(frame, text="Safe / read-only mode", variable=self.safe_mode_var, command=self._on_safe_mode_changed).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Checkbutton(frame, text="Heavy logging mode", variable=self.heavy_mode_var, command=self._toggle_heavy_mode).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include BPM buffer waveform", variable=self.include_bpm_buffer_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include U125/L4 candidate BPM scalars", variable=self.include_candidate_bpm_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include ring BPM scalars", variable=self.include_ring_bpm_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include quadrupole currents", variable=self.include_quadrupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include sextupole currents", variable=self.include_sextupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include octupoles", variable=self.include_octupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(frame, text="Extra required PVs (LABEL=PV)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        self.extra_pvs_text = tk.Text(frame, width=48, height=6)
        self.extra_pvs_text.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        ttk.Label(frame, text="Optional experiment PVs (LABEL=PV)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        self.optional_pvs_text = tk.Text(frame, width=48, height=6)
        self.optional_pvs_text.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(button_row, text="Preview Logged Channels", command=self._refresh_inventory).pack(side="left")
        ttk.Button(button_row, text="Run Measurement Log", command=self._run_stage0).pack(side="left", padx=6)
        self.start_manual_button = ttk.Button(button_row, text="Start Manual Log", command=self._start_manual_stage0)
        self.start_manual_button.pack(side="left")
        self.stop_manual_button = ttk.Button(button_row, text="Stop Manual Log", command=self._stop_manual_stage0)
        self.stop_manual_button.pack(side="left", padx=6)
        self.stop_manual_button.state(["disabled"])

    def _build_monitor_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        info = "Read-only live SSMB monitor. Use this before the experiment or during another operator's RF sweep to preview the same observables without saving data."
        ttk.Label(frame, text=info, wraplength=520, justify="left").grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 8))
        row += 1
        extra_row = ttk.Frame(frame)
        extra_row.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        ttk.Button(extra_row, text="Live Monitor Settings…", command=self._open_monitor_settings_window).pack(side="left")
        ttk.Label(
            extra_row,
            text="Sampling rate, rolling window, extra live channels, and extra oscillation candidates now live in the settings window so the main monitor tab stays uncluttered.",
            foreground="#607d8b",
            wraplength=680,
            justify="left",
        ).pack(side="left", padx=(8, 0))
        row += 1
        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 8))
        self.start_monitor_button = ttk.Button(button_row, text="Start Live Monitor", command=self._start_monitor)
        self.start_monitor_button.pack(side="left")
        self.stop_monitor_button = ttk.Button(button_row, text="Stop Live Monitor", command=self._stop_monitor)
        self.stop_monitor_button.pack(side="left", padx=6)
        self.stop_monitor_button.state(["disabled"])
        ttk.Button(button_row, text="Reset Monitor Baseline", command=self._reset_monitor_baseline).pack(side="left")
        ttk.Button(button_row, text="Open Monitor Window", command=self._open_monitor_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open Oscillation Study", command=self._open_oscillation_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open SSMB Study", command=self._open_ssmb_study_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open Theory Window", command=self._open_theory_window).pack(side="left", padx=6)
        self.monitor_jump_sweep_button = ttk.Button(button_row, text="Go To RF Sweep", command=self._focus_rf_sweep_tab)
        self.monitor_jump_sweep_button.pack(side="left", padx=6)
        ttk.Button(button_row, text="Open Lattice View", command=self._open_lattice_window).pack(side="left")
        ttk.Button(button_row, text="Open Experimental Bump Lab", command=self._open_bump_lab_window).pack(side="left", padx=6)
        row += 1
        ttk.Label(frame, text="Live SSMB summary").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.monitor_summary_text = tk.Text(frame, wrap="word", height=18)
        self.monitor_summary_text.grid(row=row, column=0, columnspan=4, sticky="nsew")
        self.monitor_summary_text.configure(state="disabled")
        row += 1
        ttk.Label(frame, text="Current channel snapshot").grid(row=row, column=0, columnspan=4, sticky="w", pady=(8, 0))
        row += 1
        self.monitor_channels_text = tk.Text(frame, wrap="none", height=16)
        self.monitor_channels_text.grid(row=row, column=0, columnspan=4, sticky="nsew")
        self.monitor_channels_text.configure(state="disabled")
        frame.rowconfigure(row - 1, weight=1)
        frame.columnconfigure(3, weight=1)

    def _extra_oscillation_candidates(self) -> list[str]:
        raw = self.monitor_candidate_keys_var.get().strip()
        if not raw:
            return []
        seen = set()
        keys = []
        for item in raw.replace("\n", ",").split(","):
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        return keys

    def _extra_monitor_labels(self) -> list[str]:
        raw = self.monitor_extra_labels_var.get().strip()
        if not raw:
            return []
        seen = set()
        labels = []
        for item in raw.replace("\n", ",").split(","):
            label = item.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
        return labels

    def _monitor_history_path(self) -> Path:
        override = os.environ.get("SSMB_MONITOR_CACHE_DIR", "").strip()
        if override:
            root = Path(override).expanduser()
        else:
            root = Path(tempfile.gettempdir()) / "ssmb_experiment_live_monitor" / os.environ.get("USER", "unknown")
        return root / "history.jsonl"

    def _debug(self, message: str) -> None:
        print("[ssmb_gui] %s" % message, flush=True)

    def _monitor_history_span_seconds(self) -> float:
        try:
            return max(30.0, float(self.monitor_history_span_var.get()))
        except Exception:
            return 600.0

    def _monitor_interval_seconds(self) -> float:
        try:
            return max(0.01, float(self.monitor_interval_var.get()))
        except Exception:
            return 0.5

    def _window_samples_for_seconds(self, seconds: float) -> int:
        interval = self._monitor_interval_seconds()
        return max(10, int(math.ceil(max(interval, seconds) / interval)))

    def _prepare_plot_series(self, values, *, window_seconds: float, max_points: int):
        if not values:
            return []
        window_samples = self._window_samples_for_seconds(window_seconds)
        clipped = list(values[-window_samples:])
        return _downsample_tail(clipped, max_points)

    def _should_compute_extended_analysis(self) -> bool:
        for name in ("oscillation_window", "ssmb_study_window"):
            window = getattr(self, name, None)
            try:
                if window is not None and window.winfo_exists():
                    return True
            except Exception:
                continue
        return False

    def _trim_monitor_history(self) -> None:
        if not self.monitor_history:
            return
        span_s = self._monitor_history_span_seconds()
        latest_ts = None
        latest = self.monitor_history[-1]
        try:
            latest_ts = float(latest.get("timestamp_epoch_s"))
        except Exception:
            latest_ts = None
        if latest_ts is None:
            return
        cutoff = latest_ts - span_s
        while self.monitor_history:
            try:
                ts = float(self.monitor_history[0].get("timestamp_epoch_s"))
            except Exception:
                break
            if ts >= cutoff:
                break
            self.monitor_history.popleft()

    def _append_monitor_history_cache(self, sample: dict) -> None:
        if os.environ.get("SSMB_DISABLE_MONITOR_CACHE", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
            return
        path = self._monitor_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sample, ensure_ascii=True) + "\n")
        self._monitor_cache_append_count += 1
        if self._monitor_cache_append_count % 50 == 0:
            self._compact_monitor_history_cache_if_needed()

    def _compact_monitor_history_cache_if_needed(self) -> None:
        path = self._monitor_history_path()
        try:
            if not path.exists() or path.stat().st_size < HISTORY_COMPACT_BYTES:
                return
            with path.open("w", encoding="utf-8") as stream:
                for sample in self.monitor_history:
                    stream.write(json.dumps(sample, ensure_ascii=True) + "\n")
            self._debug("compacted live monitor cache to %d recent samples" % len(self.monitor_history))
        except Exception as exc:
            self._debug("monitor history cache compaction failed: %s" % exc)

    def _load_monitor_history_cache(self) -> None:
        path = self._monitor_history_path()
        if os.environ.get("SSMB_DISABLE_MONITOR_CACHE", "").strip() in ("1", "true", "TRUE", "yes", "YES"):
            self._debug("live monitor cache disabled by environment")
            return
        if not path.exists():
            return
        now = time.time()
        cutoff = now - self._monitor_history_span_seconds()
        try:
            size = path.stat().st_size
            read_size = min(size, HISTORY_TAIL_READ_BYTES)
            with path.open("rb") as stream:
                if size > read_size:
                    stream.seek(-read_size, os.SEEK_END)
                blob = stream.read()
            if not blob:
                return
            text = blob.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            if size > read_size and lines:
                lines = lines[1:]
            kept = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                try:
                    ts = float(payload.get("timestamp_epoch_s"))
                except Exception:
                    ts = None
                if ts is not None and ts < cutoff:
                    continue
                self.monitor_history.append(payload)
                kept += 1
            self._debug("loaded %d cached live-monitor samples from %s" % (kept, path))
        except Exception as exc:
            self._debug("monitor history cache load failed: %s" % exc)
            return

    def _build_live_specs(self) -> None:
        try:
            _lattice, specs = self._build_monitor_specs()
        except Exception:
            return
        self.live_spec_lookup = spec_index(specs)

    def _build_monitor_specs(self):
        config = self._collect_logger_config(allow_writes=False)
        _lattice, specs = build_specs(config)
        return _lattice, _filter_live_monitor_specs(specs, self._extra_monitor_labels())

    def _open_candidate_picker(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Choose Oscillation Candidates")
        self._place_window_on_screen(window, 420, 520, x=100, y=100, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text="Select extra trend keys to include in the oscillation study").grid(row=0, column=0, sticky="w")
        listbox = tk.Listbox(frame, selectmode="multiple", exportselection=False)
        listbox.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        current = set(self._extra_oscillation_candidates())
        keys = sorted(trend_definitions().keys())
        for idx, key in enumerate(keys):
            meta = trend_definitions().get(key, {})
            listbox.insert("end", "%s  |  %s" % (key, meta.get("label", key)))
            if key in current:
                listbox.selection_set(idx)
        def apply_selection():
            selected = [keys[index] for index in listbox.curselection()]
            self.monitor_candidate_keys_var.set(", ".join(selected))
            window.destroy()
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Apply", command=apply_selection).pack(side="left")
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def _open_monitor_settings_window(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Live Monitor Settings")
        self._place_window_on_screen(window, 1100, 760, x=90, y=90, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)
        monitor_interval_var = tk.StringVar(value=self.monitor_interval_var.get())
        monitor_history_span_var = tk.StringVar(value=self.monitor_history_span_var.get())
        ttk.Label(controls, text="Monitor interval [s]").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=monitor_interval_var, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(controls, text="History span [s]").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(controls, textvariable=monitor_history_span_var, width=12).grid(row=0, column=3, sticky="w")
        ttk.Label(
            controls,
            text="The live monitor uses a lean default PV subset for responsiveness. Use this window to tune rate/span and promote extra channels into the live analysis context when you need extra lattice/debug detail.",
            wraplength=680,
            justify="left",
            foreground="#607d8b",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        current_config = self._collect_logger_config(allow_writes=False)
        _lattice, all_specs = build_specs(current_config)
        specs = _filter_live_monitor_specs(all_specs, self._extra_monitor_labels())
        labels = [spec.label for spec in specs if spec.pv]
        selected_now = set(self._extra_monitor_labels())

        ttk.Label(frame, text="Live monitor channel table").grid(row=2, column=0, sticky="w", pady=(10, 4))
        picker = ttk.Frame(frame)
        picker.grid(row=3, column=0, sticky="nsew")
        picker.columnconfigure(0, weight=1)
        picker.rowconfigure(0, weight=1)
        current_selected = set(selected_now)
        table = ttk.Treeview(
            picker,
            columns=("use", "label", "unit", "pv", "tags", "notes"),
            show="headings",
            height=18,
            selectmode="extended",
        )
        for col, title, width in (
            ("use", "Use", 55),
            ("label", "Label", 180),
            ("unit", "Unit", 70),
            ("pv", "PV", 240),
            ("tags", "Tags", 160),
            ("notes", "Notes / used for", 320),
        ):
            table.heading(col, text=title)
            table.column(col, width=width, anchor="w")
        table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(picker, orient="vertical", command=table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        table.configure(yscrollcommand=scroll.set)
        spec_map = {spec.label: spec for spec in all_specs if spec.pv}
        all_labels = [spec.label for spec in all_specs if spec.pv]
        for label in all_labels:
            spec = spec_map[label]
            use = "[x]" if label in current_selected else "[ ]"
            table.insert(
                "",
                "end",
                iid=label,
                values=(use, label, spec.unit or "", spec.pv or "", ", ".join(spec.tags or ()), spec.notes or ""),
            )
            if label in current_selected:
                table.selection_add(label)

        def sync_selection(_event=None):
            chosen = set(table.selection())
            for label in all_labels:
                current_use = "[x]" if label in chosen else "[ ]"
                table.set(label, "use", current_use)

        table.bind("<<TreeviewSelect>>", sync_selection)
        def toggle_row(event):
            row_id = table.identify_row(event.y)
            if not row_id:
                return
            current = set(table.selection())
            if row_id in current:
                current.remove(row_id)
            else:
                current.add(row_id)
            table.selection_set(tuple(current))
            sync_selection()
            return "break"
        table.bind("<Double-1>", toggle_row)

        summary_text = tk.Text(frame, wrap="word", height=8)
        summary_text.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        summary_text.configure(state="disabled")
        approx_bytes = int((self.latest_monitor_summary or {}).get("monitor_health", {}).get("approx_memory_bytes") or 0)
        self._set_text_widget(
            summary_text,
            [
                "Current monitor health",
                "",
                "Approximate live-history memory: %.2f MB" % (approx_bytes / (1024.0 * 1024.0)),
                "Central sample buffer length: %d" % len(self.monitor_history),
                "Current history span target: %s s" % self.monitor_history_span_var.get(),
                "Tip: add extra BPM labels here if you want them to appear in oscillation-study candidate picking and to keep them handy for live lattice inspection.",
            ],
        )

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, sticky="ew", pady=(10, 0))

        def apply_settings():
            self.monitor_interval_var.set(monitor_interval_var.get().strip() or self.monitor_interval_var.get())
            self.monitor_history_span_var.set(monitor_history_span_var.get().strip() or self.monitor_history_span_var.get())
            try:
                interval = max(0.01, float(self.monitor_interval_var.get()))
                self.rolling_window_var.set(str(max(10, int(math.ceil(LIVE_MONITOR_PLOT_WINDOW_S / interval)))))
            except Exception:
                pass
            selected = list(table.selection())
            self.monitor_extra_labels_var.set(", ".join(selected))
            window.destroy()
            self._update_monitor_dashboard(self.latest_monitor_summary)
            self._update_oscillation_window(self.latest_monitor_summary)

        ttk.Button(button_row, text="Apply", command=apply_settings).pack(side="left")
        ttk.Button(button_row, text="Close", command=window.destroy).pack(side="right")

    def _build_sweep_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        info = "Direct RF sweep in Hz around the current or entered RF PV value. The program starts with writes blocked, and RF writes only become available after you turn off Safe / read-only mode in the GUI."
        ttk.Label(frame, text=info, wraplength=360, justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        preset_row = ttk.Frame(frame)
        preset_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(preset_row, text="Preset: sweep bump OFF", command=lambda: self._preset_sweep("rf_sweep_bump_off")).pack(side="left")
        ttk.Button(preset_row, text="Preset: sweep bump ON", command=lambda: self._preset_sweep("rf_sweep_bump_on")).pack(side="left", padx=4)
        row += 1
        for label, var in (
            ("Center RF PV value", self.center_rf_var),
            ("Delta min [Hz]", self.delta_min_hz_var),
            ("Delta max [Hz]", self.delta_max_hz_var),
            ("Point count", self.points_var),
            ("Settle time [s]", self.settle_var),
            ("Samples per point", self.samples_per_point_var),
            ("Sample spacing [s]", self.sample_spacing_var),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=var, width=24).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

        sweep_buttons = ttk.Frame(frame)
        sweep_buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(sweep_buttons, text="Read Live RF", command=self._read_live_rf).pack(side="left")
        ttk.Button(sweep_buttons, text="Preview RF Sweep", command=self._preview_sweep).pack(side="left", padx=6)
        self.run_sweep_button = ttk.Button(sweep_buttons, text="Run RF Sweep", command=self._run_sweep)
        self.run_sweep_button.pack(side="left")
        self._update_write_controls()

    def _collect_logger_config(self, allow_writes: bool = False) -> LoggerConfig:
        safe_mode = bool(self.safe_mode_var.get()) if allow_writes else True
        write_enabled = bool(allow_writes and self.allow_writes and not safe_mode)
        return LoggerConfig(
            duration_seconds=float(self.duration_var.get()),
            sample_hz=float(self.sample_hz_var.get()),
            timeout_seconds=float(self.timeout_var.get()),
            output_root=Path(self.output_dir_var.get()).expanduser().resolve(),
            safe_mode=safe_mode,
            allow_writes=write_enabled,
            include_bpm_buffer=bool(self.include_bpm_buffer_var.get()),
            include_candidate_bpm_scalars=bool(self.include_candidate_bpm_var.get()),
            include_ring_bpm_scalars=bool(self.include_ring_bpm_var.get()),
            include_quadrupoles=bool(self.include_quadrupole_var.get()),
            include_sextupoles=bool(self.include_sextupole_var.get()),
            include_octupoles=bool(self.include_octupole_var.get()),
            session_label=self.label_var.get().strip(),
            operator_note=self.note_var.get().strip(),
            laser_shots_per_run=max(0, int(float(self.laser_shots_var.get() or "0"))),
            extra_pvs=_parse_text_mapping(self.extra_pvs_text.get("1.0", "end")),
            extra_optional_pvs=_parse_text_mapping(self.optional_pvs_text.get("1.0", "end")),
        )

    def _apply_profile(self) -> None:
        profile = self.log_profile_var.get()
        if profile == "minimal":
            self.heavy_mode_var.set(False)
            self.include_bpm_buffer_var.set(False)
            self.include_candidate_bpm_var.set(True)
            self.include_ring_bpm_var.set(False)
            self.include_quadrupole_var.set(False)
            self.include_sextupole_var.set(False)
            self.include_octupole_var.set(False)
            if float(self.sample_hz_var.get()) > 2.0:
                self.sample_hz_var.set("2")
        elif profile == "heavy":
            self.heavy_mode_var.set(True)
            self.include_bpm_buffer_var.set(True)
            self.include_candidate_bpm_var.set(True)
            self.include_ring_bpm_var.set(True)
            self.include_quadrupole_var.set(True)
            self.include_sextupole_var.set(True)
            self.include_octupole_var.set(True)
            if float(self.sample_hz_var.get()) > 2.0:
                self.sample_hz_var.set("1")
        else:
            self.heavy_mode_var.set(False)
            self.include_bpm_buffer_var.set(False)
            self.include_candidate_bpm_var.set(True)
            self.include_ring_bpm_var.set(True)
            self.include_quadrupole_var.set(False)
            self.include_sextupole_var.set(True)
            self.include_octupole_var.set(True)
            if float(self.sample_hz_var.get()) > 2.0:
                self.sample_hz_var.set("1")
        self._refresh_inventory()

    def _toggle_heavy_mode(self) -> None:
        heavy = bool(self.heavy_mode_var.get())
        if heavy:
            self.log_profile_var.set("heavy")
        elif self.log_profile_var.get() == "heavy":
            self.log_profile_var.set("ssmb_standard")
        if heavy:
            self.include_bpm_buffer_var.set(True)
            self.include_candidate_bpm_var.set(True)
            self.include_ring_bpm_var.set(True)
            self.include_quadrupole_var.set(True)
            self.include_sextupole_var.set(True)
            self.include_octupole_var.set(True)
            if float(self.sample_hz_var.get()) > 2.0:
                self.sample_hz_var.set("1")
        self._refresh_inventory()

    def _update_write_controls(self) -> None:
        if hasattr(self, "run_sweep_button"):
            if self.allow_writes and not self.safe_mode_var.get():
                self.run_sweep_button.state(["!disabled"])
            else:
                self.run_sweep_button.state(["disabled"])
        self._update_safe_mode_visuals()

    def _on_safe_mode_changed(self) -> None:
        self._update_write_controls()

    def _update_safe_mode_visuals(self) -> None:
        if not hasattr(self, "safe_mode_button"):
            return
        if self.safe_mode_var.get():
            self.safe_mode_button.configure(
                text="SAFE MODE ON",
                bg="#2e7d32",
                fg="white",
                selectcolor="#2e7d32",
                activebackground="#388e3c",
                activeforeground="white",
            )
            self.safe_mode_hint.configure(
                text="Writes are blocked. Turn this off explicitly before RF sweep or experimental bump control."
            )
        else:
            self.safe_mode_button.configure(
                text="WRITE MODE ENABLED",
                bg="#c62828",
                fg="white",
                selectcolor="#c62828",
                activebackground="#d32f2f",
                activeforeground="white",
            )
            self.safe_mode_hint.configure(
                text="Writes are possible. RF sweep and experimental bump control still require explicit confirmation."
            )

    def _preset_low_alpha(self) -> None:
        self.label_var.set("low_alpha")
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.laser_shots_var.set("0")
        self.note_var.set("Low-alpha full passive logging")
        self._toggle_heavy_mode()

    def _preset_bump(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.laser_shots_var.set("0")
        self.note_var.set("Set bump state externally before starting this passive log")
        self._toggle_heavy_mode()

    def _preset_sweep(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.sample_hz_var.set("1")
        self.laser_shots_var.set("0")
        self.note_var.set("Rich SSMB RF sweep with external bump state fixed before run; online delta_s / eta / alpha0 summaries enabled")
        self.delta_min_hz_var.set("-20")
        self.delta_max_hz_var.set("20")
        self.points_var.set("11")
        self.settle_var.set("1.2")
        self.samples_per_point_var.set("5")
        self.sample_spacing_var.set("0.25")
        self._toggle_heavy_mode()
        self.include_bpm_buffer_var.set(False)
        self._refresh_inventory()

    def _append_log(self, message: str) -> None:
        at_bottom = self.log_text.yview()[1] >= 0.999
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.configure(state="disabled")
        if at_bottom:
            self.log_text.see("end")

    def _set_inventory_text(self, lines: list[str]) -> None:
        self.inventory_text.configure(state="normal")
        self.inventory_text.delete("1.0", "end")
        self.inventory_text.insert("1.0", "\n".join(lines))
        self.inventory_text.configure(state="disabled")

    def _set_text_widget(self, widget: "tk.Text", lines: list[str]) -> None:
        yview = widget.yview()
        xview = widget.xview()
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))
        widget.configure(state="disabled")
        try:
            if yview != (0.0, 1.0):
                widget.yview_moveto(yview[0])
            if xview != (0.0, 1.0):
                widget.xview_moveto(xview[0])
        except Exception:
            pass

    def _drain_queue(self) -> None:
        while True:
            try:
                message = self.queue.get_nowait()
            except queue.Empty:
                break
            try:
                if isinstance(message, dict):
                    if message.get("kind") == "bpm_status":
                        self._update_bpm_status(message)
                    elif message.get("kind") == "manual_stage0_done":
                        self.stage0_stop_event = None
                        self.start_manual_button.state(["!disabled"])
                        self.stop_manual_button.state(["disabled"])
                        self._append_log("Manual logging task finalized.")
                    elif message.get("kind") == "monitor_update":
                        self._update_live_monitor(message)
                    elif message.get("kind") == "monitor_update_pending":
                        payload = self._take_pending_monitor_update()
                        if payload is not None:
                            self._update_live_monitor(payload)
                    elif message.get("kind") == "monitor_done":
                        self.monitor_stop_event = None
                        self.start_monitor_button.state(["!disabled"])
                        self.stop_monitor_button.state(["disabled"])
                        self._append_log("Live monitor stopped.")
                    elif message.get("kind") == "bump_lab_update":
                        self._update_bump_lab(payload=message)
                    elif message.get("kind") == "bump_lab_done":
                        self.bump_lab_stop_event = None
                        self._append_log("Experimental bump-lab loop stopped.")
                else:
                    self._append_log(str(message))
            except Exception as exc:
                self._append_log("GUI update failed: %s" % exc)
        self.root.after(100, self._drain_queue)

    def _emit(self, message: str) -> None:
        self.queue.put(message)

    def _logger_priority_active(self) -> bool:
        return bool(self.stage0_stop_event is not None or (self.worker is not None and self.worker.is_alive()))

    def _enqueue_monitor_update(self, payload: dict) -> None:
        with self._monitor_message_lock:
            self._pending_monitor_payload = payload
            if self._monitor_update_queued:
                return
            self._monitor_update_queued = True
        self.queue.put({"kind": "monitor_update_pending"})

    def _take_pending_monitor_update(self):
        with self._monitor_message_lock:
            payload = self._pending_monitor_payload
            self._pending_monitor_payload = None
            self._monitor_update_queued = False
            return payload

    def _emit_bpm_status(self, sample: dict) -> None:
        derived = sample.get("derived", {})
        self.queue.put(
            {
                "kind": "bpm_status",
                "sample_index": sample.get("sample_index"),
                "phase": sample.get("phase", ""),
                "entries": derived.get("bpm_x_status", []),
                "nonlinear_labels": derived.get("bpm_x_nonlinear_labels", []),
                "warning_mm": derived.get("bpm_x_warning_mm", BPM_WARNING_MM),
                "nonlinear_mm": derived.get("bpm_x_nonlinear_mm", BPM_NONLINEAR_MM),
            }
        )

    def _update_bpm_status(self, payload: dict) -> None:
        entries = payload.get("entries", [])
        warning_mm = payload.get("warning_mm", BPM_WARNING_MM)
        nonlinear_mm = payload.get("nonlinear_mm", BPM_NONLINEAR_MM)
        nonlinear = payload.get("nonlinear_labels", [])
        self.bpm_status_text.configure(state="normal")
        self.bpm_status_text.delete("1.0", "end")
        self.bpm_status_text.insert("end", "Current horizontal BPM status\n")
        self.bpm_status_text.insert("end", "yellow >= %.1f mm | red >= %.1f mm\n" % (warning_mm, nonlinear_mm))
        self.bpm_status_text.insert("end", "sample %s phase=%s\n\n" % (payload.get("sample_index"), payload.get("phase")))
        if not entries:
            self.bpm_status_text.insert("end", "No BPM X values available yet.\n")
        for entry in entries:
            self.bpm_status_text.insert("end", "%s = %.3f mm\n" % (entry["label"], entry["value_mm"]), entry.get("severity", "green"))
        if nonlinear:
            self.bpm_status_text.insert("end", "\nNonlinear-range BPMs detected:\n", "red")
            for label in nonlinear:
                self.bpm_status_text.insert("end", "- %s\n" % label, "red")
        self.bpm_status_text.configure(state="disabled")

    def _update_live_monitor(self, payload: dict) -> None:
        summary_lines = payload.get("summary_lines", [])
        channel_lines = payload.get("channel_lines", [])
        self.latest_monitor_sample = payload.get("sample")
        self.latest_monitor_summary = payload.get("summary")
        self._set_text_widget(self.monitor_summary_text, summary_lines)
        self._set_text_widget(self.monitor_channels_text, channel_lines)
        try:
            self._update_rf_sweep_jump_label(payload.get("summary"))
            if self.oscillation_window is not None and self.oscillation_window.winfo_exists():
                self._update_oscillation_window(self._ensure_extended_monitor_summary() or payload.get("summary"))
            self._refresh_lattice_view()
        except Exception as exc:
            self._append_log("Live monitor render failed: %s" % exc)

    def _queue_monitor_dashboard_render(self, summary) -> None:
        self._pending_dashboard_summary = summary
        if self._dashboard_render_scheduled:
            return
        now = time.monotonic()
        delay_ms = max(0, int((MONITOR_DASHBOARD_RENDER_MIN_S - (now - self._last_dashboard_render_monotonic)) * 1000.0))
        self._dashboard_render_scheduled = True
        self.root.after(delay_ms, self._flush_monitor_dashboard_render)

    def _flush_monitor_dashboard_render(self) -> None:
        self._dashboard_render_scheduled = False
        summary = self._pending_dashboard_summary
        self._pending_dashboard_summary = None
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        started = time.monotonic()
        self._update_monitor_dashboard(summary)
        self._last_dashboard_render_monotonic = time.monotonic()
        elapsed = self._last_dashboard_render_monotonic - started
        if elapsed > 0.25:
            self._debug("monitor dashboard render took %.3f s" % elapsed)
        if self._pending_dashboard_summary is not None:
            self._queue_monitor_dashboard_render(self._pending_dashboard_summary)

    def _update_rf_sweep_jump_label(self, summary) -> None:
        active = bool((summary or {}).get("rf_sweep_detection", {}).get("active"))
        text = "Go To RF Sweep (active)" if active else "Go To RF Sweep"
        for attr in ("monitor_jump_sweep_button", "monitor_window_jump_sweep_button"):
            button = getattr(self, attr, None)
            if button is not None:
                try:
                    button.configure(text=text)
                except Exception:
                    pass

    def _run_in_worker(self, target, *args) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._emit("Another SSMB task is still running.")
            return

        def runner() -> None:
            try:
                target(*args)
            except Exception as exc:
                self._emit("Task failed: %s" % exc)

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def _start_monitor(self) -> None:
        if self.monitor_thread is not None and self.monitor_thread.is_alive():
            self._append_log("Live monitor is already running.")
            return
        interval = float(self.monitor_interval_var.get())
        if interval <= 0.0:
            raise ValueError("Monitor interval must be positive.")
        self._debug("start monitor requested: interval=%s history_span=%s" % (interval, self.monitor_history_span_var.get()))
        self._debug("monitor cache path: %s" % self._monitor_history_path())
        self.monitor_history.clear()
        self.monitor_stop_event = threading.Event()
        self.start_monitor_button.state(["disabled"])
        self.stop_monitor_button.state(["!disabled"])
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self.monitor_thread.start()
        self._append_log("Started live read-only SSMB monitor. Experiment logging remains the protected path and has priority.")

    def _stop_monitor(self) -> None:
        if self.monitor_stop_event is None:
            self._append_log("Live monitor is not running.")
            return
        self.monitor_stop_event.set()
        self._append_log("Stopping live monitor after the current sample.")

    def _reset_monitor_baseline(self) -> None:
        self.monitor_history.clear()
        self._append_log("Live monitor baseline/history cleared.")

    def _monitor_loop(self, interval: float) -> None:
        try:
            config = self._collect_logger_config(allow_writes=False)
            adapter = ReadOnlyEpicsAdapter(timeout=min(config.timeout_seconds, 0.15))
            _lattice, specs = self._build_monitor_specs()
            self.live_spec_lookup = spec_index(specs)
            self._debug("monitor loop starting with %d PVs timeout=%.3f" % (len(specs), min(config.timeout_seconds, 0.15)))
            self.queue.put("Live monitor using %d PV channels (lean subset + selected extras)." % len(specs))
            sample_index = 0
            start = time.monotonic()
            derived_context = None
            while self.monitor_stop_event is not None and not self.monitor_stop_event.is_set():
                sample_started = time.monotonic()
                self._debug("monitor sample %d begin" % sample_index)
                sample = self._capture_monitor_sample(adapter, specs, sample_index, time.monotonic() - start, derived_context)
                if derived_context is None:
                    derived_context = {
                        "rf_reference_khz": sample.get("derived", {}).get("rf_readback"),
                        "l4_bpm_reference_mm": {
                            label: sample.get("channels", {}).get(label, {}).get("value")
                            for label in ("bpmz3l4rp_x", "bpmz4l4rp_x", "bpmz5l4rp_x", "bpmz6l4rp_x")
                        },
                    }
                self._debug("monitor sample %d capture complete" % sample_index)
                self.monitor_history.append(sample)
                self._trim_monitor_history()
                self._debug("monitor sample %d history append complete (len=%d)" % (sample_index, len(self.monitor_history)))
                self._append_monitor_history_cache(sample)
                self._debug("monitor sample %d cache append complete" % sample_index)
                summary = summarize_live_monitor(
                    list(self.monitor_history),
                    extra_candidate_keys=self._extra_oscillation_candidates(),
                    include_oscillation=self._should_compute_extended_analysis(),
                    include_extended=self._should_compute_extended_analysis(),
                )
                self._debug("monitor sample %d summary complete" % sample_index)
                self._enqueue_monitor_update(
                    {
                        "kind": "monitor_update",
                        "summary_lines": format_monitor_summary(summary),
                        "channel_lines": format_channel_snapshot(sample, self.live_spec_lookup),
                        "sample": sample,
                        "summary": summary,
                    }
                )
                self._debug("monitor sample %d queued for GUI update" % sample_index)
                elapsed = time.monotonic() - sample_started
                self._debug("monitor sample %d done in %.3f s" % (sample_index, elapsed))
                effective_interval = interval * (4.0 if self._logger_priority_active() else 1.0)
                if elapsed > max(1.0, 1.5 * effective_interval):
                    self.queue.put("Live monitor sample %d took %.2f s for %d PVs." % (sample_index, elapsed, len(specs)))
                sample_index += 1
                if self._logger_priority_active() and sample_index % 10 == 0:
                    self.queue.put("Logger priority active: slowing live monitor sampling to protect experiment logging.")
                if self.monitor_stop_event.wait(effective_interval):
                    break
        except Exception as exc:
            self._debug("monitor loop failed: %s" % exc)
            self.queue.put("Live monitor failed: %s" % exc)
        finally:
            self._debug("monitor loop exiting")
            self.queue.put({"kind": "monitor_done"})

    def _capture_monitor_sample(self, adapter, specs, sample_index: int, t_rel_s: float, derived_context):
        from .log_now import capture_sample_tolerant

        slow_channels = []
        error_channels = []

        def per_channel(spec, payload, elapsed):
            if elapsed >= 0.2:
                slow_channels.append((spec.label, spec.pv, elapsed))
            if payload.get("missing") and payload.get("reason") not in (None, "unconfigured_optional"):
                error_channels.append((spec.label, payload.get("reason"), payload.get("error")))

        sample = capture_sample_tolerant(
            adapter,
            specs,
            sample_index=sample_index,
            t_rel_s=t_rel_s,
            extra_fields={"phase": "live_monitor"},
            derived_context=derived_context,
            per_channel_callback=per_channel,
        )
        if slow_channels:
            slow_channels.sort(key=lambda item: item[2], reverse=True)
            top = slow_channels[:5]
            self.queue.put("Slow live-monitor PVs: %s" % ", ".join("%s=%.2fs" % (label, elapsed) for label, _pv, elapsed in top))
            self._debug("sample %d slow PVs: %s" % (sample_index, ", ".join("%s[%s]=%.3fs" % (label, pv, elapsed) for label, pv, elapsed in top)))
        if error_channels:
            top_errors = error_channels[:5]
            self._debug("sample %d PV errors: %s" % (sample_index, ", ".join("%s(%s)" % (label, reason) for label, reason, _err in top_errors)))
        return sample

    def _ensure_extended_monitor_summary(self):
        summary = self.latest_monitor_summary
        osc = (summary or {}).get("oscillation_study", {}) or {}
        if osc.get("reason") != "disabled_for_fast_monitor_path":
            return summary
        summary = summarize_live_monitor(
            list(self.monitor_history),
            extra_candidate_keys=self._extra_oscillation_candidates(),
            include_oscillation=True,
            include_extended=True,
        )
        self.latest_monitor_summary = summary
        return summary

    def _open_monitor_window(self) -> None:
        if self.monitor_window is not None and self.monitor_window.winfo_exists():
            self.monitor_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB Live Monitor")
        self._place_window_on_screen(window, 1880, 1020, x=80, y=70, relative_to_root=True)
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=0)
        outer.rowconfigure(1, weight=1)
        top = ttk.Frame(outer)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)
        left = ttk.Frame(outer)
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=0)
        left.columnconfigure(1, weight=1)
        left.rowconfigure(0, weight=1)
        self.monitor_window = window
        self.monitor_window_summary_text = None
        self.monitor_section_widgets = []
        self.monitor_plot_controls = {}
        self.monitor_plot_canvases = {}
        self.monitor_plot_settings = {}
        self.monitor_cards_container = left
        self.monitor_window_theory_text = None
        self.monitor_window_rf_state = None
        self.monitor_window_bump_state = None
        top_left = ttk.Frame(top)
        top_left.grid(row=0, column=0, sticky="nsew")
        top_left.columnconfigure(0, weight=1)
        top_right = ttk.Frame(top)
        top_right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        top_right.columnconfigure(0, weight=1)
        button_row = ttk.Frame(top_left)
        button_row.grid(row=0, column=0, sticky="nw")
        ttk.Button(button_row, text="Open Theory Window", command=self._open_theory_window).pack(side="left")
        ttk.Button(button_row, text="Open Oscillation Study", command=self._open_oscillation_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open SSMB Study", command=self._open_ssmb_study_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Live Monitor Settings…", command=self._open_monitor_settings_window).pack(side="left", padx=6)
        self.monitor_window_jump_sweep_button = ttk.Button(button_row, text="Go To RF Sweep", command=self._focus_rf_sweep_tab)
        self.monitor_window_jump_sweep_button.pack(side="left", padx=6)
        ttk.Checkbutton(button_row, text="Log y-axis", variable=self.monitor_log_scale_var, command=self._refresh_monitor_window_snapshot).pack(side="right")
        ttk.Button(button_row, text="Refresh From Buffer", command=self._refresh_monitor_window_snapshot).pack(side="left", padx=6)
        ttk.Button(button_row, text="Reload From Cache", command=self._reload_monitor_window_from_cache).pack(side="left", padx=6)
        state_row = ttk.Frame(top_left)
        state_row.grid(row=1, column=0, sticky="nw", pady=(8, 6))
        ttk.Label(state_row, text="Machine state").pack(side="left")
        self.monitor_window_rf_state = tk.Label(state_row, text="RF sweep OFF", bg="#607d8b", fg="white", padx=10, pady=4)
        self.monitor_window_rf_state.pack(side="left", padx=6)
        self.monitor_window_bump_state = tk.Label(state_row, text="Bump OFF", bg="#2e7d32", fg="white", padx=10, pady=4)
        self.monitor_window_bump_state.pack(side="left", padx=6)
        self.monitor_window_temp_state = tk.Label(state_row, text="Temp stable", bg="#2e7d32", fg="white", padx=10, pady=4)
        self.monitor_window_temp_state.pack(side="left", padx=6)
        self.monitor_window_logger_state = tk.Label(state_row, text="Logger idle", bg="#546e7a", fg="white", padx=10, pady=4)
        self.monitor_window_logger_state.pack(side="left", padx=6)
        helper = ttk.Label(
            top_left,
            text="This popout is a snapshot/history viewer for stability. Live monitor sampling keeps running in the main tool; use Refresh From Buffer or Reload From Cache to update this window.",
            wraplength=620,
            justify="left",
        )
        helper.grid(row=2, column=0, sticky="nw", pady=(0, 8))
        snap_frame = ttk.Frame(top_right)
        snap_frame.grid(row=0, column=0, sticky="nsew")
        snap_frame.columnconfigure(0, weight=1)
        snap_frame.rowconfigure(1, weight=0)
        snap_frame.rowconfigure(3, weight=1)
        ttk.Label(snap_frame, text="Current monitor summary").grid(row=0, column=0, sticky="w")
        self.monitor_window_summary_text = tk.Text(snap_frame, wrap="word", height=4, width=48)
        self.monitor_window_summary_text.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.monitor_window_summary_text.configure(state="disabled")
        ttk.Label(snap_frame, text="Current channel snapshot").grid(row=2, column=0, sticky="w")
        self.monitor_window_channels_text = tk.Text(snap_frame, wrap="none", height=6, width=48)
        self.monitor_window_channels_text.grid(row=3, column=0, sticky="nsew")
        self.monitor_window_channels_text.configure(state="disabled")
        if self.latest_monitor_sample is None:
            self._set_text_widget(
                self.monitor_window_channels_text,
                [
                    "No live sample yet.",
                    "",
                    "Start Live Monitor first, then this window will show",
                    "the live snapshot and rolling plots.",
                ],
            )
            self._set_text_widget(
                self.monitor_window_summary_text,
                [
                    "SSMB Live Monitor",
                    "",
                    "No live sample yet.",
                    "Start Live Monitor to populate the live dashboard.",
                ],
            )
        else:
            self._set_text_widget(self.monitor_window_channels_text, self.monitor_channels_text.get("1.0", "end").splitlines())
            self._set_text_widget(self.monitor_window_summary_text, self.monitor_summary_text.get("1.0", "end").splitlines())
        section_list_frame = ttk.Frame(left)
        section_list_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        section_list_frame.rowconfigure(1, weight=1)
        ttk.Label(section_list_frame, text="Sections").grid(row=0, column=0, sticky="w")
        section_tree = ttk.Treeview(section_list_frame, columns=("title",), show="headings", height=10, selectmode="browse")
        section_tree.heading("title", text="Section")
        section_tree.column("title", width=210, anchor="w")
        section_tree.grid(row=1, column=0, sticky="nsw")
        section_tree.bind("<<TreeviewSelect>>", self._on_monitor_section_selected)
        detail = ttk.Labelframe(left, text="Monitor Section", padding=8)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        body = ttk.Frame(detail)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.rowconfigure(0, weight=1)
        canvas = tk.Canvas(body, bg="white", width=960, height=420, highlightthickness=1, highlightbackground="#cfd8dc")
        canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        side = ttk.Frame(body)
        side.grid(row=0, column=1, sticky="ns")
        side.columnconfigure(0, weight=1)
        selector_header = ttk.Frame(side)
        selector_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(selector_header, text="Plot (click Use to toggle overlay)").pack(side="left")
        help_button = ttk.Button(selector_header, text="?", width=2)
        help_button.pack(side="right")
        settings_button = ttk.Button(selector_header, text="⚙", width=2)
        settings_button.pack(side="right", padx=(0, 4))
        selector = ttk.Treeview(side, columns=("enabled", "metric", "value"), show="headings", height=8, selectmode="browse")
        selector.heading("enabled", text="Use")
        selector.heading("metric", text="Metric")
        selector.heading("value", text="Latest")
        selector.column("enabled", width=44, anchor="center")
        selector.column("metric", width=180, anchor="w")
        selector.column("value", width=96, anchor="e")
        selector.grid(row=1, column=0, sticky="ns")
        text = tk.Text(side, wrap="word", height=8, width=38)
        text.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        text.configure(state="disabled")
        self.monitor_section_tree = section_tree
        self.monitor_section_widgets = [({"key": ""}, {"card": detail, "text": text, "help_button": help_button, "settings_button": settings_button, "selector": selector, "canvas": canvas})]
        if self.latest_monitor_summary is not None:
            self._refresh_monitor_window_snapshot()
        self._schedule_monitor_window_refresh()
        try:
            window.update_idletasks()
            window.deiconify()
            window.lift()
            window.attributes("-topmost", True)
            window.after(600, lambda: self._clear_topmost(window))
            window.focus_force()
        except Exception as exc:
            self._debug("open monitor window focus/lift failed: %s" % exc)
        window.protocol("WM_DELETE_WINDOW", self._close_monitor_window)

    def _close_monitor_window(self) -> None:
        if self.monitor_window is not None and self.monitor_window.winfo_exists():
            self.monitor_window.destroy()
        self.monitor_window = None
        self.monitor_window_summary_text = None
        self.monitor_window_channels_text = None
        self.monitor_cards_container = None
        self.monitor_section_widgets = []
        self.monitor_dashboard_sections = []
        self.monitor_active_section_key = None
        self.monitor_section_tree = None
        self._cancel_monitor_window_refresh()
        self.monitor_window_theory_text = None
        self.monitor_plot_controls = {}
        self.monitor_plot_canvases = {}
        self.monitor_plot_settings = {}
        self._pending_dashboard_summary = None
        self._dashboard_render_scheduled = False
        self.monitor_window_rf_state = None
        self.monitor_window_bump_state = None
        self.monitor_window_temp_state = None
        self.monitor_window_logger_state = None

    def _refresh_monitor_window_snapshot(self) -> None:
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        summary = self.latest_monitor_summary
        sample = self.latest_monitor_sample
        if summary is None and self.monitor_history:
            summary = summarize_live_monitor(
                list(self.monitor_history),
                extra_candidate_keys=self._extra_oscillation_candidates(),
                include_oscillation=False,
                include_extended=False,
            )
        if sample is None and self.monitor_history:
            sample = self.monitor_history[-1]
        summary_lines = format_monitor_summary(summary) if summary is not None else [
            "SSMB Live Monitor",
            "",
            "No live summary yet.",
            "Start Live Monitor or reload a recent history cache.",
        ]
        channel_lines = format_channel_snapshot(sample, self.live_spec_lookup) if sample is not None else [
            "No live sample yet.",
            "",
            "Start Live Monitor or reload a recent history cache.",
        ]
        if self.monitor_window_summary_text is not None:
            self._set_text_widget(self.monitor_window_summary_text, summary_lines)
        if self.monitor_window_channels_text is not None:
            self._set_text_widget(self.monitor_window_channels_text, channel_lines)
        started = time.monotonic()
        self._update_monitor_dashboard(summary)
        elapsed = time.monotonic() - started
        if elapsed > 0.25:
            self._debug("monitor window snapshot render took %.3f s" % elapsed)

    def _reload_monitor_window_from_cache(self) -> None:
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        self._load_monitor_history_cache()
        self._refresh_monitor_window_snapshot()

    def _schedule_monitor_window_refresh(self) -> None:
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        self._cancel_monitor_window_refresh()
        self._monitor_window_auto_refresh_job = self.root.after(MONITOR_WINDOW_REFRESH_MS, self._auto_refresh_monitor_window)

    def _cancel_monitor_window_refresh(self) -> None:
        job = getattr(self, "_monitor_window_auto_refresh_job", None)
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._monitor_window_auto_refresh_job = None

    def _auto_refresh_monitor_window(self) -> None:
        self._monitor_window_auto_refresh_job = None
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        if self.monitor_stop_event is not None:
            self._refresh_monitor_window_snapshot()
        self._schedule_monitor_window_refresh()

    def _focus_rf_sweep_tab(self) -> None:
        notebook = getattr(self, "control_notebook", None)
        target = getattr(self, "sweep_tab", None)
        if notebook is not None and target is not None:
            notebook.select(target)
        try:
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _open_oscillation_window(self) -> None:
        if self.oscillation_window is not None and self.oscillation_window.winfo_exists():
            self.oscillation_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB P1 Oscillation Study")
        self._place_window_on_screen(window, 1340, 930, x=90, y=80, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)
        top_buttons = ttk.Frame(frame)
        top_buttons.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(top_buttons, text="Open Theory Window", command=self._open_theory_window).pack(side="left")
        ttk.Checkbutton(top_buttons, text="Ignore during RF sweep", variable=self.oscillation_ignore_rf_var, command=lambda: self._update_oscillation_window(self.latest_monitor_summary)).pack(side="left", padx=8)
        text = tk.Text(frame, wrap="word", height=16)
        text.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        text.configure(state="disabled")
        table_frame = ttk.Frame(frame)
        table_frame.grid(row=1, column=1, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        candidate_table = ttk.Treeview(
            table_frame,
            columns=("candidate", "score", "corr", "lag", "period", "harmonic", "pairs"),
            show="headings",
            height=10,
        )
        for col, title, width in (
            ("candidate", "Candidate", 220),
            ("score", "Score", 80),
            ("corr", "r", 70),
            ("lag", "Lag", 90),
            ("period", "Period", 90),
            ("harmonic", "Harmonic", 80),
            ("pairs", "Pairs", 60),
        ):
            candidate_table.heading(col, text=title)
            candidate_table.column(col, width=width, anchor="center")
        candidate_table.grid(row=0, column=0, sticky="nsew")
        candidate_table.bind("<<TreeviewSelect>>", self._on_oscillation_candidate_selected)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=candidate_table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        candidate_table.configure(yscrollcommand=scrollbar.set)
        plots = ttk.Frame(frame)
        plots.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        plots.columnconfigure(0, weight=1)
        plots.columnconfigure(1, weight=1)
        plots.rowconfigure(0, weight=1)
        plots.rowconfigure(1, weight=1)
        canvases = []
        for idx in range(4):
            canvas = tk.Canvas(plots, bg="white", height=220, highlightthickness=1, highlightbackground="#cfd8dc")
            canvas.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            canvases.append(canvas)
        self.oscillation_window = window
        self.oscillation_window_text = text
        self.oscillation_window_table = candidate_table
        button_row = ttk.Frame(frame)
        button_row.grid(row=0, column=1, sticky="e")
        ttk.Button(button_row, text="Open Selected In Lattice", command=self._open_selected_oscillation_candidate_in_lattice).pack(side="right")
        self.oscillation_plot_canvases = canvases
        self._update_oscillation_window(
            self._ensure_extended_monitor_summary()
            or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        )
        window.protocol("WM_DELETE_WINDOW", self._close_oscillation_window)

    def _update_oscillation_window(self, summary) -> None:
        if self.oscillation_window is None or not self.oscillation_window.winfo_exists():
            return
        safe_summary = summary or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        if self.oscillation_ignore_rf_var.get() and bool((safe_summary.get("rf_sweep_detection") or {}).get("active")):
            safe_summary = dict(safe_summary)
            safe_summary["oscillation_study"] = {
                "available": False,
                "reason": "rf_sweep_active_ignored",
                "checked_candidate_keys": list(((safe_summary.get("oscillation_study") or {}).get("checked_candidate_keys")) or []),
            }
        self._set_text_widget(self.oscillation_window_text, format_oscillation_study(safe_summary))
        self._update_oscillation_candidate_table(safe_summary)
        self._draw_oscillation_candidate_plots(safe_summary)

    def _close_oscillation_window(self) -> None:
        if self.oscillation_window is not None and self.oscillation_window.winfo_exists():
            self.oscillation_window.destroy()
        self.oscillation_window = None
        self.oscillation_window_text = None
        self.oscillation_window_table = None
        self.oscillation_plot_canvases = []

    def _update_oscillation_candidate_table(self, summary) -> None:
        table = getattr(self, "oscillation_window_table", None)
        if table is None:
            return
        for item in table.get_children():
            table.delete(item)
        candidates = ((summary or {}).get("oscillation_study", {}) or {}).get("candidates", [])
        if not candidates:
            self.oscillation_selected_candidate_key = None
        for candidate in candidates:
            table.insert(
                "",
                "end",
                iid=candidate.get("key", ""),
                values=(
                    candidate.get("label", candidate.get("key", "candidate")),
                    "%.3f" % float(candidate.get("score") or 0.0),
                    "%.3f" % float(candidate.get("pearson_r") or 0.0),
                    self._format_short_duration(candidate.get("lag_s")),
                    self._format_short_duration(candidate.get("candidate_period_s")),
                    "%.3f" % float(candidate.get("harmonic_similarity") or 0.0),
                    "%d" % int(candidate.get("pair_count") or 0),
                ),
            )

    def _on_oscillation_candidate_selected(self, _event=None) -> None:
        table = getattr(self, "oscillation_window_table", None)
        if table is None:
            return
        selection = table.selection()
        if not selection:
            return
        key = selection[0]
        self.oscillation_selected_candidate_key = key
        self._draw_oscillation_candidate_plots(self.latest_monitor_summary)

    def _open_selected_oscillation_candidate_in_lattice(self) -> None:
        key = self.oscillation_selected_candidate_key
        if not key:
            return
        mapping = {
            "qpd_l4_center_x_avg_um": "QPD00ZL4RP",
            "qpd_l2_center_x_avg_um": "QPD01ZL2RP",
            "bump_strength_a": "HS3P1L4RP:setCur",
            "bump_orbit_error_mm": "BPMZ1L2RP",
            "bump_bpm_l2_mm": "BPMZ1L2RP",
            "bump_bpm_k3_mm": "BPMZ1K3RP",
            "bump_bpm_l4_mm": "BPMZ1L4RP",
            "delta_s": "BPMZ4L4RP",
        }
        device_name = mapping.get(key)
        if not device_name:
            return
        self._open_lattice_window()
        if not self.lattice_device_items:
            return
        for item in self.lattice_device_items:
            if item.get("name") == device_name:
                self._show_lattice_item_info(item)
                break

    def _format_short_duration(self, value) -> str:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return "n/a"
        if abs(seconds) >= 60.0:
            return "%.2f min" % (seconds / 60.0)
        if abs(seconds) >= 1.0:
            return "%.2f s" % seconds
        if abs(seconds) >= 1.0e-3:
            return "%.2f ms" % (seconds * 1.0e3)
        return "%.2f us" % (seconds * 1.0e6)

    def _draw_oscillation_candidate_plots(self, summary) -> None:
        canvases = getattr(self, "oscillation_plot_canvases", [])
        if not canvases:
            return
        trend_data = (summary or {}).get("trend_data", {})
        osc = (summary or {}).get("oscillation_study", {}) or {}
        selected_key = self.oscillation_selected_candidate_key
        selected_candidate = None
        for candidate in osc.get("candidates", []):
            if candidate.get("key") == selected_key:
                selected_candidate = candidate
                break
        if selected_candidate is None and osc.get("candidates"):
            selected_candidate = osc.get("candidates", [None])[2] if len(osc.get("candidates", [])) >= 3 else osc.get("candidates", [None])[-1]
        plot_defs = [
            (
                "P1 avg only",
                [("P1 avg", self._prepare_plot_series(list(trend_data.get("p1_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa")],
            ),
        ]
        top_candidates = list(osc.get("candidates", []))[:2]
        comparison_candidates = top_candidates + [selected_candidate]
        while len(comparison_candidates) < 3:
            comparison_candidates.append(None)
        seen = set()
        deduped = []
        for candidate in comparison_candidates:
            key = None if candidate is None else candidate.get("key")
            marker = key or "__none__"
            if marker in seen and key is not None:
                continue
            seen.add(marker)
            deduped.append(candidate)
        while len(deduped) < 3:
            deduped.append(None)
        for candidate in deduped[:3]:
            if candidate is None:
                plot_defs.append(("Candidate pending", []))
                continue
            key = candidate.get("key")
            label = candidate.get("label", key or "candidate")
            meta = trend_definitions().get(key, {"color": "#455a64"})
            plot_defs.append(
                (
                        "P1 vs %s" % label,
                        [
                        ("P1 avg", self._prepare_plot_series(list(trend_data.get("p1_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"),
                        (label, self._prepare_plot_series(list(trend_data.get(key, [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), meta["color"]),
                        ],
                    )
            )
        for canvas, (title, payload) in zip(canvases, plot_defs):
            canvas.delete("all")
            width = int(canvas.winfo_width() or 420)
            height = int(canvas.winfo_height() or 180)
            if not payload:
                canvas.create_rectangle(10, 10, width - 10, height - 10, outline="#cfd8dc")
                canvas.create_text(width / 2, height / 2, text=title, fill="#90a4ae")
                continue
            normalized_payload = []
            for series_label, values, color in payload:
                valid = [float(value) for value in values if isinstance(value, (int, float))]
                if len(valid) >= 2:
                    mean = sum(valid) / len(valid)
                    variance = sum((value - mean) ** 2 for value in valid) / max(len(valid) - 1, 1)
                    std = math.sqrt(variance) if variance > 0.0 else 1.0
                    norm_values = [None if not isinstance(value, (int, float)) else (float(value) - mean) / std for value in values]
                else:
                    norm_values = list(values)
                normalized_payload.append((series_label, norm_values, color))
            actual_samples = max((len(values) for _series_label, values, _color in normalized_payload), default=0)
            self._draw_multi_series(
                canvas,
                normalized_payload,
                10,
                24,
                width - 10,
                height - 10,
                max(10, self._window_samples_for_seconds(LONG_STUDY_PLOT_WINDOW_S)),
                actual_samples=actual_samples,
            )
            canvas.create_text(width / 2, 6, anchor="n", text=title, fill="#37474f", font=("Helvetica", 10, "bold"))

    def _update_monitor_dashboard(self, summary) -> None:
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        if summary is None:
            summary = summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        sections = build_monitor_sections(summary)
        self._update_monitor_state_badges(summary)
        self._ensure_monitor_cards(sections)
        self._render_active_monitor_section()
        if self.theory_window is not None and self.theory_window.winfo_exists():
            self._update_theory_window(summary)
        if self.ssmb_study_window is not None and self.ssmb_study_window.winfo_exists():
            self._update_ssmb_study_window(self._ensure_extended_monitor_summary() or summary)

    def _color_text_widget(self, widget: "tk.Text", color_name: str) -> None:
        colors = {"green": "#1b5e20", "yellow": "#8d6e00", "red": "#b71c1c"}
        widget.configure(fg=colors.get(color_name, "#263238"))

    def _update_monitor_state_badges(self, summary) -> None:
        rf_widget = getattr(self, "monitor_window_rf_state", None)
        bump_widget = getattr(self, "monitor_window_bump_state", None)
        temp_widget = getattr(self, "monitor_window_temp_state", None)
        logger_widget = getattr(self, "monitor_window_logger_state", None)
        if rf_widget is not None:
            rf_active = bool((summary or {}).get("rf_sweep_detection", {}).get("active"))
            rf_widget.configure(text="RF sweep ON" if rf_active else "RF sweep OFF", bg="#c62828" if rf_active else "#607d8b")
        if bump_widget is not None:
            bump_active = bool((summary or {}).get("bump_state", {}).get("active"))
            bump_widget.configure(text="Bump ON" if bump_active else "Bump OFF", bg="#c62828" if bump_active else "#2e7d32")
        if temp_widget is not None:
            temp_state = (summary or {}).get("temperature_state", {}) or {}
            temp_active = bool(temp_state.get("unstable"))
            delta = temp_state.get("max_deviation_c")
            label = "Temp unstable" if temp_active else "Temp stable"
            if isinstance(delta, (int, float)):
                label += " (Δ=%.2f C)" % float(delta)
            temp_widget.configure(text=label, bg="#c62828" if temp_active else "#2e7d32")
        if logger_widget is not None:
            logger_running = self.stage0_stop_event is not None or (self.worker is not None and self.worker.is_alive())
            logger_widget.configure(text="Logger active" if logger_running else "Logger idle", bg="#ef6c00" if logger_running else "#546e7a")

    def _format_plot_value(self, value) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "n/a"
        if numeric == 0.0:
            return "0"
        magnitude = abs(numeric)
        if magnitude >= 1.0e3 or magnitude < 1.0e-2:
            return "%.2e" % numeric
        return "%.4g" % numeric

    def _ensure_monitor_cards(self, sections) -> None:
        selector_tree = getattr(self, "monitor_section_tree", None)
        if selector_tree is None:
            return
        self.monitor_dashboard_sections = list(sections)
        existing_ids = set(selector_tree.get_children())
        desired_ids = [section["key"] for section in sections]
        for item_id in existing_ids - set(desired_ids):
            selector_tree.delete(item_id)
        for section in sections:
            item_id = section["key"]
            if selector_tree.exists(item_id):
                selector_tree.set(item_id, "title", section["title"])
            else:
                selector_tree.insert("", "end", iid=item_id, values=(section["title"],))
        if self.monitor_active_section_key not in desired_ids:
            self.monitor_active_section_key = desired_ids[0] if desired_ids else None
        if self.monitor_active_section_key is not None and selector_tree.exists(self.monitor_active_section_key):
            current_selection = tuple(selector_tree.selection())
            desired_selection = (self.monitor_active_section_key,)
            if current_selection != desired_selection:
                self._updating_monitor_section_tree = True
                try:
                    selector_tree.selection_set(desired_selection)
                    selector_tree.focus(self.monitor_active_section_key)
                finally:
                    self._updating_monitor_section_tree = False
        if not self.monitor_section_widgets:
            return
        section = next((item for item in sections if item["key"] == self.monitor_active_section_key), sections[0] if sections else None)
        if section is None:
            return
        widgets = self.monitor_section_widgets[0][1]
        selector = widgets["selector"]
        options = section.get("trend_options", [])
        current_keys = self.monitor_plot_controls.get(section["key"])
        if not current_keys:
            current_keys = [section.get("default_trend")] if section.get("default_trend") else []
        current_keys = [key for key in current_keys if key in options]
        if not current_keys and options:
            current_keys = [options[0]]
        self.monitor_plot_controls[section["key"]] = current_keys
        trend_data = (self.latest_monitor_summary or {}).get("trend_data", {})
        previous_options = widgets.get("selector_options", [])
        if list(previous_options) != list(options):
            for item in selector.get_children():
                selector.delete(item)
            options = section.get("trend_options", [])
            for key in options:
                values = [value for value in trend_data.get(key, []) if isinstance(value, (int, float))]
                latest = values[-1] if values else None
                selector.insert(
                    "",
                    "end",
                    iid=key,
                    values=("[x]" if key in current_keys else "[ ]", trend_definitions()[key]["label"], self._format_plot_value(latest)),
                )
            selector.bind("<<TreeviewSelect>>", lambda _event, key=section["key"], opts=options, tree=selector: self._on_monitor_plot_selected(key, opts, tree))
            selector.bind("<Button-1>", lambda event, key=section["key"], opts=options, tree=selector: self._on_monitor_plot_click(key, opts, tree, event))
            widgets["selector_options"] = list(options)
        else:
            for key in options:
                if not selector.exists(key):
                    continue
                values = [value for value in trend_data.get(key, []) if isinstance(value, (int, float))]
                latest = values[-1] if values else None
                selector.set(key, "enabled", "[x]" if key in current_keys else "[ ]")
                selector.set(key, "value", self._format_plot_value(latest))
        desired_plot_selection = (current_keys[0],) if current_keys else ()
        if tuple(selector.selection()) != desired_plot_selection:
            self._updating_monitor_plot_selector = True
            try:
                selector.selection_set(desired_plot_selection)
            finally:
                self._updating_monitor_plot_selector = False
        widgets["help_button"].configure(command=lambda sec=section: self._show_monitor_section_help(sec))
        widgets["settings_button"].configure(command=lambda sec=section: self._open_monitor_plot_settings(sec))
        self.monitor_section_widgets = [(section, widgets)]

    def _render_active_monitor_section(self) -> None:
        if not self.monitor_section_widgets:
            return
        section, widgets = self.monitor_section_widgets[0]
        card = widgets["card"]
        text_widget = widgets["text"]
        card.configure(text=section["title"])
        lines = []
        for label, value in section.get("rows", []):
            lines.append("%s: %s" % (label, value))
        if section.get("equations"):
            lines.extend(["", "Equations:"])
            lines.extend(section["equations"])
        if section.get("note"):
            lines.extend(["", section["note"]])
        self._set_text_widget(text_widget, lines)
        self._color_text_widget(text_widget, section.get("color", "green"))
        self._draw_section_plot(section)

    def _on_monitor_section_selected(self, _event=None) -> None:
        if self._updating_monitor_section_tree:
            return
        tree = getattr(self, "monitor_section_tree", None)
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            return
        self.monitor_active_section_key = selection[0]
        self._update_monitor_dashboard(self.latest_monitor_summary)

    def _on_monitor_plot_selected(self, section_key: str, options: Sequence[str], tree) -> None:
        if self._updating_monitor_plot_selector:
            return
        if getattr(self, "_suppress_monitor_plot_selected_once", False):
            self._suppress_monitor_plot_selected_once = False
            return
        selected = [item for item in tree.selection() if item in options]
        if not selected and options:
            selected = [options[0]]
            tree.selection_set(options[0])
        current = list(self.monitor_plot_controls.get(section_key) or [])
        focused = selected[0] if selected else None
        if focused:
            current = [key for key in current if key in options]
            if not current:
                current = [focused]
            elif focused in current:
                current = [focused] + [key for key in current if key != focused]
            else:
                current = [focused] + current
        if not current and options:
            current = [options[0]]
        self.monitor_plot_controls[section_key] = current
        for key in options:
            if tree.exists(key):
                tree.set(key, "enabled", "[x]" if key in current else "[ ]")
        self._update_monitor_dashboard(self.latest_monitor_summary)

    def _on_monitor_plot_click(self, section_key: str, options: Sequence[str], tree, event):
        region = tree.identify("region", event.x, event.y)
        column = tree.identify_column(event.x)
        row_id = tree.identify_row(event.y)
        if region == "cell" and column == "#1" and row_id and row_id in options:
            return self._on_monitor_plot_toggle(section_key, options, tree, event)
        return None

    def _on_monitor_plot_toggle(self, section_key: str, options: Sequence[str], tree, event) -> str:
        row_id = tree.identify_row(event.y)
        if not row_id or row_id not in options:
            return "break"
        current = list(self.monitor_plot_controls.get(section_key) or [])
        if row_id in current:
            if len(current) > 1:
                current = [key for key in current if key != row_id]
        else:
            current.append(row_id)
        current = [key for key in current if key in options]
        if not current and options:
            current = [options[0]]
        self.monitor_plot_controls[section_key] = current
        self._suppress_monitor_plot_selected_once = True
        self._updating_monitor_plot_selector = True
        try:
            tree.selection_set((row_id,))
        finally:
            self._updating_monitor_plot_selector = False
        for key in options:
            if tree.exists(key):
                tree.set(key, "enabled", "[x]" if key in current else "[ ]")
        self._update_monitor_dashboard(self.latest_monitor_summary)
        return "break"

    def _show_monitor_section_help(self, section: dict) -> None:
        lines = [section.get("title", "Section"), ""]
        if section.get("equations"):
            lines.append("How values are derived:")
            lines.extend(section["equations"])
            lines.append("")
        if section.get("note"):
            lines.append(section["note"])
        else:
            lines.append("Live values and trends for this section.")
        if messagebox is not None:
            messagebox.showinfo(section.get("title", "Section help"), "\n".join(lines))

    def _open_monitor_plot_settings(self, section: dict) -> None:
        key = section["key"]
        current = self.monitor_plot_settings.get(key, {})
        window = tk.Toplevel(self.root)
        window.title("%s Plot Settings" % section.get("title", "Pane"))
        self._place_window_on_screen(window, 360, 220, x=120, y=120, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        local_window_var = tk.StringVar(value=str(current.get("window_samples", self.rolling_window_var.get())))
        local_log_var = tk.BooleanVar(value=bool(current.get("log_y", False)))
        local_fixed_var = tk.BooleanVar(value=bool(current.get("fixed_window", True)))
        ttk.Label(frame, text="Window [samples]").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=local_window_var, width=12).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Log y-axis for this pane", variable=local_log_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(frame, text="Fixed rolling window", variable=local_fixed_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(
            frame,
            text="Fixed rolling window keeps the last N samples. If disabled, the pane follows the full available monitor history up to the central buffer limit.",
            wraplength=320,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        def apply_settings():
            try:
                window_samples = max(10, int(float(local_window_var.get())))
            except Exception:
                window_samples = max(10, int(float(self.rolling_window_var.get())))
            self.monitor_plot_settings[key] = {
                "window_samples": window_samples,
                "log_y": bool(local_log_var.get()),
                "fixed_window": bool(local_fixed_var.get()),
            }
            window.destroy()
            self._update_monitor_dashboard(self.latest_monitor_summary)

        ttk.Button(button_row, text="Apply", command=apply_settings).pack(side="left")
        ttk.Button(button_row, text="Reset", command=lambda: (self.monitor_plot_settings.pop(key, None), window.destroy(), self._update_monitor_dashboard(self.latest_monitor_summary))).pack(side="left", padx=6)
        ttk.Button(button_row, text="Close", command=window.destroy).pack(side="right")

    def _draw_section_plot(self, section: dict) -> None:
        widgets = None
        for existing_section, candidate in self.monitor_section_widgets:
            if existing_section["key"] == section["key"]:
                widgets = candidate
                break
        if widgets is None:
            return
        canvas = widgets["canvas"]
        selected_metrics = self.monitor_plot_controls.get(section["key"])
        if not selected_metrics:
            default_metric = section.get("default_trend")
            selected_metrics = [default_metric] if default_metric else []
            self.monitor_plot_controls[section["key"]] = selected_metrics
        trend_data = (self.latest_monitor_summary or {}).get("trend_data", {})
        canvas.delete("all")
        width = int(canvas.winfo_width() or 280)
        height = int(canvas.winfo_height() or 120)
        settings = self.monitor_plot_settings.get(section["key"], {})
        default_samples = self._window_samples_for_seconds(LIVE_MONITOR_PLOT_WINDOW_S)
        window_samples = max(10, int(settings.get("window_samples", default_samples)))
        fixed_window = bool(settings.get("fixed_window", True))
        series_payload = []
        for metric in selected_metrics:
            values = list(trend_data.get(metric, []))
            if fixed_window:
                values = values[-window_samples:]
            values = _downsample_tail(values, DEFAULT_PLOT_MAX_POINTS)
            meta = trend_definitions().get(metric, {"label": metric, "color": "#455a64"})
            series_payload.append((meta["label"], values, meta["color"]))
        actual_samples = max((len(values) for _label, values, _color in series_payload), default=0)
        self._draw_multi_series(
            canvas,
            series_payload,
            10,
            10,
            width - 10,
            height - 10,
            window_samples,
            use_log_override=settings.get("log_y"),
            actual_samples=actual_samples,
        )

    def _draw_series(self, canvas, values, x0, y0, x1, y1, color, label):
        canvas.create_rectangle(x0, y0, x1, y1, outline="#cfd8dc")
        canvas.create_text(x0 + 4, y0 + 4, anchor="nw", text=label, fill="#37474f")
        clean = [v for v in values if isinstance(v, (int, float, float))]
        if len(clean) < 2:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="waiting for data", fill="#90a4ae")
            return
        pts = self._series_to_points(values, x0 + 8, y0 + 20, x1 - 8, y1 - 8)
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=2)

    def _draw_multi_series(self, canvas, series_payload, x0, y0, x1, y1, window_samples: int, use_log_override=None, actual_samples=None):
        canvas.create_rectangle(x0, y0, x1, y1, outline="#cfd8dc")
        use_log = bool(self.monitor_log_scale_var.get()) if use_log_override is None else bool(use_log_override)
        clean_all = []
        for _label, values, _color in series_payload:
            for value in values:
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    if use_log:
                        if numeric <= 0.0:
                            continue
                        numeric = math.log10(numeric)
                    clean_all.append(numeric)
        if not clean_all:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="waiting for data", fill="#90a4ae")
            return
        vmin = min(clean_all)
        vmax = max(clean_all)
        if vmax == vmin:
            vmax = vmin + 1.0
        else:
            pad = 0.05 * (vmax - vmin)
            vmin -= pad
            vmax += pad
        exponent = 0
        scale = 1.0
        if not use_log:
            max_abs = max(abs(vmin), abs(vmax))
            if max_abs > 0.0:
                exponent = int(math.floor(math.log10(max_abs)))
                if abs(exponent) >= 2:
                    scale = 10.0 ** exponent
        try:
            interval_s = max(0.01, float(self.monitor_interval_var.get()))
        except Exception:
            interval_s = 0.5
        displayed_samples = window_samples
        if isinstance(actual_samples, int) and actual_samples > 1:
            displayed_samples = min(window_samples, actual_samples)
        time_span_s = max(interval_s, displayed_samples * interval_s)
        plot_x0 = x0 + 42
        plot_y0 = y0 + 38
        plot_x1 = x1 - 8
        plot_y1 = y1 - 22
        axis_text = "log10 scale" if use_log else ("y / 1e%d" % exponent if scale != 1.0 else "linear scale")
        label_text = "last %d samples" % displayed_samples if displayed_samples < window_samples else "last %d samples" % window_samples
        canvas.create_text(x0 + 4, y0 + 4, anchor="nw", text=label_text, fill="#607d8b", font=("Helvetica", 8))
        canvas.create_text(x1 - 4, y0 + 4, anchor="ne", text="%.1f s window | %s" % (time_span_s, axis_text), fill="#607d8b", font=("Helvetica", 8))
        for frac, value in ((0.0, vmax), (0.5, 0.5 * (vmin + vmax)), (1.0, vmin)):
            y = plot_y0 + frac * (plot_y1 - plot_y0)
            canvas.create_line(plot_x0, y, plot_x1, y, fill="#eceff1", dash=(2, 2))
            display_value = value if use_log else value / scale
            canvas.create_text(plot_x0 - 4, y, anchor="e", text="%.3g" % display_value, fill="#607d8b", font=("Helvetica", 8))
        for frac, label in ((0.0, "-%.0fs" % time_span_s), (0.5, "-%.0fs" % (0.5 * time_span_s)), (1.0, "now")):
            x = plot_x0 + frac * (plot_x1 - plot_x0)
            canvas.create_line(x, plot_y1, x, plot_y1 + 4, fill="#90a4ae")
            canvas.create_text(x, plot_y1 + 6, anchor="n", text=label, fill="#607d8b", font=("Helvetica", 8))
        legend_y = y0 + 18
        for idx, (label, values, color) in enumerate(series_payload):
            canvas.create_rectangle(x0 + 6, legend_y + idx * 12, x0 + 14, legend_y + 8 + idx * 12, fill=color, outline=color)
            canvas.create_text(x0 + 18, legend_y + 4 + idx * 12, anchor="w", text=label, fill="#37474f", font=("Helvetica", 8))
            transformed = []
            for value in values:
                if not isinstance(value, (int, float)):
                    transformed.append(None)
                    continue
                numeric = float(value)
                if use_log:
                    transformed.append(math.log10(numeric) if numeric > 0.0 else None)
                else:
                    transformed.append(numeric)
            pts = self._series_to_points(transformed, plot_x0, plot_y0, plot_x1, plot_y1, reference=clean_all)
            if len(pts) >= 4:
                canvas.create_line(*pts, fill=color, width=2, smooth=True)

    def _draw_beam_proxy(self, canvas, center_x, sigma_x, sigma_y, x0, y0, x1, y1, title):
        canvas.create_rectangle(x0, y0, x1, y1, outline="#d7ccc8")
        canvas.create_text((x0 + x1) / 2, y0 + 8, text=title, anchor="n", fill="#6d4c41", font=("Helvetica", 8, "bold"))
        width = max(10.0, x1 - x0 - 18.0)
        height = max(10.0, y1 - y0 - 26.0)
        cx = x0 + 9.0 + width / 2.0
        if isinstance(center_x, (int, float)):
            cx += max(-0.35, min(0.35, float(center_x) / 1000.0)) * width
        cy = y0 + 18.0 + height / 2.0
        sx = max(6.0, min(width * 0.4, 20.0 + 140.0 * abs(float(sigma_x or 0.0))))
        sy = max(6.0, min(height * 0.4, 20.0 + 140.0 * abs(float(sigma_y or 0.0))))
        canvas.create_line(x0 + 9, cy, x1 - 9, cy, fill="#eceff1")
        canvas.create_line(cx, y0 + 18, cx, y1 - 8, fill="#eceff1")
        canvas.create_oval(cx - sx, cy - sy, cx + sx, cy + sy, fill="#f3e5f5", outline="#8e24aa", width=2)

    def _draw_overlay_series(self, canvas, series_a, series_b, x0, y0, x1, y1, color_a, color_b, label):
        canvas.create_rectangle(x0, y0, x1, y1, outline="#cfd8dc")
        canvas.create_text(x0 + 4, y0 + 4, anchor="nw", text=label, fill="#37474f")
        pts_a = self._series_to_points(series_a, x0 + 8, y0 + 20, x1 - 8, y1 - 8)
        pts_b = self._series_to_points(series_b, x0 + 8, y0 + 20, x1 - 8, y1 - 8, reference=series_a + series_b)
        if len(pts_a) >= 4:
            canvas.create_line(*pts_a, fill=color_a, width=2, smooth=True)
        if len(pts_b) >= 4:
            canvas.create_line(*pts_b, fill=color_b, width=2, dash=(4, 2), smooth=True)

    def _series_to_points(self, values, x0, y0, x1, y1, reference=None):
        ref = reference if reference is not None else values
        clean = [float(v) for v in ref if isinstance(v, (int, float))]
        if len(clean) < 2:
            return []
        vmin = min(clean)
        vmax = max(clean)
        if vmax == vmin:
            vmax = vmin + 1.0
        step = (x1 - x0) / max(len(values) - 1, 1)
        points = []
        for idx, value in enumerate(values):
            if not isinstance(value, (int, float)):
                continue
            x = x0 + idx * step
            y = y1 - (float(value) - vmin) / (vmax - vmin) * (y1 - y0)
            points.extend([x, y])
        return points

    def _open_lattice_window(self) -> None:
        if self.lattice_window is not None and self.lattice_window.winfo_exists():
            self.lattice_window.lift()
            return
        config = self._collect_logger_config(allow_writes=False)
        config.include_candidate_bpm_scalars = True
        config.include_ring_bpm_scalars = True
        config.include_quadrupoles = True
        config.include_sextupoles = True
        config.include_octupoles = True
        lattice, specs = build_specs(config)
        window = tk.Toplevel(self.root)
        window.title("SSMB Live Lattice View")
        self._place_window_on_screen(window, 1360, 860, x=100, y=90, relative_to_root=True)
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=0)
        outer.rowconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg="white", height=660)
        canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        side = ttk.Frame(outer)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(0, weight=1)
        side.rowconfigure(1, weight=0)
        info = tk.Text(side, wrap="word", width=42, height=22)
        info.grid(row=0, column=0, sticky="nsew")
        info.configure(state="disabled")
        detail_canvas = tk.Canvas(side, bg="white", width=360, height=190, highlightthickness=1, highlightbackground="#cfd8dc")
        detail_canvas.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.lattice_window = window
        self.lattice_canvas = canvas
        self.lattice_info_text = info
        self.lattice_detail_canvas = detail_canvas
        self.lattice_context = lattice
        self.lattice_specs = specs
        canvas.bind("<Button-1>", self._on_lattice_click)
        canvas.bind("<Configure>", self._on_lattice_canvas_configure)
        window.protocol("WM_DELETE_WINDOW", self._close_lattice_window)
        window.update_idletasks()
        self._draw_lattice_view(lattice, specs)
        self._refresh_lattice_view()

    def _on_lattice_canvas_configure(self, _event=None) -> None:
        if self.lattice_context is None or self.lattice_specs is None:
            return
        self._draw_lattice_view(self.lattice_context, self.lattice_specs)

    def _draw_lattice_view(self, lattice, specs) -> None:
        canvas = self.lattice_canvas
        canvas.delete("all")
        width = int(canvas.winfo_width() or 1000)
        height = int(canvas.winfo_height() or 680)
        left = 60
        right = width - 40
        y_track = 100
        row_positions = {
            "section": 60,
            "bpm": 160,
            "qpd": 220,
            "rf": 280,
            "quadrupole": 350,
            "sextupole": 410,
            "dipole": 470,
            "octupole": 530,
            "bump": 610,
        }
        canvas.create_line(left, y_track, right, y_track, fill="#37474f", width=3)
        self.lattice_device_items = []
        sections = [("K1", "#fff3e0"), ("L2", "#e8f5e9"), ("K3", "#e3f2fd"), ("L4", "#fce4ec")]
        section_bounds = self._section_bounds(lattice)
        for name, color in sections:
            bounds = section_bounds.get(name)
            if not bounds:
                continue
            x0 = self._s_to_x(bounds[0], lattice, left, right)
            x1 = self._s_to_x(bounds[1], lattice, left, right)
            canvas.create_rectangle(x0, y_track - 18, x1, y_track + 18, fill=color, outline="")
            canvas.create_text((x0 + x1) / 2.0, row_positions["section"], text=name, fill="#263238", font=("Helvetica", 11, "bold"))
        row_specs = (
            ("BPMs", row_positions["bpm"]),
            ("QPD / optics", row_positions["qpd"]),
            ("RF / tune", row_positions["rf"]),
            ("Quadrupoles", row_positions["quadrupole"]),
            ("Sextupoles", row_positions["sextupole"]),
            ("Dipoles", row_positions["dipole"]),
            ("Octupoles", row_positions["octupole"]),
            ("Bump correctors", row_positions["bump"]),
        )
        for row_name, row_y in row_specs:
            canvas.create_text(10, row_y, anchor="w", text=row_name, fill="#455a64", font=("Helvetica", 10, "bold"))
            canvas.create_line(left, row_y, right, row_y, fill="#eceff1", dash=(3, 3))
        bpm_label_specs = {
            "BPMZ1L2RP": {"text": "BPMZ1L2", "dy": -20, "anchor": "s"},
            "BPMZ1K3RP": {"text": "BPMZ1K3", "dy": 20, "anchor": "n"},
            "BPMZ1L4RP": {"text": "BPMZ1L4", "dy": -20, "anchor": "s"},
            "BPMZ3L4RP": {"text": "BPMZ3L4", "dy": -20, "anchor": "s"},
            "BPMZ4L4RP": {"text": "BPMZ4L4", "dy": 20, "anchor": "n"},
            "BPMZ5L4RP": {"text": "BPMZ5L4", "dy": -20, "anchor": "s"},
            "BPMZ6L4RP": {"text": "BPMZ6L4", "dy": 20, "anchor": "n"},
        }
        for element in lattice.elements:
            if element.element_type not in ("Monitor", "Quadrupole", "Sextupole", "Octupole", "Dipole", "RFCavity"):
                continue
            x = self._s_to_x(element.s_center_m, lattice, left, right)
            color, label, row_y = self._element_style(element, row_positions)
            pv_label = self._match_spec_label(specs, element)
            live_payload = ((self.latest_monitor_sample or {}).get("channels", {}) or {}).get(pv_label or "", {})
            live_value = live_payload.get("value")
            marker_color, marker_outline = self._live_marker_style(element, live_value, color)
            half_width = self._lattice_marker_half_width(element)
            item_id = canvas.create_rectangle(
                x - half_width,
                row_y - 12,
                x + half_width,
                row_y + 12,
                fill=marker_color,
                outline=marker_outline,
                width=2 if marker_outline else 1,
            )
            is_bump_feedback_bpm = element.family_name in ("BPMZ1K1RP", "BPMZ1L2RP", "BPMZ1K3RP", "BPMZ1L4RP")
            if is_bump_feedback_bpm:
                canvas.create_rectangle(x - (half_width + 3), row_y - 15, x + (half_width + 3), row_y + 15, outline="#1565c0", width=2)
            self.lattice_device_items.append(
                {
                    "item_id": item_id,
                    "name": element.family_name,
                    "element_type": element.element_type,
                    "pv_label": pv_label,
                    "pv": self._match_spec_pv(specs, element),
                    "notes": "%s in %s" % (element.element_type, element.section or "ring"),
                    "x": x,
                    "y": row_y,
                    "row": row_y,
                    "click_radius": 20 if element.element_type == "Monitor" else (26 if element.element_type == "RFCavity" else 24),
                }
            )
            if element.element_type in ("RFCavity",):
                canvas.create_text(x, row_y - 18, text=label or element.family_name, anchor="s", font=("Helvetica", 8, "bold"))
            elif element.element_type == "Monitor" and element.family_name in bpm_label_specs:
                spec = bpm_label_specs[element.family_name]
                label_fill = "#1565c0" if is_bump_feedback_bpm else "#263238"
                canvas.create_text(
                    x,
                    row_y + spec["dy"],
                    text=spec["text"],
                    anchor=spec["anchor"],
                    font=("Helvetica", 7, "bold" if is_bump_feedback_bpm else "normal"),
                    fill=label_fill,
                )
        extras = [
            (
                "U125 undulator",
                None,
                "U125 undulator / interaction section marker. Inferred lattice marker near the L2 straight.",
                self._element_s_position(lattice, "BM1L2RP", fallback=6.8),
                "#26a69a",
                row_positions["qpd"],
            ),
            (
                "Laser interaction",
                None,
                "Inferred laser / interaction-point marker near the undulator region. No direct PV is attached here.",
                self._element_s_position(lattice, "BM1L2RP", fallback=7.05),
                "#00acc1",
                row_positions["qpd"],
            ),
            (
                "P1 light monitor",
                "p1_h1_ampl_avg",
                "Main coherent-light harmonic monitor used for the SSMB scan. Placed near the L2/undulator diagnostic region.",
                self._element_s_position(lattice, "BM1L2RP", fallback=7.2),
                "#8e24aa",
                row_positions["qpd"],
            ),
            (
                "P3 light monitor",
                "p3_h1_ampl_avg",
                "Third-harmonic coherent-light monitor from the same scope chain. Placed near the L2/undulator diagnostic region.",
                self._element_s_position(lattice, "BM1L2RP", fallback=7.35),
                "#fb8c00",
                row_positions["qpd"],
            ),
            (
                "QPD00ZL4RP",
                "qpd_l4_sigma_x",
                "QPD00 SR camera/profile monitor in L4. Marker is placed at the inferred source dipole BM1L4RP, not the camera head itself.",
                self._element_s_position(lattice, "BM1L4RP", fallback=31.175),
                "#d81b60",
                row_positions["qpd"],
            ),
            (
                "QPD01ZL2RP",
                "qpd_l2_sigma_x",
                "QPD01 SR camera/profile monitor in L2. Marker is placed at the inferred source dipole BM1L2RP, near the U125-side source point.",
                self._element_s_position(lattice, "BM1L2RP", fallback=7.175),
                "#8e24aa",
                row_positions["qpd"],
            ),
            (
                "HS1P2K3RP:setCur",
                "l4_bump_hcorr_k3_upstream",
                "Recovered bump corrector, mapped to the associated S1 sextupole package in K3 (inferred position).",
                self._element_s_position(lattice, "S1M1K3RP", fallback=19.45),
                "#ef6c00",
                row_positions["bump"],
            ),
            (
                "HS3P1L4RP:setCur",
                "l4_bump_hcorr_l4_upstream",
                "Recovered bump corrector, mapped to the associated S3 sextupole package in L4 (P1 family, inferred position).",
                self._element_s_position(lattice, "S3M2L4RP", fallback=39.05),
                "#ef6c00",
                row_positions["bump"],
            ),
            (
                "HS3P2L4RP:setCur",
                "l4_bump_hcorr_l4_downstream",
                "Recovered bump corrector, mapped to the associated S3 sextupole package in L4 (P2 family, inferred position).",
                self._element_s_position(lattice, "S3M1L4RP", fallback=32.95),
                "#ef6c00",
                row_positions["bump"],
            ),
            (
                "HS1P1K1RP:setCur",
                "l4_bump_hcorr_k1_downstream",
                "Recovered bump corrector, mapped to the associated S1 sextupole package in K1 (P1 family, inferred position).",
                self._element_s_position(lattice, "S1M2K1RP", fallback=4.55),
                "#ef6c00",
                row_positions["bump"],
            ),
        ]
        for name, label, notes, s_pos, color, row_y in extras:
            x = self._s_to_x(s_pos, lattice, left, right)
            live_payload = ((self.latest_monitor_sample or {}).get("channels", {}) or {}).get(label, {})
            live_value = live_payload.get("value")
            fill = color
            outline = ""
            width_px = 1
            if label.startswith("l4_bump_hcorr"):
                try:
                    current = abs(float(live_value))
                except (TypeError, ValueError):
                    current = None
                if current is not None and current >= 0.002:
                    fill = "#d84315"
                    outline = "#bf360c"
                    width_px = 2
                else:
                    fill = "#ffcc80"
                    outline = "#ef6c00"
            item_id = canvas.create_oval(x - 7, row_y - 7, x + 7, row_y + 7, fill=fill, outline=outline, width=width_px)
            if name == "QPD00ZL4RP":
                short_label = "QPD00@BM1L4"
            elif name == "QPD01ZL2RP":
                short_label = "QPD01@BM1L2"
            elif name == "P1 light monitor":
                short_label = "P1"
            elif name == "P3 light monitor":
                short_label = "P3"
            elif name == "U125 undulator":
                short_label = "U125"
            elif name == "Laser interaction":
                short_label = "Laser"
            else:
                short_label = name.split(":")[0]
            label_dy = -16
            if name in ("P1 light monitor", "QPD00ZL4RP", "HS3P2L4RP:setCur"):
                label_dy = -26
            elif name in ("P3 light monitor", "QPD01ZL2RP", "HS3P1L4RP:setCur"):
                label_dy = 18
            canvas.create_text(x, row_y + label_dy, text=short_label, anchor="s" if label_dy < 0 else "n", font=("Helvetica", 8, "bold" if name.startswith("QPD") or name.startswith("P") else "normal"))
            if isinstance(live_value, (int, float)):
                canvas.create_text(x, row_y + 12, text="%.3f" % float(live_value), anchor="n", font=("Helvetica", 7), fill="#5d4037")
            self.lattice_device_items.append(
                {
                    "item_id": item_id,
                    "name": name,
                    "element_type": "Diagnostic",
                    "pv_label": label,
                    "pv": name if ":" in name else None,
                    "notes": notes,
                    "x": x,
                    "y": row_y,
                    "row": row_y,
                    "click_radius": 18,
                }
            )
        bump_state = (self.latest_monitor_summary or {}).get("bump_state", {})
        bump_label = "BUMP ON" if bump_state.get("active") else "BUMP OFF/idle"
        bump_color = "#b71c1c" if bump_state.get("active") else "#1b5e20"
        canvas.create_text(right, 24, anchor="e", text=bump_label, fill=bump_color, font=("Helvetica", 12, "bold"))
        canvas.create_text(left, height - 18, anchor="w", text="Click a marker for live PV mapping. Rows separate BPMs, optics, RF, and each magnet family for easier inspection.", fill="#455a64")

    def _refresh_lattice_view(self) -> None:
        if self.lattice_window is None or not self.lattice_window.winfo_exists():
            return
        if self.latest_monitor_sample is None:
            self._set_text_widget(self.lattice_info_text, ["No live sample yet. Start Live Monitor first."])
            return
        if not self.lattice_device_items:
            return
        if self.selected_lattice_item_name:
            for item in self.lattice_device_items:
                if item.get("name") == self.selected_lattice_item_name:
                    self._show_lattice_item_info(item)
                    return
        self._set_text_widget(
            self.lattice_info_text,
            [
                "Lattice view ready.",
                "",
                "Click a lattice marker to inspect its live readout.",
                "",
                "Recovered bump-feedback BPM chain: BPMZ1K1RP, BPMZ1L2RP, BPMZ1K3RP, BPMZ1L4RP.",
                "BPMZ1L2RP is the undulator-side/ L2 anchor of the orbit-lock loop; the others are spread through K3 and L4, so the loop constrains a global closed orbit rather than only one local point.",
                "",
                "Live lattice hints:",
                "- BPM markers are colored by live X offset severity.",
                "- Bump correctors highlight when their live current is active.",
            ],
        )

    def _on_lattice_click(self, event) -> None:
        if not self.lattice_device_items:
            return
        candidates = [
            item
            for item in self.lattice_device_items
            if abs(item["x"] - event.x) <= item.get("click_radius", 18)
            and abs(item.get("row", item["y"]) - event.y) <= max(18, item.get("click_radius", 18))
        ]
        pool = candidates or self.lattice_device_items
        nearest = min(
            pool,
            key=lambda item: (item["x"] - event.x) ** 2 + ((item.get("row", item["y"]) - event.y) * 1.35) ** 2,
        )
        self._show_lattice_item_info(nearest)

    def _show_lattice_item_info(self, item: dict) -> None:
        self.selected_lattice_item_name = item.get("name")
        sample = self.latest_monitor_sample or {}
        channels = sample.get("channels", {})
        payload = channels.get(item.get("pv_label"), {}) if item.get("pv_label") else {}
        value = payload.get("value")
        pv = payload.get("pv") or item.get("pv")
        spec = self.live_spec_lookup.get(item.get("pv_label")) if item.get("pv_label") else None
        unit = (getattr(spec, "unit", "") or "")
        if spec is None and item.get("pv_label") and self.lattice_specs is not None:
            spec = spec_index(self.lattice_specs).get(item.get("pv_label"))
            unit = (getattr(spec, "unit", "") or "")
        lines = [
            item.get("name", "device"),
            "",
            "Type: %s" % item.get("element_type"),
            "PV label: %s" % (item.get("pv_label") or "n/a"),
            "PV: %s" % (pv or "n/a"),
            "Unit: %s" % (unit or "n/a"),
            "Live value: %s%s" % (value, (" %s" % unit) if unit else ""),
            "Notes: %s" % item.get("notes", ""),
        ]
        if spec is not None:
            lines.extend(
                [
                    "Tags: %s" % (", ".join(getattr(spec, "tags", ()) or ()) or "n/a"),
                    "Inventory note: %s" % (getattr(spec, "notes", "") or "n/a"),
                ]
            )
        if item.get("element_type") in ("Quadrupole", "Sextupole", "Octupole", "Dipole"):
            lines.extend(
                [
                    "",
                    "Magnet metadata:",
                    "Section: %s" % ((item.get("notes", "").split(" in ", 1)[1]) if " in " in item.get("notes", "") else "ring"),
                    "Power-supply PV mapping comes from the lattice export / inventory build.",
                    "If the live monitor is not polling this magnet family, the live value can be n/a while the PV mapping and metadata are still shown here.",
                ]
            )
        if item.get("pv_label") == "qpd_l4_sigma_x":
            lines.extend(
                [
                    "",
                    "Use with eta_x in L4 to estimate sigma_delta via:",
                    "sigma_x^2 ~= beta_x*epsilon_x + (eta_x*sigma_delta)^2",
                    "Also inspect sigma_y and center drift to see whether the profile monitor itself is moving.",
                ]
            )
        if item.get("element_type") == "RFCavity":
            lines.extend(
                [
                    "",
                    "Relevant cavity history here includes cavity voltage, RF set/readback, and rdFrq499.",
                    "For RF sweeps, compare cavity / RF traces against P1, δₛ, η, and α₀ in the live monitor.",
                ]
            )
        if item.get("name") in ("BPMZ1L2RP", "BPMZ1K3RP", "BPMZ1L4RP", "BPMZ1K1RP"):
            lines.extend(
                [
                    "",
                    "This BPM is part of the 4-BPM bump-feedback average.",
                    "The loop tries to keep the arithmetic mean of those BPM X values close to AKC12VP.",
                ]
            )
            if item.get("name") == "BPMZ1L2RP":
                lines.append("BPMZ1L2RP sits on the L2 / undulator side, so it helps anchor the source-region orbit during the bump-controlled RF sweep.")
        if (item.get("pv_label") or "").startswith("l4_bump_hcorr"):
            lines.extend(
                [
                    "",
                    "This corrector participates in the 4-corrector L4 bump.",
                    "Live bump state is inferred from the set of these currents plus AKC10VP.",
                ]
            )
        if item.get("pv_label", "").endswith("_x") and isinstance(value, (int, float)):
            severity = "linear/green"
            if abs(float(value)) >= BPM_NONLINEAR_MM:
                severity = "nonlinear/red"
            elif abs(float(value)) >= BPM_WARNING_MM:
                severity = "warning/yellow"
            lines.extend(
                [
                    "",
                    "Live orbit interpretation:",
                    "Current X severity: %s" % severity,
                    "Green < %.1f mm, yellow >= %.1f mm, red >= %.1f mm." % (BPM_WARNING_MM, BPM_WARNING_MM, BPM_NONLINEAR_MM),
                ]
            )
        self._set_text_widget(self.lattice_info_text, lines)
        self._draw_lattice_item_history(item)

    def _draw_lattice_item_history(self, item: dict) -> None:
        canvas = getattr(self, "lattice_detail_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = int(canvas.winfo_width() or 360)
        height = int(canvas.winfo_height() or 190)
        trend_data = ((self.latest_monitor_summary or {}).get("trend_data", {}) or {})
        series_payload = []
        mapping = {
            "BPMZ1K1RP": "bump_bpm_k1_mm",
            "BPMZ1L2RP": "bump_bpm_l2_mm",
            "BPMZ1K3RP": "bump_bpm_k3_mm",
            "BPMZ1L4RP": "bump_bpm_l4_mm",
        }
        key = mapping.get(item.get("name"))
        if key and key in trend_data:
            meta = trend_definitions().get(key, {"label": key, "color": "#1565c0"})
            series_payload.append((meta["label"], list(trend_data.get(key, [])), meta["color"]))
        elif item.get("element_type") == "RFCavity":
            for key in ("cavity_voltage_kv", "rf_readback_499mhz_khz", "rf_offset_hz"):
                meta = trend_definitions().get(key, {"label": key, "color": "#1565c0"})
                series_payload.append((meta["label"], list(trend_data.get(key, [])), meta["color"]))
        elif item.get("name") == "QPD00ZL4RP":
            series_payload.append(("QPD00 center [um]", list(trend_data.get("qpd_l4_center_x_avg_um", [])), "#6a1b9a"))
            series_payload.append(("QPD00 σx [mm]", list(trend_data.get("qpd_l4_sigma_x_mm", [])), "#7b1fa2"))
            series_payload.append(("QPD00 σy [mm]", list(trend_data.get("qpd_l4_sigma_y_mm", [])), "#ab47bc"))
        elif item.get("name") == "QPD01ZL2RP":
            series_payload.append(("QPD01 center [um]", list(trend_data.get("qpd_l2_center_x_avg_um", [])), "#8e24aa"))
            series_payload.append(("QPD01 σx [mm]", list(trend_data.get("qpd_l2_sigma_x_mm", [])), "#5e35b1"))
            series_payload.append(("QPD01 σy [mm]", list(trend_data.get("qpd_l2_sigma_y_mm", [])), "#4527a0"))
        elif item.get("name") == "P1 light monitor":
            series_payload.append(("P1 avg", list(trend_data.get("p1_h1_ampl_avg", [])), "#8e24aa"))
            series_payload.append(("P1 live", list(trend_data.get("p1_h1_ampl", [])), "#00acc1"))
        elif item.get("name") == "P3 light monitor":
            series_payload.append(("P3 avg", list(trend_data.get("p3_h1_ampl_avg", [])), "#fb8c00"))
            series_payload.append(("P3 live", list(trend_data.get("p3_h1_ampl", [])), "#f4511e"))
        elif (item.get("pv_label") or "").startswith("l4_bump_hcorr"):
            series_payload.append(("Orbit error [mm]", list(trend_data.get("bump_orbit_error_mm", [])), "#c2185b"))
            series_payload.append(("BPM avg [mm]", list(trend_data.get("bump_bpm_avg_mm", [])), "#00838f"))
        elif item.get("pv_label") in trend_data:
            meta = trend_definitions().get(item.get("pv_label"), {"label": item.get("pv_label"), "color": "#1565c0"})
            series_payload.append((meta["label"], list(trend_data.get(item.get("pv_label"), [])), meta["color"]))
        if not series_payload:
            dynamic_payload = self._history_series_for_label(item.get("pv_label"))
            if dynamic_payload is not None:
                series_payload.append(dynamic_payload)
        if not series_payload:
            canvas.create_rectangle(10, 10, width - 10, height - 10, outline="#cfd8dc")
            canvas.create_text(width / 2, height / 2, text="No live history yet for this device", fill="#90a4ae")
            return
        self._draw_multi_series(canvas, series_payload, 10, 10, width - 10, height - 10, max(20, max(len(values) for _label, values, _color in series_payload)))
        canvas.create_text(width / 2, 12, anchor="n", text="%s live history" % item.get("name", "device"), fill="#37474f", font=("Helvetica", 10, "bold"))
        first_values = [float(value) for value in series_payload[0][1] if isinstance(value, (int, float))]
        if first_values:
            mean = sum(first_values) / len(first_values)
            canvas.create_text(width - 12, height - 10, anchor="se", text="mean %.3g" % mean, fill="#546e7a", font=("Helvetica", 8))
        channels = ((self.latest_monitor_sample or {}).get("channels", {}) or {})
        if item.get("name") == "QPD00ZL4RP":
            self._draw_beam_proxy(
                canvas,
                (self.latest_monitor_summary or {}).get("current", {}).get("qpd_l4_center_x_avg_um"),
                (self.latest_monitor_summary or {}).get("current", {}).get("qpd_l4_sigma_x_mm"),
                (self.latest_monitor_summary or {}).get("current", {}).get("qpd_l4_sigma_y_mm"),
                width - 150,
                24,
                width - 16,
                118,
                "QPD00 beam proxy",
            )
        elif item.get("name") == "QPD01ZL2RP":
            self._draw_beam_proxy(
                canvas,
                (self.latest_monitor_summary or {}).get("current", {}).get("qpd_l2_center_x_avg_um"),
                (channels.get("qpd_l2_sigma_x", {}) or {}).get("value"),
                (channels.get("qpd_l2_sigma_y", {}) or {}).get("value"),
                width - 150,
                24,
                width - 16,
                118,
                "QPD01 beam proxy",
            )

    def _history_series_for_label(self, label):
        if not label:
            return None
        values = []
        for sample in self.monitor_history:
            channel = (sample.get("channels", {}) or {}).get(label, {})
            values.append(channel.get("value"))
        if not any(isinstance(value, (int, float)) for value in values):
            return None
        meta = trend_definitions().get(label, {"label": label, "color": "#1565c0"})
        return (meta["label"], values, meta["color"])

    def _close_lattice_window(self) -> None:
        if self.lattice_window is not None and self.lattice_window.winfo_exists():
            self.lattice_window.destroy()
        self.lattice_window = None
        self.lattice_canvas = None
        self.lattice_info_text = None
        self.lattice_detail_canvas = None
        self.lattice_context = None
        self.lattice_specs = None
        self.lattice_device_items = []
        self.selected_lattice_item_name = None

    def _section_bounds(self, lattice) -> dict:
        bounds = {}
        for element in lattice.elements:
            if not element.section:
                continue
            current = bounds.get(element.section)
            if current is None:
                bounds[element.section] = [element.s_center_m, element.s_center_m]
            else:
                current[0] = min(current[0], element.s_center_m)
                current[1] = max(current[1], element.s_center_m)
        return bounds

    def _s_to_x(self, s_pos: float, lattice, left: int, right: int) -> float:
        if lattice.circumference_m <= 0:
            return left
        return left + (right - left) * float(s_pos) / float(lattice.circumference_m)

    def _element_style(self, element: LatticeElement, row_positions):
        styles = {
            "Monitor": ("#1e88e5", element.family_name, row_positions["bpm"]),
            "Quadrupole": ("#43a047", "", row_positions["quadrupole"]),
            "Sextupole": ("#fdd835", "", row_positions["sextupole"]),
            "Octupole": ("#8e24aa", "", row_positions["octupole"]),
            "Dipole": ("#6d4c41", "", row_positions["dipole"]),
            "RFCavity": ("#c62828", "CAV", row_positions["rf"]),
        }
        return styles.get(element.element_type, ("#90a4ae", "", row_positions["quadrupole"]))

    def _lattice_marker_half_width(self, element: LatticeElement) -> int:
        if element.element_type == "Dipole":
            return 9
        if element.element_type in ("Quadrupole", "Sextupole", "Octupole"):
            return 7
        if element.element_type == "RFCavity":
            return 8
        return 6

    def _element_s_position(self, lattice, family_name: str, fallback: float) -> float:
        for element in lattice.elements:
            if element.family_name == family_name:
                return float(element.s_center_m)
        return float(fallback)

    def _live_marker_style(self, element: LatticeElement, live_value, default_color: str):
        if element.element_type != "Monitor":
            return default_color, ""
        try:
            value = abs(float(live_value))
        except (TypeError, ValueError):
            return "#90caf9", "#1e88e5"
        if value >= BPM_NONLINEAR_MM:
            return "#ef9a9a", "#b71c1c"
        if value >= BPM_WARNING_MM:
            return "#ffe082", "#f57f17"
        return "#a5d6a7", "#2e7d32"

    def _open_theory_window(self) -> None:
        if self.theory_window is not None and self.theory_window.winfo_exists():
            self.theory_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB Theory And Derived-Value Pipeline")
        self._place_window_on_screen(window, 900, 760, x=110, y=100, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word")
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")
        self.theory_window = window
        self.theory_window_text = text
        self._update_theory_window(self.latest_monitor_summary)
        window.protocol("WM_DELETE_WINDOW", self._close_theory_window)

    def _update_theory_window(self, summary) -> None:
        if self.theory_window is None or not self.theory_window.winfo_exists():
            return
        theory_lines = []
        if summary is None:
            theory_lines = ["No live monitor summary yet.", "", "Start Live Monitor to populate the theory pipeline with live values."]
        else:
            for section in build_theory_sections(summary):
                theory_lines.append(section["title"])
                theory_lines.append("")
                for eq in section.get("equations", []):
                    theory_lines.append(eq)
                if section.get("equations"):
                    theory_lines.append("")
                for line in section.get("lines", []):
                    theory_lines.append(line)
                theory_lines.append("")
        self._set_text_widget(self.theory_window_text, theory_lines)

    def _close_theory_window(self) -> None:
        if self.theory_window is not None and self.theory_window.winfo_exists():
            self.theory_window.destroy()
        self.theory_window = None
        self.theory_window_text = None

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        try:
            if self.monitor_stop_event is not None:
                self.monitor_stop_event.set()
            if self.bump_lab_stop_event is not None:
                self.bump_lab_stop_event.set()
            if self.stage0_stop_event is not None:
                self.stage0_stop_event.set()
        except Exception:
            pass
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _open_ssmb_study_window(self) -> None:
        if self.ssmb_study_window is not None and self.ssmb_study_window.winfo_exists():
            self.ssmb_study_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB Oscillation / Resonance Study")
        self._place_window_on_screen(window, 1480, 980, x=95, y=85, relative_to_root=True)
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=0)
        frame.rowconfigure(2, weight=1)
        top = ttk.Frame(frame)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(top, text="Open Theory Window", command=self._open_theory_window).pack(side="left")
        ttk.Button(top, text="Open Oscillation Study", command=self._open_oscillation_window).pack(side="left", padx=6)
        ttk.Button(top, text="Open Lattice View", command=self._open_lattice_window).pack(side="left", padx=6)
        text = tk.Text(frame, wrap="word", height=18)
        text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 8))
        text.configure(state="disabled")
        plots = ttk.Frame(frame)
        plots.grid(row=2, column=0, columnspan=2, sticky="nsew")
        plots.columnconfigure(0, weight=1)
        plots.columnconfigure(1, weight=1)
        plots.rowconfigure(0, weight=1)
        plots.rowconfigure(1, weight=1)
        canvases = []
        for idx in range(4):
            canvas = tk.Canvas(plots, bg="white", height=260, highlightthickness=1, highlightbackground="#cfd8dc")
            canvas.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=4, pady=4)
            canvases.append(canvas)
        self.ssmb_study_window = window
        self.ssmb_study_text = text
        self.ssmb_study_canvases = canvases
        self._update_ssmb_study_window(self.latest_monitor_summary)
        window.protocol("WM_DELETE_WINDOW", self._close_ssmb_study_window)

    def _close_ssmb_study_window(self) -> None:
        if self.ssmb_study_window is not None and self.ssmb_study_window.winfo_exists():
            self.ssmb_study_window.destroy()
        self.ssmb_study_window = None
        self.ssmb_study_text = None
        self.ssmb_study_canvases = []

    def _update_ssmb_study_window(self, summary) -> None:
        if self.ssmb_study_window is None or not self.ssmb_study_window.winfo_exists():
            return
        safe_summary = summary or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        current = safe_summary.get("current", {}) or {}
        sweep = safe_summary.get("rf_sweep_metrics", {}) or {}
        oscillation = safe_summary.get("oscillation_study", {}) or {}
        resonance = safe_summary.get("ssmb_resonance", {}) or {}
        lines = [
            "SSMB Oscillation / Resonance Study",
            "",
            "This window is focused on the actual SSMB experiment observables: P1/P3, RF, δₛ, η, α₀, beam energy, momentum spread, and whether the observed slow oscillation looks compatible with a fast machine resonance or instead with slow control / thermal modulation.",
            "",
            "Live observed quantities",
            "P1 avg / P3 avg: %s / %s" % (current.get("p1_h1_ampl_avg"), current.get("p3_h1_ampl_avg")),
            "Observed P1 period: %s" % self._format_short_duration(oscillation.get("dominant_period_s")),
            "Observed P1 frequency: %s Hz" % self._format_plot_value(oscillation.get("dominant_frequency_hz")),
            "Autocorr period: %s" % self._format_short_duration(oscillation.get("autocorr_period_s")),
            "Certainty: %s" % oscillation.get("certainty", "n/a"),
            "",
            "Derived machine quantities",
            "δₛ: %s" % self._format_plot_value(current.get("delta_l4_bpm_first_order")),
            "η: %s" % self._format_plot_value(sweep.get("phase_slip_factor_eta")),
            "α₀ legacy / BPM: %s / %s" % (self._format_plot_value(current.get("legacy_alpha0_corrected")), self._format_plot_value(sweep.get("alpha0_from_bpm_eta"))),
            "Beam energy / σδ: %s MeV / %s" % (self._format_plot_value(current.get("beam_energy_from_bpm_mev")), self._format_plot_value(current.get("qpd_l4_sigma_delta_first_order"))),
            "",
            "Resonance sanity check",
            "Synchrotron period from Qs: %s" % self._format_short_duration(resonance.get("synchrotron_period_s")),
            "Observed P1 period / Qs period ratio: %s" % self._format_plot_value(resonance.get("period_ratio_to_qs")),
            resonance.get("message", "No resonance interpretation available yet."),
            "",
            "Caveat",
            "This is a live heuristic study. Error bars and certainty here are based on rolling FFT/autocorrelation / correlation strength, not a full offline statistical model.",
        ]
        self._set_text_widget(self.ssmb_study_text, lines)
        trend_data = safe_summary.get("trend_data", {}) or {}
        plot_defs = [
            ("P1/P3 vs RF", [("P1 avg", self._prepare_plot_series(list(trend_data.get("p1_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"), ("P3 avg", self._prepare_plot_series(list(trend_data.get("p3_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#fb8c00"), ("Δf_RF [Hz]", self._prepare_plot_series(list(trend_data.get("rf_offset_hz", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#1e88e5")]),
            ("P1 vs δₛ / E", [("P1 avg", self._prepare_plot_series(list(trend_data.get("p1_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"), ("δₛ", self._prepare_plot_series(list(trend_data.get("delta_s", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#43a047"), ("E_BPM [MeV]", self._prepare_plot_series(list(trend_data.get("beam_energy_mev", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#00897b")]),
            ("α₀ / η chain", [("α₀ legacy", self._prepare_plot_series(list(trend_data.get("legacy_alpha0", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#ef6c00"), ("α₀ BPM", self._prepare_plot_series(list(trend_data.get("bpm_alpha0", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"), ("σδ", self._prepare_plot_series(list(trend_data.get("sigma_delta", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#6d4c41")]),
            ("Slow-driver context", [("KW13 temp", self._prepare_plot_series(list(trend_data.get("climate_kw13_return_temp_c", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#00838f"), ("QPD00 center", self._prepare_plot_series(list(trend_data.get("qpd_l4_center_x_avg_um", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#6a1b9a"), ("Bump error", self._prepare_plot_series(list(trend_data.get("bump_orbit_error_mm", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#c2185b")]),
        ]
        for canvas, (title, payload) in zip(self.ssmb_study_canvases, plot_defs):
            canvas.delete("all")
            width = int(canvas.winfo_width() or 520)
            height = int(canvas.winfo_height() or 220)
            actual_samples = max((len(values) for _series_label, values, _color in payload), default=0)
            self._draw_multi_series(
                canvas,
                payload,
                10,
                24,
                width - 10,
                height - 10,
                max(20, self._window_samples_for_seconds(LONG_STUDY_PLOT_WINDOW_S)),
                actual_samples=actual_samples,
            )
            canvas.create_text(width / 2, 6, anchor="n", text=title, fill="#37474f", font=("Helvetica", 10, "bold"))

    def _open_bump_lab_window(self) -> None:
        if self.bump_lab_window is not None and self.bump_lab_window.winfo_exists():
            self.bump_lab_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("Experimental Bump Lab")
        self._place_window_on_screen(window, 1700, 980, x=85, y=75, relative_to_root=True)
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=0)
        outer.rowconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)

        ttk.Label(left, text="Highly experimental bump investigation / controller lab.", foreground="#b71c1c", wraplength=320).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="Poll interval [s]").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(left, textvariable=self.bump_lab_poll_var, width=10).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(left, text="Feedback BPMs").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row = 3
        for pv_name, var in self.bump_lab_bpm_vars.items():
            ttk.Checkbutton(left, text=pv_name, variable=var).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1

        ttk.Label(left, text="Corrector factors").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        for pv_name, var in self.bump_lab_steerer_vars.items():
            ttk.Label(left, text=pv_name).grid(row=row, column=0, sticky="w")
            ttk.Entry(left, textvariable=var, width=12).grid(row=row, column=1, sticky="w")
            row += 1

        button_row = ttk.Frame(left)
        button_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(button_row, text="Refresh Snapshot", command=self._refresh_bump_lab_snapshot).pack(side="left")
        ttk.Button(button_row, text="Start Observe Loop", command=self._start_bump_lab_observer).pack(side="left", padx=4)
        ttk.Button(button_row, text="Stop Loop", command=self._stop_bump_lab_loop).pack(side="left", padx=4)
        ttk.Button(button_row, text="Run Experimental Controller", command=self._start_bump_lab_controller).pack(side="left", padx=4)
        ttk.Button(button_row, text="Open Theory Window", command=self._open_theory_window).pack(side="left", padx=4)
        row += 1

        ttk.Label(right, text="Experimental bump-lab live summary").grid(row=0, column=0, columnspan=2, sticky="w")
        self.bump_lab_summary_text = tk.Text(right, wrap="word", height=12)
        self.bump_lab_summary_text.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.bump_lab_summary_text.configure(state="disabled")
        ttk.Label(outer, text="Live bump and undulator-side trends").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        plot_frame = ttk.Frame(outer)
        plot_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.columnconfigure(1, weight=1)
        plot_frame.rowconfigure(0, weight=1)
        bump_canvas = tk.Canvas(plot_frame, bg="white", height=360, highlightthickness=1, highlightbackground="#cfd8dc")
        bump_canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        und_canvas = tk.Canvas(plot_frame, bg="white", height=360, highlightthickness=1, highlightbackground="#cfd8dc")
        und_canvas.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.bump_lab_plot_canvases = {"bump": bump_canvas, "undulator": und_canvas}
        ttk.Label(right, text="Notebook-export source reference").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.bump_lab_source_text = tk.Text(right, wrap="none", height=18)
        self.bump_lab_source_text.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.bump_lab_source_text.configure(state="disabled")
        source_path = SSMB_ROOT / "references" / "OrbitControlL4Bump_test_20250307.py"
        try:
            self._set_text_widget(self.bump_lab_source_text, source_path.read_text().splitlines())
        except Exception as exc:
            self._set_text_widget(self.bump_lab_source_text, ["Could not load reference source: %s" % exc])

        self.bump_lab_window = window
        self._refresh_bump_lab_snapshot()
        window.protocol("WM_DELETE_WINDOW", self._close_bump_lab_window)

    def _close_bump_lab_window(self) -> None:
        if self.bump_lab_window is not None and self.bump_lab_window.winfo_exists():
            self.bump_lab_window.destroy()
        self.bump_lab_window = None
        self.bump_lab_summary_text = None
        self.bump_lab_source_text = None
        self.bump_lab_plot_canvases = {}

    def _selected_bump_lab_bpms(self):
        return [pv for pv, var in self.bump_lab_bpm_vars.items() if var.get()]

    def _selected_bump_lab_steerers(self):
        result = []
        for pv, var in self.bump_lab_steerer_vars.items():
            try:
                factor = float(var.get())
            except Exception:
                factor = 0.0
            result.append((pv, factor))
        return result

    def _refresh_bump_lab_snapshot(self) -> None:
        summary = self.latest_monitor_summary or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        self._update_bump_lab({"summary": summary, "mode": "snapshot"})

    def _update_bump_lab(self, payload: dict) -> None:
        if self.bump_lab_window is None or not self.bump_lab_window.winfo_exists():
            return
        summary = payload.get("summary") or self.latest_monitor_summary or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
        bump_state = summary.get("bump_state", {})
        current = summary.get("current", {})
        lines = [
            "Mode: %s" % payload.get("mode", "snapshot"),
            "",
            "Observe loop = passive polling only. Use it to watch the external bumper script without writing PVs.",
            "",
            "Feedback state: %s" % bump_state.get("state_label", "unknown"),
            "RF ctrl enable: %s" % bump_state.get("rf_frequency_control_enable"),
            "Gain: %s" % current.get("bump_feedback_gain"),
            "Reference orbit: %s mm" % current.get("bump_feedback_ref_mm"),
            "Deadband: %s mm" % current.get("bump_feedback_deadband_mm"),
            "4-BPM average: %s mm" % current.get("bump_bpm_avg_mm"),
            "Orbit error: %s mm" % current.get("bump_orbit_error_mm"),
            "Estimated step: %s" % current.get("bump_step_estimate"),
            "",
            "Selected feedback BPMs: %s" % (", ".join(self._selected_bump_lab_bpms()) or "none"),
            "Selected correctors: %s" % ", ".join("%s * %s" % (pv, factor) for pv, factor in self._selected_bump_lab_steerers()),
            "",
            "P1 avg: %s" % current.get("p1_h1_ampl_avg"),
            "P1 std: %s" % current.get("p1_h1_ampl_dev"),
            "P1avg vs bump |I| slope: %s" % ((summary.get("bump_monitor") or {}).get("p1_avg_vs_bump_strength") or {}).get("slope"),
            "P1avg vs bump error slope: %s" % ((summary.get("bump_monitor") or {}).get("p1_avg_vs_bump_error") or {}).get("slope"),
            "Bump quality score: %.1f (%s)" % (
                float((((summary.get("bump_monitor") or {}).get("quality_score") or {}).get("score") or 0.0)),
                (((summary.get("bump_monitor") or {}).get("quality_score") or {}).get("status") or "n/a"),
            ),
            "δs: %s" % current.get("delta_l4_bpm_first_order"),
            "σδ proxy: %s" % current.get("qpd_l4_sigma_delta_first_order"),
            "BPMZ1L2RP (undulator-side anchor): %s mm" % current.get("bump_bpm_l2_mm"),
            "QPD01 center X avg: %s um" % current.get("qpd_l2_center_x_avg_um"),
            "",
            "Interpretation:",
            "The recovered controller is a scalar orbit-lock loop: it drives the average of the 4 selected BPMs toward AKC12VP.",
            "Because BPMZ1L2RP is near the L2 / undulator side and the others are spread through K3 and L4, this is a global closed-orbit constraint, not a local undulator-only correction.",
        ]
        self._set_text_widget(self.bump_lab_summary_text, lines)
        self._draw_bump_lab_plots(summary)

    def _draw_bump_lab_plots(self, summary) -> None:
        trend_data = (summary or {}).get("trend_data", {})
        bump_canvas = (self.bump_lab_plot_canvases or {}).get("bump")
        und_canvas = (self.bump_lab_plot_canvases or {}).get("undulator")
        if bump_canvas is not None:
            width = int(bump_canvas.winfo_width() or 420)
            height = int(bump_canvas.winfo_height() or 210)
            payload = [
                ("Orbit error [mm]", self._prepare_plot_series(list(trend_data.get("bump_orbit_error_mm", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#c2185b"),
                ("BPM avg [mm]", self._prepare_plot_series(list(trend_data.get("bump_bpm_avg_mm", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#00838f"),
                ("P1 avg", self._prepare_plot_series(list(trend_data.get("p1_h1_ampl_avg", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"),
            ]
            actual_samples = max((len(values) for _series_label, values, _color in payload), default=0)
            self._draw_multi_series(
                bump_canvas,
                payload,
                10,
                24,
                width - 10,
                height - 10,
                max(20, self._window_samples_for_seconds(LONG_STUDY_PLOT_WINDOW_S)),
                actual_samples=actual_samples,
            )
            bump_canvas.create_text(width / 2, 6, anchor="n", text="Bump loop vs P1", fill="#37474f", font=("Helvetica", 10, "bold"))
        if und_canvas is not None:
            width = int(und_canvas.winfo_width() or 420)
            height = int(und_canvas.winfo_height() or 210)
            payload = [
                ("BPMZ1L2 [mm]", self._prepare_plot_series(list(trend_data.get("bump_bpm_l2_mm", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#1565c0"),
                ("δs", self._prepare_plot_series(list(trend_data.get("delta_s", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#43a047"),
                ("σδ", self._prepare_plot_series(list(trend_data.get("sigma_delta", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#6d4c41"),
                ("QPD01 center [um]", self._prepare_plot_series(list(trend_data.get("qpd_l2_center_x_avg_um", [])), window_seconds=LONG_STUDY_PLOT_WINDOW_S, max_points=LONG_STUDY_PLOT_MAX_POINTS), "#8e24aa"),
            ]
            actual_samples = max((len(values) for _series_label, values, _color in payload), default=0)
            self._draw_multi_series(
                und_canvas,
                payload,
                10,
                24,
                width - 10,
                height - 10,
                max(20, self._window_samples_for_seconds(LONG_STUDY_PLOT_WINDOW_S)),
                actual_samples=actual_samples,
            )
            und_canvas.create_text(width / 2, 6, anchor="n", text="Undulator-side anchor and spread proxies", fill="#37474f", font=("Helvetica", 10, "bold"))

    def _start_bump_lab_observer(self) -> None:
        if self.bump_lab_stop_event is not None:
            self._append_log("Experimental bump-lab loop is already running.")
            return
        self.bump_lab_stop_event = threading.Event()
        self.bump_lab_thread = threading.Thread(target=self._bump_lab_loop, args=(False,), daemon=True)
        self.bump_lab_thread.start()
        self._append_log("Started experimental bump-lab observer.")

    def _start_bump_lab_controller(self) -> None:
        if not self.allow_writes or self.safe_mode_var.get():
            self._append_log("Experimental bump controller is blocked. Disable Safe / read-only mode first.")
            return
        if self.bump_lab_stop_event is not None:
            self._append_log("Experimental bump-lab loop is already running.")
            return
        lines = [
            "This is highly experimental.",
            "",
            "It will write to these steerer PVs:",
        ]
        lines.extend(["- %s" % pv for pv, _factor in self._selected_bump_lab_steerers()])
        lines.extend(
            [
                "",
                "Using BPMs:",
            ]
        )
        lines.extend(["- %s" % pv for pv in self._selected_bump_lab_bpms()])
        lines.extend(
            [
                "",
                "The control law is the notebook-style scalar loop:",
                "step = gain * (ref - avg_bpm) if outside deadband",
            ]
        )
        if not messagebox.askokcancel("Run Experimental Bump Controller", "\n".join(lines)):
            self._append_log("Experimental bump controller cancelled.")
            return
        self.bump_lab_stop_event = threading.Event()
        self.bump_lab_thread = threading.Thread(target=self._bump_lab_loop, args=(True,), daemon=True)
        self.bump_lab_thread.start()
        self._append_log("Started experimental bump controller.")

    def _stop_bump_lab_loop(self) -> None:
        if self.bump_lab_stop_event is None:
            self._append_log("Experimental bump-lab loop is not running.")
            return
        self.bump_lab_stop_event.set()

    def _bump_lab_loop(self, write_enabled: bool) -> None:
        try:
            interval = max(0.1, float(self.bump_lab_poll_var.get()))
            adapter = EpicsAdapter(timeout=float(self.timeout_var.get())) if write_enabled else ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            while self.bump_lab_stop_event is not None and not self.bump_lab_stop_event.is_set():
                bpm_values = []
                for bpm_pv in self._selected_bump_lab_bpms():
                    value = adapter.get(bpm_pv, None)
                    if value is not None:
                        bpm_values.append(float(value))
                gain = adapter.get("AKC11VP", None)
                ref = adapter.get("AKC12VP", None)
                deadband = adapter.get("AKC13VP", None)
                rf_ctrl = adapter.get("MCLKHGP:ctrl:enable", None)
                avg_bpm = sum(bpm_values) / len(bpm_values) if bpm_values else None
                error = None if avg_bpm is None or ref is None else float(ref) - float(avg_bpm)
                step = None
                if error is not None and gain is not None:
                    if deadband is None or abs(error) > abs(float(deadband)):
                        step = float(gain) * error
                if write_enabled and step not in (None, 0.0):
                    for pv, factor in self._selected_bump_lab_steerers():
                        old = adapter.get(pv, None)
                        if old is None:
                            continue
                        adapter.put(pv, float(old) + step * factor)
                summary = self.latest_monitor_summary or summarize_live_monitor([], extra_candidate_keys=self._extra_oscillation_candidates())
                self.queue.put({"kind": "bump_lab_update", "summary": summary, "mode": "controller" if write_enabled else "observe"})
                if self.bump_lab_stop_event.wait(interval):
                    break
        except Exception as exc:
            self.queue.put("Experimental bump-lab failed: %s" % exc)
        finally:
            self.queue.put({"kind": "bump_lab_done"})

    def _match_spec_label(self, specs, element: LatticeElement):
        if element.element_type == "RFCavity":
            return "cavity_voltage_kv"
        family = element.family_name.lower()
        candidates = [family, family + "_x", family + "_y"]
        for spec in specs:
            if spec.label in candidates:
                return spec.label
        return None

    def _match_spec_pv(self, specs, element: LatticeElement):
        label = self._match_spec_label(specs, element)
        if label is None:
            return None
        for spec in specs:
            if spec.label == label:
                return spec.pv
        return None

    def _refresh_inventory(self) -> None:
        try:
            config = self._collect_logger_config(allow_writes=False)
            _, specs = build_specs(config)
        except Exception as exc:
            self._set_inventory_text(["Could not build inventory: %s" % exc])
            return
        self.live_spec_lookup = spec_index(specs)
        lines = inventory_overview_lines(specs)
        try:
            estimate_bytes = estimate_passive_session_bytes(specs, config.duration_seconds, config.sample_hz)
            heavy_channels = estimate_sample_breakdown(specs)[:8]
            disk = shutil.disk_usage(config.output_root if config.output_root.exists() else config.output_root.parent)
            lines.extend(
                [
                    "",
                    "Estimated passive-session size: %.2f MB" % (estimate_bytes / (1024.0 * 1024.0)),
                    "Free space at output root: %.2f GB" % (disk.free / (1024.0 * 1024.0 * 1024.0)),
                    "",
                    "Heaviest logged channels per sample:",
                ]
            )
            for item in heavy_channels:
                lines.append("- %s | %s | %.1f kB/sample" % (item["label"], item["kind"], float(item["bytes_per_sample"]) / 1024.0))
        except Exception:
            pass
        self._set_inventory_text(lines)

    def _run_stage0(self) -> None:
        config = self._collect_logger_config(allow_writes=False)
        self._run_in_worker(self._run_stage0_worker, config)

    def _run_stage0_worker(self, config: LoggerConfig) -> None:
        session_dir = run_stage0_logger(config, progress_callback=self._emit, sample_callback=self._emit_bpm_status)
        self._emit("Stage 0 log saved to: %s" % session_dir)

    def _start_manual_stage0(self) -> None:
        if self.stage0_stop_event is not None:
            self._append_log("Manual logging is already running.")
            return
        config = self._collect_logger_config(allow_writes=False)
        config = LoggerConfig(
            duration_seconds=24.0 * 3600.0,
            sample_hz=config.sample_hz,
            timeout_seconds=config.timeout_seconds,
            output_root=config.output_root,
            lattice_export=config.lattice_export,
            safe_mode=True,
            allow_writes=False,
            include_bpm_buffer=config.include_bpm_buffer,
            include_candidate_bpm_scalars=config.include_candidate_bpm_scalars,
            include_ring_bpm_scalars=config.include_ring_bpm_scalars,
            include_quadrupoles=config.include_quadrupoles,
            include_sextupoles=config.include_sextupoles,
            include_octupoles=config.include_octupoles,
            session_label=config.session_label,
            operator_note=config.operator_note,
            extra_pvs=config.extra_pvs,
            extra_optional_pvs=config.extra_optional_pvs,
        )
        self.stage0_stop_event = threading.Event()
        self.start_manual_button.state(["disabled"])
        self.stop_manual_button.state(["!disabled"])
        self._append_log("Starting manual passive logging. Use Stop Manual Log to finish and flush outputs.")
        self._run_in_worker(self._run_stage0_manual_worker, config)

    def _stop_manual_stage0(self) -> None:
        if self.stage0_stop_event is None:
            self._append_log("No manual logging task is currently running.")
            return
        self._append_log("Manual stop requested. Waiting for the current sample to finish.")
        self.stage0_stop_event.set()

    def _run_stage0_manual_worker(self, config: LoggerConfig) -> None:
        try:
            session_dir = run_stage0_logger(
                config,
                progress_callback=self._emit,
                sample_callback=self._emit_bpm_status,
                stop_event=self.stage0_stop_event,
                session_prefix="ssmb_manual",
                extra_metadata={"manual_stop_mode": True, "started_from_gui": True},
            )
            self._emit("Manual log saved to: %s" % session_dir)
        finally:
            self.queue.put({"kind": "manual_stage0_done"})

    def _read_live_rf(self) -> None:
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
        except Exception as exc:
            self._append_log("Live RF read failed: %s" % exc)
            return
        if value is None:
            self._append_log("Live RF read failed for %s." % RF_PV_NAME)
            return
        text = "%.6f" % float(value)
        self.center_rf_var.set(text)
        self._append_log("Read live RF %s = %s" % (RF_PV_NAME, text))

    def _build_sweep_runtime(self) -> SweepRuntimeConfig:
        config = self._collect_logger_config(allow_writes=True)
        plan = build_plan_from_hz(
            center_rf_pv=float(self.center_rf_var.get()),
            delta_min_hz=float(self.delta_min_hz_var.get()),
            delta_max_hz=float(self.delta_max_hz_var.get()),
            n_points=int(self.points_var.get()),
            settle_seconds=float(self.settle_var.get()),
            samples_per_point=int(self.samples_per_point_var.get()),
            sample_spacing_seconds=float(self.sample_spacing_var.get()),
        )
        return SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=True)

    def _preview_sweep(self) -> None:
        try:
            runtime = self._build_sweep_runtime()
        except Exception as exc:
            self._append_log("RF sweep preview failed: %s" % exc)
            return
        current_rf = None
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
            current_rf = float(value) if value is not None else None
        except Exception:
            current_rf = None
        lines = preview_lines(runtime.plan, current_rf)
        try:
            _, specs = build_specs(runtime.logger_config)
            estimate_bytes = estimate_sweep_session_bytes(specs, runtime.plan)
            disk = shutil.disk_usage(runtime.logger_config.output_root if runtime.logger_config.output_root.exists() else runtime.logger_config.output_root.parent)
            lines.extend(
                [
                    "",
                    "Estimated sweep size: %.2f MB" % (estimate_bytes / (1024.0 * 1024.0)),
                    "Free space at output root: %.2f GB" % (disk.free / (1024.0 * 1024.0 * 1024.0)),
                ]
            )
        except Exception:
            pass
        self._set_inventory_text(lines)
        self._append_log("RF sweep preview updated.")

    def _run_sweep(self) -> None:
        if not self.allow_writes:
            self._append_log("RF sweep writes are disabled. Start the GUI with --allow-writes.")
            return
        if self.safe_mode_var.get():
            self._append_log("RF sweep writes are blocked because Safe / read-only mode is enabled.")
            return
        runtime = self._build_sweep_runtime()
        current_rf = None
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
            current_rf = float(value) if value is not None else None
        except Exception:
            current_rf = None
        lines = preview_lines(runtime.plan, current_rf)
        preview_text = "This action will write to EPICS PVs.\n\nDouble-check units carefully: the RF preview below is in Hz, while %s uses PV units where 1 unit = 1000 Hz.\n\n%s" % (RF_PV_NAME, "\n".join(lines))
        if not messagebox.askokcancel("Confirm RF Sweep Writes", preview_text):
            self._append_log("RF sweep cancelled by user.")
            return
        self._run_in_worker(self._run_sweep_worker, runtime)

    def _run_sweep_worker(self, runtime: SweepRuntimeConfig) -> None:
        session_dir = run_rf_sweep_session(runtime, progress_callback=self._emit, sample_callback=self._emit_bpm_status)
        self._emit("RF sweep log saved to: %s" % session_dir)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GUI for SSMB Stage 0 logging and conservative RF sweeps.")
    parser.add_argument("--safe-mode", action="store_true", help="Compatibility flag. The GUI already starts with Safe / read-only mode enabled by default.")
    parser.add_argument("--unsafe-start", action="store_true", help="Start with Safe / read-only mode disabled. RF writes still require explicit confirmation in the GUI.")
    parser.add_argument("--allow-writes", action="store_true", help="Deprecated compatibility flag. The GUI can enable writes from inside the window when Safe / read-only mode is turned off.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if tk is None:
        raise SystemExit("tkinter is unavailable; cannot start the SSMB GUI.")
    print("[ssmb_gui] main(): parsing arguments", flush=True)
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    print("[ssmb_gui] main(): creating Tk root", flush=True)
    root = tk.Tk()
    print("[ssmb_gui] main(): building SSMBGui", flush=True)
    app = SSMBGui(root, allow_writes=True, start_safe_mode=not bool(args.unsafe_start))
    sigint_count = {"count": 0}

    def handle_sigint(_signum=None, _frame=None):
        sigint_count["count"] += 1
        print("[ssmb_gui] SIGINT received, shutting down (count=%d)" % sigint_count["count"], flush=True)
        if sigint_count["count"] >= 2:
            print("[ssmb_gui] forcing exit after repeated SIGINT", flush=True)
            os._exit(130)
        try:
            root.after(0, app.shutdown)
        except Exception:
            app.shutdown()

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except Exception:
        pass
    try:
        root.protocol("WM_DELETE_WINDOW", app.shutdown)
    except Exception:
        pass
    root.deiconify()
    print("[ssmb_gui] main(): entering Tk mainloop", flush=True)
    try:
        root.mainloop()
    except tk.TclError:
        print("[ssmb_gui] main(): Tk closed", flush=True)
        return 0
    except KeyboardInterrupt:
        print("[ssmb_gui] main(): KeyboardInterrupt", flush=True)
        app.shutdown()
    print("[ssmb_gui] main(): exit", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
