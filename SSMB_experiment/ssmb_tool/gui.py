from __future__ import annotations

import argparse
import queue
import shutil
import threading
from pathlib import Path
from typing import Optional, Sequence

from .config import LoggerConfig, SSMB_ROOT, parse_labeled_pvs
from .epics_io import EpicsUnavailableError, ReadOnlyEpicsAdapter
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
    def __init__(self, root: "tk.Tk", allow_writes: bool = True, start_safe_mode: bool = False):
        self.root = root
        self.allow_writes = allow_writes
        self.start_safe_mode = start_safe_mode
        self.queue: "queue.Queue[object]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stage0_stop_event: Optional[threading.Event] = None
        self._build_vars()
        self._build_ui()
        self._apply_profile()
        self._refresh_inventory()
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

        logger_frame = ttk.Frame(notebook, padding=8)
        sweep_frame = ttk.Frame(notebook, padding=8)
        notebook.add(logger_frame, text="Stage 0 Logger")
        notebook.add(sweep_frame, text="RF Sweep")

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

    def _build_sweep_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        info = "Direct RF sweep in Hz around the current or entered RF PV value. Writes are allowed by default, but they are blocked whenever the Safe / read-only mode checkbox is enabled."
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

    def _drain_queue(self) -> None:
        while True:
            try:
                message = self.queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(message, dict):
                if message.get("kind") == "bpm_status":
                    self._update_bpm_status(message)
                elif message.get("kind") == "manual_stage0_done":
                    self.stage0_stop_event = None
                    self.start_manual_button.state(["!disabled"])
                    self.stop_manual_button.state(["disabled"])
                    self._append_log("Manual logging task finalized.")
            else:
                self._append_log(str(message))
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
    parser.add_argument("--safe-mode", action="store_true", help="Start with Safe / read-only mode enabled so RF writes are blocked until you manually turn them back on.")
    parser.add_argument("--allow-writes", action="store_true", help="Deprecated compatibility flag. Writes are enabled by default unless --safe-mode is used.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if tk is None:
        raise SystemExit("tkinter is unavailable; cannot start the SSMB GUI.")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    SSMBGui(root, allow_writes=True, start_safe_mode=bool(args.safe_mode))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
