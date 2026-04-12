from __future__ import annotations

import argparse
import collections
import queue
import shutil
import threading
import time
from pathlib import Path
from typing import Optional, Sequence

from .config import LoggerConfig, SSMB_ROOT, parse_labeled_pvs
from .epics_io import EpicsUnavailableError, ReadOnlyEpicsAdapter
from .lattice import LatticeElement
from .live_monitor import (
    build_monitor_sections,
    build_theory_sections,
    format_channel_snapshot,
    format_monitor_summary,
    summarize_live_monitor,
    trend_definitions,
)
from .log_now import BPM_NONLINEAR_MM, BPM_WARNING_MM, build_specs, estimate_passive_session_bytes, inventory_overview_lines, run_stage0_logger
from .sweep import RF_PV_NAME, SweepRuntimeConfig, build_plan_from_hz, estimate_sweep_session_bytes, preview_lines, run_rf_sweep_session

try:  # pragma: no cover - depends on host GUI packages
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on host GUI packages
    tk = None
    filedialog = None
    messagebox = None
    ttk = None


def _parse_text_mapping(text: str) -> dict[str, str]:
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return parse_labeled_pvs(items)


class SSMBGui:
    def __init__(self, root: "tk.Tk", allow_writes: bool = True, start_safe_mode: bool = True):
        self.root = root
        self.allow_writes = allow_writes
        self.start_safe_mode = start_safe_mode
        self.queue: "queue.Queue[object]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_stop_event: Optional[threading.Event] = None
        self.monitor_history = collections.deque(maxlen=120)
        self.monitor_window: Optional["tk.Toplevel"] = None
        self.theory_window: Optional["tk.Toplevel"] = None
        self.lattice_window: Optional["tk.Toplevel"] = None
        self.latest_monitor_sample = None
        self.latest_monitor_summary = None
        self.lattice_device_items = []
        self.stage0_stop_event: Optional[threading.Event] = None
        self._build_vars()
        self._build_ui()
        self._apply_profile()
        self._refresh_inventory()
        self._open_monitor_window()
        self.root.after(100, self._drain_queue)

    def _build_vars(self) -> None:
        self.duration_var = tk.StringVar(value="60")
        self.sample_hz_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="0.5")
        self.label_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
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

    def _build_ui(self) -> None:
        self.root.title("SSMB Experiment Stage 0 / RF Sweep")
        self.root.geometry("1380x900")

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        control = ttk.Frame(outer)
        control.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        notebook = ttk.Notebook(control)
        notebook.pack(fill="both", expand=False)

        monitor_frame = ttk.Frame(notebook, padding=8)
        logger_frame = ttk.Frame(notebook, padding=8)
        sweep_frame = ttk.Frame(notebook, padding=8)
        notebook.add(monitor_frame, text="Live Monitor")
        notebook.add(logger_frame, text="Stage 0 Logger")
        notebook.add(sweep_frame, text="RF Sweep")

        self._build_monitor_tab(monitor_frame)
        self._build_logger_tab(logger_frame)
        self._build_sweep_tab(sweep_frame)

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

        ttk.Checkbutton(frame, text="Safe / read-only mode", variable=self.safe_mode_var, command=self._update_write_controls).grid(row=row, column=0, columnspan=2, sticky="w")
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
        ttk.Button(button_row, text="Run Stage 0 Log", command=self._run_stage0).pack(side="left", padx=6)
        self.start_manual_button = ttk.Button(button_row, text="Start Manual Log", command=self._start_manual_stage0)
        self.start_manual_button.pack(side="left")
        self.stop_manual_button = ttk.Button(button_row, text="Stop Manual Log", command=self._stop_manual_stage0)
        self.stop_manual_button.pack(side="left", padx=6)
        self.stop_manual_button.state(["disabled"])

    def _build_monitor_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        info = "Read-only live SSMB monitor. Use this before the experiment or during another operator's RF sweep to preview the same observables without saving data."
        ttk.Label(frame, text=info, wraplength=380, justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        ttk.Label(frame, text="Monitor interval [s]").grid(row=row, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.monitor_interval_var, width=12).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 8))
        self.start_monitor_button = ttk.Button(button_row, text="Start Live Monitor", command=self._start_monitor)
        self.start_monitor_button.pack(side="left")
        self.stop_monitor_button = ttk.Button(button_row, text="Stop Live Monitor", command=self._stop_monitor)
        self.stop_monitor_button.pack(side="left", padx=6)
        self.stop_monitor_button.state(["disabled"])
        ttk.Button(button_row, text="Reset Monitor Baseline", command=self._reset_monitor_baseline).pack(side="left")
        ttk.Button(button_row, text="Open Monitor Window", command=self._open_monitor_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open Theory Window", command=self._open_theory_window).pack(side="left", padx=6)
        ttk.Button(button_row, text="Open Lattice View", command=self._open_lattice_window).pack(side="left")
        row += 1
        ttk.Label(frame, text="Live SSMB summary").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        self.monitor_summary_text = tk.Text(frame, wrap="word", height=18)
        self.monitor_summary_text.grid(row=row, column=0, columnspan=3, sticky="nsew")
        self.monitor_summary_text.configure(state="disabled")
        row += 1
        ttk.Label(frame, text="Current channel snapshot").grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 0))
        row += 1
        self.monitor_channels_text = tk.Text(frame, wrap="none", height=16)
        self.monitor_channels_text.grid(row=row, column=0, columnspan=3, sticky="nsew")
        self.monitor_channels_text.configure(state="disabled")
        frame.rowconfigure(row - 1, weight=1)
        frame.columnconfigure(2, weight=1)

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

    def _preset_low_alpha(self) -> None:
        self.label_var.set("low_alpha")
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.note_var.set("Low-alpha full passive logging")
        self._toggle_heavy_mode()

    def _preset_bump(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.note_var.set("Set bump state externally before starting this passive log")
        self._toggle_heavy_mode()

    def _preset_sweep(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.sample_hz_var.set("1")
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
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", "\n".join(lines))
        widget.configure(state="disabled")

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
                    elif message.get("kind") == "monitor_done":
                        self.monitor_stop_event = None
                        self.start_monitor_button.state(["!disabled"])
                        self.stop_monitor_button.state(["disabled"])
                        self._append_log("Live monitor stopped.")
                else:
                    self._append_log(str(message))
            except Exception as exc:
                self._append_log("GUI update failed: %s" % exc)
        self.root.after(100, self._drain_queue)

    def _emit(self, message: str) -> None:
        self.queue.put(message)

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
            if self.monitor_window is not None and self.monitor_window.winfo_exists():
                summary_widget = getattr(self, "monitor_window_summary_text", None)
                channel_widget = getattr(self, "monitor_window_channels_text", None)
                if summary_widget is not None:
                    self._set_text_widget(summary_widget, summary_lines)
                if channel_widget is not None:
                    self._set_text_widget(channel_widget, channel_lines)
                self._update_monitor_dashboard(payload.get("summary"))
            self._refresh_lattice_view()
        except Exception as exc:
            self._append_log("Live monitor render failed: %s" % exc)

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
        self.monitor_history.clear()
        self.monitor_stop_event = threading.Event()
        self.start_monitor_button.state(["disabled"])
        self.stop_monitor_button.state(["!disabled"])
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self.monitor_thread.start()
        self._append_log("Started live read-only SSMB monitor.")

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
            adapter = ReadOnlyEpicsAdapter(timeout=config.timeout_seconds)
            _lattice, specs = build_specs(config)
            sample_index = 0
            start = time.monotonic()
            derived_context = None
            while self.monitor_stop_event is not None and not self.monitor_stop_event.is_set():
                sample = self._capture_monitor_sample(adapter, specs, sample_index, time.monotonic() - start, derived_context)
                if derived_context is None:
                    derived_context = {
                        "rf_reference_khz": sample.get("derived", {}).get("rf_readback"),
                        "l4_bpm_reference_mm": {
                            label: sample.get("channels", {}).get(label, {}).get("value")
                            for label in ("bpmz3l4rp_x", "bpmz4l4rp_x", "bpmz5l4rp_x", "bpmz6l4rp_x")
                        },
                    }
                self.monitor_history.append(sample)
                summary = summarize_live_monitor(list(self.monitor_history))
                self.queue.put(
                    {
                        "kind": "monitor_update",
                        "summary_lines": format_monitor_summary(summary),
                        "channel_lines": format_channel_snapshot(sample),
                        "sample": sample,
                        "summary": summary,
                    }
                )
                sample_index += 1
                if self.monitor_stop_event.wait(interval):
                    break
        except Exception as exc:
            self.queue.put("Live monitor failed: %s" % exc)
        finally:
            self.queue.put({"kind": "monitor_done"})

    def _capture_monitor_sample(self, adapter, specs, sample_index: int, t_rel_s: float, derived_context):
        from .log_now import capture_sample

        return capture_sample(
            adapter,
            specs,
            sample_index=sample_index,
            t_rel_s=t_rel_s,
            extra_fields={"phase": "live_monitor"},
            derived_context=derived_context,
        )

    def _open_monitor_window(self) -> None:
        if self.monitor_window is not None and self.monitor_window.winfo_exists():
            self.monitor_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB Live Monitor")
        window.geometry("1380x900")
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(0, weight=1)
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)
        self.monitor_window = window
        self.monitor_window_summary_text = None
        self.monitor_section_widgets = []
        self.monitor_plot_controls = {}
        self.monitor_plot_canvases = {}
        self.monitor_cards_container = left
        self.monitor_window_theory_text = None
        left.columnconfigure(0, weight=1)
        left.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        summary_frame = ttk.Labelframe(right, text="Theory And Value Pipeline", padding=8)
        summary_frame.grid(row=0, column=0, sticky="nsew")
        self.monitor_window_theory_text = tk.Text(summary_frame, wrap="word", height=18)
        self.monitor_window_theory_text.pack(fill="both", expand=True)
        self.monitor_window_theory_text.configure(state="disabled")
        ttk.Button(right, text="Open Theory Window", command=self._open_theory_window).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(right, text="Current channel snapshot").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.monitor_window_channels_text = tk.Text(right, wrap="none", height=18)
        self.monitor_window_channels_text.grid(row=3, column=0, sticky="nsew")
        self.monitor_window_channels_text.configure(state="disabled")
        self._set_text_widget(self.monitor_window_channels_text, self.monitor_channels_text.get("1.0", "end").splitlines())
        self._update_monitor_dashboard(self.latest_monitor_summary or summarize_live_monitor([]))
        window.protocol("WM_DELETE_WINDOW", self._close_monitor_window)

    def _close_monitor_window(self) -> None:
        if self.monitor_window is not None and self.monitor_window.winfo_exists():
            self.monitor_window.destroy()
        self.monitor_window = None
        self.monitor_window_summary_text = None
        self.monitor_window_channels_text = None
        self.monitor_cards_container = None
        self.monitor_section_widgets = []
        self.monitor_window_theory_text = None
        self.monitor_plot_controls = {}
        self.monitor_plot_canvases = {}

    def _update_monitor_dashboard(self, summary) -> None:
        if self.monitor_window is None or not self.monitor_window.winfo_exists():
            return
        if summary is None:
            summary = summarize_live_monitor([])
        sections = build_monitor_sections(summary)
        self._ensure_monitor_cards(sections)
        for section, widgets in self.monitor_section_widgets:
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
        theory_lines = []
        for theory_section in build_theory_sections(summary):
            theory_lines.append(theory_section["title"])
            for eq in theory_section.get("equations", []):
                theory_lines.append("  " + eq)
            for line in theory_section.get("lines", []):
                theory_lines.append("  " + line)
            theory_lines.append("")
        if self.monitor_window_theory_text is not None:
            self._set_text_widget(self.monitor_window_theory_text, theory_lines)
        if self.theory_window is not None and self.theory_window.winfo_exists():
            self._update_theory_window(summary)

    def _color_text_widget(self, widget: "tk.Text", color_name: str) -> None:
        colors = {"green": "#1b5e20", "yellow": "#8d6e00", "red": "#b71c1c"}
        widget.configure(fg=colors.get(color_name, "#263238"))

    def _ensure_monitor_cards(self, sections) -> None:
        container = getattr(self, "monitor_cards_container", None)
        if container is None:
            return
        existing = len(self.monitor_section_widgets)
        for idx in range(existing, len(sections)):
            row = idx // 2
            col = idx % 2
            container.rowconfigure(row, weight=1)
            card = ttk.Labelframe(container, text="Section", padding=8)
            card.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            card.columnconfigure(0, weight=1)
            text = tk.Text(card, wrap="word", height=9)
            text.grid(row=0, column=0, columnspan=2, sticky="nsew")
            text.configure(state="disabled")
            card.rowconfigure(0, weight=1)
            combo_var = tk.StringVar(value="")
            combo = ttk.Combobox(card, textvariable=combo_var, state="readonly", width=22)
            combo.grid(row=1, column=0, sticky="w", pady=(6, 4))
            canvas = tk.Canvas(card, bg="white", width=280, height=120, highlightthickness=1, highlightbackground="#cfd8dc")
            canvas.grid(row=2, column=0, columnspan=2, sticky="nsew")
            card.rowconfigure(2, weight=1)
            self.monitor_section_widgets.append(
                (
                    sections[idx],
                    {
                        "card": card,
                        "text": text,
                        "combo": combo,
                        "combo_var": combo_var,
                        "canvas": canvas,
                    },
                )
            )
        updated = []
        for idx, section in enumerate(sections):
            widgets = self.monitor_section_widgets[idx][1]
            combo = widgets["combo"]
            combo_var = widgets["combo_var"]
            options = section.get("trend_options", [])
            combo["values"] = [trend_definitions()[name]["label"] for name in options]
            current_key = self.monitor_plot_controls.get(section["key"])
            if current_key not in options:
                current_key = section.get("default_trend")
                self.monitor_plot_controls[section["key"]] = current_key
            combo_var.set(trend_definitions()[current_key]["label"])
            combo.bind("<<ComboboxSelected>>", lambda _event, key=section["key"], opts=options, var=combo_var: self._on_monitor_plot_selected(key, opts, var))
            updated.append((section, widgets))
        self.monitor_section_widgets = updated

    def _on_monitor_plot_selected(self, section_key: str, options: Sequence[str], var) -> None:
        label = var.get()
        for key in options:
            if trend_definitions()[key]["label"] == label:
                self.monitor_plot_controls[section_key] = key
                break
        self._update_monitor_dashboard(self.latest_monitor_summary)

    def _draw_section_plot(self, section: dict) -> None:
        widgets = None
        for existing_section, candidate in self.monitor_section_widgets:
            if existing_section["key"] == section["key"]:
                widgets = candidate
                break
        if widgets is None:
            return
        canvas = widgets["canvas"]
        metric = self.monitor_plot_controls.get(section["key"], section.get("default_trend"))
        trend_data = (self.latest_monitor_summary or {}).get("trend_data", {})
        values = trend_data.get(metric, [])
        meta = trend_definitions().get(metric, {"label": metric, "color": "#455a64"})
        canvas.delete("all")
        width = int(canvas.winfo_width() or 280)
        height = int(canvas.winfo_height() or 120)
        self._draw_series(canvas, values, 10, 10, width - 10, height - 10, meta["color"], meta["label"])

    def _draw_series(self, canvas, values, x0, y0, x1, y1, color, label):
        canvas.create_rectangle(x0, y0, x1, y1, outline="#cfd8dc")
        canvas.create_text(x0 + 4, y0 + 4, anchor="nw", text=label, fill="#37474f")
        clean = [v for v in values if isinstance(v, (int, float, float))]
        if len(clean) < 2:
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="waiting for data", fill="#90a4ae")
            return
        pts = self._series_to_points(values, x0 + 8, y0 + 20, x1 - 8, y1 - 8)
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=color, width=2, smooth=True)

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
        lattice, specs = build_specs(config)
        window = tk.Toplevel(self.root)
        window.title("SSMB Live Lattice View")
        window.geometry("1200x720")
        outer = ttk.Frame(window, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=0)
        outer.rowconfigure(0, weight=1)
        canvas = tk.Canvas(outer, bg="white", height=520)
        canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        info = tk.Text(outer, wrap="word", width=42)
        info.grid(row=0, column=1, sticky="nsew")
        info.configure(state="disabled")
        self.lattice_window = window
        self.lattice_canvas = canvas
        self.lattice_info_text = info
        self._draw_lattice_view(lattice, specs)
        canvas.bind("<Button-1>", self._on_lattice_click)
        window.protocol("WM_DELETE_WINDOW", self._close_lattice_window)
        self._refresh_lattice_view()

    def _draw_lattice_view(self, lattice, specs) -> None:
        canvas = self.lattice_canvas
        canvas.delete("all")
        width = int(canvas.winfo_width() or 1000)
        height = int(canvas.winfo_height() or 520)
        left = 60
        right = width - 40
        y_track = 100
        row_positions = {
            "section": 60,
            "bpm": 160,
            "qpd": 220,
            "rf": 280,
            "magnet": 340,
            "bump": 410,
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
        for row_name, row_y in (("BPMs", row_positions["bpm"]), ("QPD / optics", row_positions["qpd"]), ("RF / tune", row_positions["rf"]), ("Main lattice", row_positions["magnet"]), ("Bump correctors", row_positions["bump"])):
            canvas.create_text(10, row_y, anchor="w", text=row_name, fill="#455a64", font=("Helvetica", 10, "bold"))
            canvas.create_line(left, row_y, right, row_y, fill="#eceff1", dash=(3, 3))
        for element in lattice.elements:
            if element.element_type not in ("Monitor", "Quadrupole", "Sextupole", "Octupole", "Dipole", "RFCavity"):
                continue
            x = self._s_to_x(element.s_center_m, lattice, left, right)
            color, label, row_y = self._element_style(element, row_positions)
            item_id = canvas.create_rectangle(x - 5, row_y - 12, x + 5, row_y + 12, fill=color, outline="")
            self.lattice_device_items.append(
                {
                    "item_id": item_id,
                    "name": element.family_name,
                    "element_type": element.element_type,
                    "pv_label": self._match_spec_label(specs, element),
                    "pv": self._match_spec_pv(specs, element),
                    "notes": "%s in %s" % (element.element_type, element.section or "ring"),
                    "x": x,
                    "y": row_y,
                }
            )
            if element.element_type in ("RFCavity",):
                canvas.create_text(x, row_y - 18, text=label or element.family_name, anchor="s", font=("Helvetica", 8, "bold"))
        extras = [
            ("QPD00ZL4RP", "qpd_l4_sigma_x", "QPD00 SR camera/profile monitor in L4", 36.0, "#d81b60", row_positions["qpd"]),
            ("QPD01ZL2RP", "qpd_l2_sigma_x", "QPD01 SR camera/profile monitor in L2", 12.0, "#8e24aa", row_positions["qpd"]),
            ("HS1P2K3RP:setCur", "l4_bump_hcorr_k3_upstream", "Recovered bump corrector", 24.0, "#ef6c00", row_positions["bump"]),
            ("HS3P1L4RP:setCur", "l4_bump_hcorr_l4_upstream", "Recovered bump corrector", 31.5, "#ef6c00", row_positions["bump"]),
            ("HS3P2L4RP:setCur", "l4_bump_hcorr_l4_downstream", "Recovered bump corrector", 40.0, "#ef6c00", row_positions["bump"]),
            ("HS1P1K1RP:setCur", "l4_bump_hcorr_k1_downstream", "Recovered bump corrector", 47.0, "#ef6c00", row_positions["bump"]),
        ]
        for name, label, notes, s_pos, color, row_y in extras:
            x = self._s_to_x(s_pos, lattice, left, right)
            item_id = canvas.create_oval(x - 7, row_y - 7, x + 7, row_y + 7, fill=color, outline="")
            canvas.create_text(x, row_y - 14, text=name.split(":")[0], anchor="s", font=("Helvetica", 8))
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
                }
            )
        canvas.create_text(left, height - 18, anchor="w", text="Click a marker for live PV mapping. Rows separate BPMs, QPDs, RF, main lattice, and bump correctors.", fill="#455a64")

    def _refresh_lattice_view(self) -> None:
        if self.lattice_window is None or not self.lattice_window.winfo_exists():
            return
        if self.latest_monitor_sample is None:
            self._set_text_widget(self.lattice_info_text, ["No live sample yet. Start Live Monitor first."])
            return
        if not self.lattice_device_items:
            return
        self._set_text_widget(self.lattice_info_text, ["Lattice view ready.", "", "Click a lattice marker to inspect its live readout."])

    def _on_lattice_click(self, event) -> None:
        if not self.lattice_device_items:
            return
        nearest = min(self.lattice_device_items, key=lambda item: (item["x"] - event.x) ** 2 + (item["y"] - event.y) ** 2)
        self._show_lattice_item_info(nearest)

    def _show_lattice_item_info(self, item: dict) -> None:
        sample = self.latest_monitor_sample or {}
        channels = sample.get("channels", {})
        payload = channels.get(item.get("pv_label"), {}) if item.get("pv_label") else {}
        value = payload.get("value")
        pv = payload.get("pv") or item.get("pv")
        lines = [
            item.get("name", "device"),
            "",
            "Type: %s" % item.get("element_type"),
            "PV label: %s" % (item.get("pv_label") or "n/a"),
            "PV: %s" % (pv or "n/a"),
            "Live value: %s" % value,
            "Notes: %s" % item.get("notes", ""),
        ]
        if item.get("pv_label") == "qpd_l4_sigma_x":
            lines.extend(
                [
                    "",
                    "Use with eta_x in L4 to estimate sigma_delta via:",
                    "sigma_x^2 ~= beta_x*epsilon_x + (eta_x*sigma_delta)^2",
                ]
            )
        if item.get("pv_label", "").startswith("l4_bump_hcorr"):
            lines.extend(
                [
                    "",
                    "This corrector participates in the 4-corrector L4 bump.",
                    "Live bump state is inferred from the set of these currents plus AKC10VP.",
                ]
            )
        self._set_text_widget(self.lattice_info_text, lines)

    def _close_lattice_window(self) -> None:
        if self.lattice_window is not None and self.lattice_window.winfo_exists():
            self.lattice_window.destroy()
        self.lattice_window = None
        self.lattice_canvas = None
        self.lattice_info_text = None
        self.lattice_device_items = []

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
            "Quadrupole": ("#43a047", "", row_positions["magnet"]),
            "Sextupole": ("#fdd835", "", row_positions["magnet"]),
            "Octupole": ("#8e24aa", "", row_positions["magnet"]),
            "Dipole": ("#6d4c41", "", row_positions["magnet"]),
            "RFCavity": ("#c62828", "CAV", row_positions["rf"]),
        }
        return styles.get(element.element_type, ("#90a4ae", "", row_positions["magnet"]))

    def _open_theory_window(self) -> None:
        if self.theory_window is not None and self.theory_window.winfo_exists():
            self.theory_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("SSMB Theory And Derived-Value Pipeline")
        window.geometry("900x760")
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

    def _match_spec_label(self, specs, element: LatticeElement):
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
        lines = inventory_overview_lines(specs)
        try:
            estimate_bytes = estimate_passive_session_bytes(specs, config.duration_seconds, config.sample_hz)
            disk = shutil.disk_usage(config.output_root if config.output_root.exists() else config.output_root.parent)
            lines.extend(
                [
                    "",
                    "Estimated passive-session size: %.2f MB" % (estimate_bytes / (1024.0 * 1024.0)),
                    "Free space at output root: %.2f GB" % (disk.free / (1024.0 * 1024.0 * 1024.0)),
                ]
            )
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
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    SSMBGui(root, allow_writes=True, start_safe_mode=not bool(args.unsafe_start))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
