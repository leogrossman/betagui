from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .config import AppConfig
from .geometry import LaserMirrorGeometry
from .hardware import MOTOR_PVS, PVFactory, SIGNAL_PRESETS, MirrorController, build_signal_backend
from .models import BestPointRecommendation, MeasurementRecord, MirrorAngles, MotorTargets, UndulatorTarget
from .scan import ScanContext, ScanRunner, build_angle_scan_points, build_spiral_scan_points
from .state import MirrorStateSnapshot, load_state, save_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSMB laser mirror scan tool")
    parser.add_argument("--safe-mode", action="store_true", help="Run with simulated motors and simulated signal")
    parser.add_argument("--write-mode", action="store_true", help="Enable real motor writes (never needed for safe demos)")
    parser.add_argument("--config", default="laser_mirrors_config.json", help="Path to JSON config file")
    return parser


class LaserMirrorApp:
    def __init__(self, root: tk.Tk, config_path: Path, force_safe_mode: bool = False, force_write_mode: bool = False):
        self.root = root
        self.root.title("SSMB Laser Mirror Angle Scan Tool")
        self.config_path = config_path
        self.config = AppConfig.load(config_path)
        if force_safe_mode:
            self.config.controller.safe_mode = True
            self.config.controller.write_mode = False
        if force_write_mode:
            self.config.controller.write_mode = True
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        self.output_root = Path(tempfile.gettempdir()) / "laser_mirror_runs"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.measurements: list[MeasurementRecord] = []
        self.best_point: BestPointRecommendation | None = None
        self._poll_after_id: str | None = None
        self._signal_history: deque[float] = deque(maxlen=max(1, self.config.controller.p1_average_samples))
        self._signal_trace: deque[tuple[float, float]] = deque(maxlen=400)
        self._build_state()
        self._build_ui()
        self._restore_legacy_state()
        self._connect_backends()
        self._draw_geometry_preview()
        self._schedule_signal_poll()

    def _build_state(self) -> None:
        self.safe_mode_var = tk.BooleanVar(value=self.config.controller.safe_mode)
        self.write_mode_var = tk.BooleanVar(value=self.config.controller.write_mode)
        self.signal_preset_var = tk.StringVar(value=self._preset_from_pv(self.config.controller.signal_pv))
        self.signal_pv_var = tk.StringVar(value=self.config.controller.signal_pv)
        self.signal_label_var = tk.StringVar(value=self.config.controller.signal_label)
        self.poll_interval_var = tk.IntVar(value=self.config.controller.p1_poll_interval_ms)
        self.average_samples_var = tk.IntVar(value=self.config.controller.p1_average_samples)
        self.max_step_var = tk.DoubleVar(value=self.config.controller.max_step_per_put)
        self.delay_var = tk.DoubleVar(value=self.config.controller.inter_put_delay_s)
        self.settle_var = tk.DoubleVar(value=self.config.controller.settle_s)
        self.max_delta_var = tk.DoubleVar(value=self.config.controller.max_delta_from_reference)
        self.max_absolute_move_var = tk.DoubleVar(value=self.config.controller.max_absolute_move_steps)
        self.offset_x_var = tk.DoubleVar(value=self.config.controller.startup_offset_x_mm)
        self.offset_y_var = tk.DoubleVar(value=self.config.controller.startup_offset_y_mm)
        self.center_x_var = tk.DoubleVar(value=self.config.scan.center_angle_x_urad)
        self.center_y_var = tk.DoubleVar(value=self.config.scan.center_angle_y_urad)
        self.span_x_var = tk.DoubleVar(value=self.config.scan.span_angle_x_urad)
        self.span_y_var = tk.DoubleVar(value=self.config.scan.span_angle_y_urad)
        self.points_x_var = tk.IntVar(value=self.config.scan.points_x)
        self.points_y_var = tk.IntVar(value=self.config.scan.points_y)
        self.dwell_var = tk.DoubleVar(value=self.config.scan.dwell_s)
        self.samples_var = tk.IntVar(value=self.config.scan.p1_samples_per_point)
        self.scan_mode_var = tk.StringVar(value=self.config.scan.mode)
        self.solve_mode_var = tk.StringVar(value=self.config.scan.solve_mode)
        self.objective_var = tk.StringVar(value=self.config.scan.objective)
        self.spiral_step_x_var = tk.DoubleVar(value=self.config.scan.spiral_step_x)
        self.spiral_step_y_var = tk.DoubleVar(value=self.config.scan.spiral_step_y)
        self.spiral_turns_var = tk.IntVar(value=self.config.scan.spiral_turns)
        self.manual_motor_var = tk.StringVar(value="m2_horizontal")
        self.manual_delta_var = tk.DoubleVar(value=1.0)
        self.manual_absolute_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Idle")
        self.runtime_var = tk.StringVar(value="Backends not connected yet.")
        self.best_var = tk.StringVar(value="No best point yet.")
        self.last_export_var = tk.StringVar(value="No scan saved yet.")
        self.signal_live_var = tk.StringVar(value="—")
        self.signal_avg_var = tk.StringVar(value="—")
        self.signal_std_var = tk.StringVar(value="—")
        self.signal_samples_var = tk.StringVar(value="0")
        self.signal_last_update_var = tk.StringVar(value="Never")
        self.reference_var = tk.StringVar(value="Reference not captured yet.")
        self.state_path_var = tk.StringVar(value=self.config.controller.state_file_path)
        self.current_reference_steps: dict[str, float] = {key: 0.0 for key in MOTOR_PVS}
        self.legacy_state_path = (self.config_path.parent / self.config.controller.state_file_path).resolve()
        self.motor_recovery_path = (self.config_path.parent / self.config.controller.motor_recovery_path).resolve()
        self.last_command_path = (self.config_path.parent / self.config.controller.last_command_path).resolve()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)
        self.overview_frame = ttk.Frame(notebook, padding=10)
        self.manual_frame = ttk.Frame(notebook, padding=10)
        self.angle_frame = ttk.Frame(notebook, padding=10)
        self.spiral_frame = ttk.Frame(notebook, padding=10)
        self.debug_frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.overview_frame, text="Overview")
        notebook.add(self.manual_frame, text="Manual control")
        notebook.add(self.angle_frame, text="Angle scan")
        notebook.add(self.spiral_frame, text="Mirror 2 spiral")
        notebook.add(self.debug_frame, text="Debug / Logs")
        self._build_overview()
        self._build_manual()
        self._build_angle()
        self._build_spiral()
        self._build_debug()

    def _build_overview(self) -> None:
        left = ttk.Frame(self.overview_frame)
        right = ttk.Frame(self.overview_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.overview_frame.columnconfigure(0, weight=2)
        self.overview_frame.columnconfigure(1, weight=1)
        self.overview_frame.rowconfigure(0, weight=1)

        top = ttk.LabelFrame(left, text="Machine / safety", padding=10)
        top.pack(fill="x")
        ttk.Checkbutton(top, text="Safe mode (no hardware writes)", variable=self.safe_mode_var, command=self._safe_mode_changed).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(top, text="Enable real writes", variable=self.write_mode_var, command=self._write_mode_changed).grid(row=1, column=0, columnspan=2, sticky="w")
        self._add_labeled_combo(top, "Signal preset", self.signal_preset_var, list(SIGNAL_PRESETS.keys()), 2)
        self._add_labeled_entry(top, "Signal PV override", self.signal_pv_var, 3, width=34)
        self._add_labeled_entry(top, "Poll [ms]", self.poll_interval_var, 4)
        self._add_labeled_entry(top, "Avg samples", self.average_samples_var, 5)
        self._add_labeled_entry(top, "Max steps/put", self.max_step_var, 6)
        self._add_labeled_entry(top, "Inter-put delay [s]", self.delay_var, 7)
        self._add_labeled_entry(top, "Settle [s]", self.settle_var, 8)
        self._add_labeled_entry(top, "Max delta from ref [steps]", self.max_delta_var, 9)
        self._add_labeled_entry(top, "Max move window [steps]", self.max_absolute_move_var, 10)
        ttk.Button(top, text="Reconnect backends", command=self._connect_backends).grid(row=11, column=0, pady=(8, 0), sticky="w")
        ttk.Button(top, text="Save config", command=self._save_config).grid(row=11, column=1, pady=(8, 0), sticky="e")

        target = ttk.LabelFrame(left, text="Undulator-space target", padding=10)
        target.pack(fill="x", pady=(10, 0))
        self._add_labeled_entry(target, "Offset X [mm]", self.offset_x_var, 0)
        self._add_labeled_entry(target, "Offset Y [mm]", self.offset_y_var, 1)
        ttk.Button(target, text="Save current mirror state", command=self._save_motor_recovery).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Return to startup reference", command=self._return_to_reference).grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Return to saved motor state", command=self._return_to_recovery_state).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Capture current RBV as reference", command=self._capture_reference).grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(target, textvariable=self.reference_var, wraplength=500, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.motor_tree = ttk.Treeview(
            left,
            columns=("pv", "rbv", "val", "dmov", "movn", "stat", "sevr", "egu"),
            show="headings",
            height=8,
        )
        for key, title, width in [
            ("pv", "PV", 190),
            ("rbv", "RBV", 90),
            ("val", "VAL", 90),
            ("dmov", "DMOV", 60),
            ("movn", "MOVN", 60),
            ("stat", "STAT", 90),
            ("sevr", "SEVR", 90),
            ("egu", "EGU", 60),
        ]:
            self.motor_tree.heading(key, text=title)
            self.motor_tree.column(key, width=width)
        self.motor_tree.pack(fill="x", pady=(10, 0))
        for key, pv in MOTOR_PVS.items():
            self.motor_tree.insert("", "end", iid=key, text=key, values=(pv, "", "", "", "", "", "", ""))

        self.signal_box = ttk.LabelFrame(right, text="Live signal readout", padding=10)
        self.signal_box.pack(fill="x")
        self._labeled_value(self.signal_box, "Label", self.signal_label_var, 0)
        self._labeled_value(self.signal_box, "Instantaneous", self.signal_live_var, 1)
        self._labeled_value(self.signal_box, "Rolling average", self.signal_avg_var, 2)
        self._labeled_value(self.signal_box, "Rolling std", self.signal_std_var, 3)
        self._labeled_value(self.signal_box, "Samples in window", self.signal_samples_var, 4)
        self._labeled_value(self.signal_box, "Last update", self.signal_last_update_var, 5)
        self.signal_trace_canvas = tk.Canvas(self.signal_box, width=360, height=160, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.signal_trace_canvas.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        info = ttk.LabelFrame(right, text="Runtime", padding=10)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, textvariable=self.runtime_var, wraplength=360, justify="left").pack(anchor="w")
        ttk.Label(info, text=f"Legacy state file: {self.legacy_state_path}", wraplength=360, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, text=f"Motor recovery file: {self.motor_recovery_path}", wraplength=360, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, text=f"Last command file: {self.last_command_path}", wraplength=360, justify="left").pack(anchor="w", pady=(6, 0))

        schematic = ttk.LabelFrame(right, text="Laser steering schematic", padding=10)
        schematic.pack(fill="both", expand=True, pady=(10, 0))
        self.geometry_canvas = tk.Canvas(schematic, width=380, height=280, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.geometry_canvas.pack(fill="both", expand=True)

    def _build_manual(self) -> None:
        left = ttk.Frame(self.manual_frame)
        right = ttk.Frame(self.manual_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        box = ttk.LabelFrame(left, text="Motor move tools", padding=10)
        box.pack(fill="x")
        self._add_labeled_combo(box, "Motor", self.manual_motor_var, list(MOTOR_PVS.keys()), 0)
        self._add_labeled_entry(box, "Delta [steps]", self.manual_delta_var, 1)
        self._add_labeled_entry(box, "Absolute [steps]", self.manual_absolute_var, 2)
        ttk.Button(box, text="Nudge -", command=lambda: self._manual_relative_move(-1)).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(box, text="Nudge +", command=lambda: self._manual_relative_move(1)).grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(box, text="Move absolute", command=self._manual_absolute_move).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(box, text="STOP all (emergency)", command=self._hard_stop).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        note = ttk.LabelFrame(right, text="Safety notes", padding=10)
        note.pack(fill="x")
        ttk.Label(
            note,
            text=(
                "Manual commands use the same ramped EPICS `.VAL` path as scans.\n"
                "Every real command is written to the debug log and to the last-command file.\n"
                "Use tiny steps first. Prefer graceful scan stop over hard `.STOP` unless needed."
            ),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")

    def _build_angle(self) -> None:
        controls = ttk.LabelFrame(self.angle_frame, text="Carsten angle scan", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.LabelFrame(self.angle_frame, text="Live scan maps", padding=10)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.angle_frame.columnconfigure(1, weight=1)
        self.angle_frame.rowconfigure(0, weight=1)
        self._add_labeled_entry(controls, "Center X [µrad]", self.center_x_var, 0)
        self._add_labeled_entry(controls, "Center Y [µrad]", self.center_y_var, 1)
        self._add_labeled_entry(controls, "Span X [µrad]", self.span_x_var, 2)
        self._add_labeled_entry(controls, "Span Y [µrad]", self.span_y_var, 3)
        self._add_labeled_entry(controls, "Points X", self.points_x_var, 4)
        self._add_labeled_entry(controls, "Points Y", self.points_y_var, 5)
        self._add_labeled_entry(controls, "Dwell [s]", self.dwell_var, 6)
        self._add_labeled_entry(controls, "Samples / point", self.samples_var, 7)
        self._add_labeled_combo(controls, "Sweep mode", self.scan_mode_var, ["both_2d", "horizontal_only", "vertical_only"], 8)
        self._add_labeled_combo(controls, "Solve mode", self.solve_mode_var, ["two_mirror_target", "mirror1_primary", "mirror2_primary"], 9)
        self._add_labeled_combo(controls, "Objective", self.objective_var, ["max", "min"], 10)
        ttk.Button(controls, text="Preview commands", command=self._preview_angle_scan).grid(row=11, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start angle scan", command=self._start_angle_scan).grid(row=11, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Request stop", command=self._stop_scan).grid(row=12, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Move to best point", command=self._move_to_best_point).grid(row=12, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.status_var, wraplength=320, justify="left").grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.best_var, wraplength=320, justify="left").grid(row=14, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.last_export_var, wraplength=320, justify="left").grid(row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.heatmap_canvas = tk.Canvas(plots, width=700, height=360, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.heatmap_canvas.pack(fill="both", expand=True)
        self.progress_canvas = tk.Canvas(plots, width=700, height=220, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.progress_canvas.pack(fill="x", pady=(10, 0))

    def _build_spiral(self) -> None:
        controls = ttk.LabelFrame(self.spiral_frame, text="Mirror 2 spiral", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.LabelFrame(self.spiral_frame, text="Mirror 2 signal map", padding=10)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.spiral_frame.columnconfigure(1, weight=1)
        self.spiral_frame.rowconfigure(0, weight=1)
        self._add_labeled_entry(controls, "Step X [steps]", self.spiral_step_x_var, 0)
        self._add_labeled_entry(controls, "Step Y [steps]", self.spiral_step_y_var, 1)
        self._add_labeled_entry(controls, "Turns", self.spiral_turns_var, 2)
        ttk.Button(controls, text="Preview commands", command=self._preview_spiral_scan).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start spiral", command=self._start_spiral_scan).grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Request stop", command=self._stop_scan).grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.spiral_canvas = tk.Canvas(plots, width=700, height=420, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.spiral_canvas.pack(fill="both", expand=True)

    def _build_debug(self) -> None:
        ttk.Label(self.debug_frame, text="Diagnostics, planned commands, and runtime logs.").pack(anchor="w")
        row = ttk.Frame(self.debug_frame)
        row.pack(fill="x", pady=(8, 8))
        ttk.Button(row, text="Refresh motor diagnostics", command=self._refresh_motor_table).pack(side="left")
        ttk.Button(row, text="Export diagnostics JSON", command=self._export_diagnostics).pack(side="left", padx=6)
        self.debug_text = tk.Text(self.debug_frame, width=120, height=32)
        self.debug_text.pack(fill="both", expand=True)

    def _add_labeled_entry(self, parent: ttk.Widget, label: str, variable: tk.Variable, row: int, width: int = 14) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="e", pady=2)

    def _add_labeled_combo(self, parent: ttk.Widget, label: str, variable: tk.Variable, values: list[str], row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=18).grid(row=row, column=1, sticky="e", pady=2)

    def _labeled_value(self, parent: ttk.Widget, label: str, variable: tk.Variable, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(parent, textvariable=variable).grid(row=row, column=1, sticky="e", pady=2)

    def _preset_from_pv(self, pv_name: str) -> str:
        for key, (_label, pv) in SIGNAL_PRESETS.items():
            if pv == pv_name:
                return key
        return "p1_h1_avg"

    def _pull_ui_into_config(self) -> None:
        self.config.controller.safe_mode = self.safe_mode_var.get()
        self.config.controller.write_mode = self.write_mode_var.get()
        preset = self.signal_preset_var.get()
        if not self.signal_pv_var.get() and preset in SIGNAL_PRESETS:
            label, pv = SIGNAL_PRESETS[preset]
            self.signal_pv_var.set(pv)
            self.signal_label_var.set(label)
        self.config.controller.signal_pv = self.signal_pv_var.get()
        self.config.controller.signal_label = self.signal_label_var.get()
        self.config.controller.p1_poll_interval_ms = max(100, int(self.poll_interval_var.get()))
        self.config.controller.p1_average_samples = max(1, int(self.average_samples_var.get()))
        self.config.controller.max_step_per_put = max(0.1, float(self.max_step_var.get()))
        self.config.controller.inter_put_delay_s = max(0.0, float(self.delay_var.get()))
        self.config.controller.settle_s = max(0.0, float(self.settle_var.get()))
        self.config.controller.max_delta_from_reference = max(1.0, float(self.max_delta_var.get()))
        self.config.controller.max_absolute_move_steps = max(1.0, float(self.max_absolute_move_var.get()))
        self.config.controller.startup_offset_x_mm = float(self.offset_x_var.get())
        self.config.controller.startup_offset_y_mm = float(self.offset_y_var.get())
        self.config.scan.offset_x_mm = float(self.offset_x_var.get())
        self.config.scan.offset_y_mm = float(self.offset_y_var.get())
        self.config.scan.center_angle_x_urad = float(self.center_x_var.get())
        self.config.scan.center_angle_y_urad = float(self.center_y_var.get())
        self.config.scan.span_angle_x_urad = float(self.span_x_var.get())
        self.config.scan.span_angle_y_urad = float(self.span_y_var.get())
        self.config.scan.points_x = max(1, int(self.points_x_var.get()))
        self.config.scan.points_y = max(1, int(self.points_y_var.get()))
        self.config.scan.dwell_s = max(0.0, float(self.dwell_var.get()))
        self.config.scan.p1_samples_per_point = max(1, int(self.samples_var.get()))
        self.config.scan.mode = self.scan_mode_var.get()
        self.config.scan.solve_mode = self.solve_mode_var.get()
        self.config.scan.objective = self.objective_var.get()
        self.config.scan.spiral_step_x = float(self.spiral_step_x_var.get())
        self.config.scan.spiral_step_y = float(self.spiral_step_y_var.get())
        self.config.scan.spiral_turns = max(1, int(self.spiral_turns_var.get()))

    def _save_config(self) -> None:
        self._pull_ui_into_config()
        self.config.save(self.config_path)
        self._log(f"Saved config to {self.config_path}")

    def _safe_mode_changed(self) -> None:
        if self.safe_mode_var.get():
            self.write_mode_var.set(False)
        self._connect_backends()

    def _write_mode_changed(self) -> None:
        if self.write_mode_var.get() and self.safe_mode_var.get():
            self.safe_mode_var.set(False)
        self._connect_backends()

    def _connect_backends(self) -> None:
        self._pull_ui_into_config()
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        try:
            self.factory = PVFactory(self.config.controller.safe_mode)
            self.controller = MirrorController(self.config.controller, self.factory, self._log)
            self.current_reference_steps = self.controller.capture_reference()
            self.signal_backend = build_signal_backend(
                self.config.controller.safe_mode,
                self.signal_preset_var.get(),
                self.signal_pv_var.get(),
                self.factory,
            )
            if hasattr(self.signal_backend, "label"):
                self.signal_label_var.set(getattr(self.signal_backend, "label"))
            if hasattr(self.signal_backend, "pv_name"):
                self.signal_pv_var.set(getattr(self.signal_backend, "pv_name"))
            self.scan_runner = ScanRunner(self.config, self.geometry, self.controller, self.signal_backend, self._log, self.output_root)
            self.runtime_var.set(
                "EPICS backend ready\n"
                f"safe_mode={self.config.controller.safe_mode}, write_mode={self.controller.write_mode}\n"
                f"signal={self.signal_label_var.get()} ({self.signal_pv_var.get()})\n"
                f"output_root={self.output_root}"
            )
            self.status_var.set("Backends connected.")
            self.reference_var.set("Reference RBV: " + ", ".join(f"{key}={value:.2f}" for key, value in self.current_reference_steps.items()))
            self._refresh_motor_table()
        except Exception as exc:  # noqa: BLE001
            self.safe_mode_var.set(True)
            self.write_mode_var.set(False)
            self._pull_ui_into_config()
            self.factory = PVFactory(True)
            self.controller = MirrorController(self.config.controller, self.factory, self._log)
            self.current_reference_steps = self.controller.capture_reference()
            self.signal_backend = build_signal_backend(True, self.signal_preset_var.get(), None, self.factory)
            self.scan_runner = ScanRunner(self.config, self.geometry, self.controller, self.signal_backend, self._log, self.output_root)
            self.runtime_var.set(f"Backend connection failed; fell back to safe mode.\nReason: {exc}")
            self.status_var.set("Using safe mode after backend failure.")
            self._log(f"Backend connection failed, using safe mode: {exc}")

    def _restore_legacy_state(self) -> None:
        snapshot = load_state(self.legacy_state_path)
        self.offset_x_var.set(snapshot.last_set_x.offset_mm)
        self.offset_y_var.set(snapshot.last_set_y.offset_mm)
        self.center_x_var.set(snapshot.last_set_x.angle_urad)
        self.center_y_var.set(snapshot.last_set_y.angle_urad)
        self._log(f"Loaded legacy setpoints from {self.legacy_state_path}")

    def _save_legacy_state(self) -> None:
        target_x = UndulatorTarget(self.offset_x_var.get(), self.center_x_var.get())
        target_y = UndulatorTarget(self.offset_y_var.get(), self.center_y_var.get())
        angles_x = self.geometry.to_mirror_angles(target_x, "x")
        angles_y = self.geometry.to_mirror_angles(target_y, "y")
        save_state(self.legacy_state_path, self.geometry, angles_x, angles_y, target_x, target_y)
        self._log(f"Saved legacy mirror state to {self.legacy_state_path}")

    def _save_motor_recovery(self) -> None:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "reference_steps": dict(self.current_reference_steps),
            "current_steps": self.controller.current_steps(),
            "target_offset_x_mm": self.offset_x_var.get(),
            "target_offset_y_mm": self.offset_y_var.get(),
            "scan_center_x_urad": self.center_x_var.get(),
            "scan_center_y_urad": self.center_y_var.get(),
        }
        self.motor_recovery_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        self._log(f"Saved motor recovery state to {self.motor_recovery_path}")

    def _load_motor_recovery(self) -> dict[str, float] | None:
        if not self.motor_recovery_path.exists():
            return None
        try:
            payload = json.loads(self.motor_recovery_path.read_text())
            return payload.get("current_steps")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Could not load motor recovery state: {exc}")
            return None

    def _capture_reference(self) -> None:
        self.current_reference_steps = self.controller.capture_reference()
        self.reference_var.set("Reference RBV: " + ", ".join(f"{key}={value:.2f}" for key, value in self.current_reference_steps.items()))
        self._log("Captured current motor RBV values as the new reference.")

    def _return_to_reference(self) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan first.")
            return
        self._move_motor_targets(self.current_reference_steps, "Return to startup reference")

    def _return_to_recovery_state(self) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan first.")
            return
        targets = self._load_motor_recovery()
        if not targets:
            messagebox.showinfo("No saved motor state", "No motor recovery state is available yet.")
            return
        self._move_motor_targets(targets, "Return to saved motor state")

    def _manual_relative_move(self, direction: int) -> None:
        key = self.manual_motor_var.get()
        delta = float(self.manual_delta_var.get()) * float(direction)
        current = self.controller.current_steps()
        targets = dict(current)
        targets[key] = current[key] + delta
        self._move_motor_targets(targets, f"Manual relative move {key} by {delta:.2f} steps")

    def _manual_absolute_move(self) -> None:
        key = self.manual_motor_var.get()
        target = float(self.manual_absolute_var.get())
        current = self.controller.current_steps()
        targets = dict(current)
        targets[key] = target
        self._move_motor_targets(targets, f"Manual absolute move {key} to {target:.2f} steps")

    def _hard_stop(self) -> None:
        self.controller.stop_all()
        self.status_var.set("STOP sent to all motors.")

    def _move_motor_targets(self, targets: dict[str, float], description: str) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan first.")
            return
        self._save_motor_recovery()
        ok, errors = self.controller.validate_targets(targets)
        if not ok:
            messagebox.showerror("Unsafe move blocked", "\n".join(errors))
            return
        preview = self.controller.plan_absolute_move(self.controller.current_steps(), targets)
        if self.config.controller.preview_required and not self._show_command_preview(preview, description):
            self._log("Operator cancelled move preview.")
            return
        try:
            moved = self.controller.move_absolute_group(
                targets,
                request_stop=lambda: False,
                command_logger=self._append_command_record,
                command_path=self.last_command_path,
            )
            if moved:
                self.status_var.set(description)
                self._refresh_motor_table()
                self._save_legacy_state()
        except Exception as exc:  # noqa: BLE001
            self._log(f"Motor move failed: {exc}")
            messagebox.showerror("Move failed", str(exc))

    def _append_command_record(self, record) -> None:
        self._log(json.dumps({"timestamp": record.timestamp, "action": record.action, "payload": record.payload}))

    def _preview_angle_scan(self) -> None:
        points = build_angle_scan_points(self.config, self.geometry, self.current_reference_steps)
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        self._show_scan_preview(preview, "Angle scan preview")

    def _preview_spiral_scan(self) -> None:
        points = build_spiral_scan_points(self.config, self.current_reference_steps)
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        self._show_scan_preview(preview, "Mirror 2 spiral preview")

    def _show_scan_preview(self, preview_rows: list[dict[str, object]], title: str) -> bool:
        if not preview_rows:
            messagebox.showinfo(title, "No scan points generated.")
            return False
        lines = []
        for row in preview_rows[:24]:
            lines.append(
                f"#{row['index']} mode={row['mode']} ax={row['angle_x_urad']:.2f} ay={row['angle_y_urad']:.2f} "
                f"maxΔ={row['max_delta_from_reference']:.2f} layers={row['estimated_ramp_layers']} "
                f"targets={row['targets']}"
            )
        if len(preview_rows) > 24:
            lines.append(f"... {len(preview_rows) - 24} more points omitted")
        return messagebox.askokcancel(title, "\n".join(lines) + "\n\nApprove?")

    def _show_command_preview(self, preview: dict[str, list], title: str) -> bool:
        lines = []
        for key, commands in preview.items():
            for command in commands:
                lines.append(
                    f"{key}: {command.start_rbv:.2f} -> {command.target_val:.2f}; "
                    f"wait_dmov={command.wait_for_dmov}, settle={command.settle_s:.2f}s"
                )
        return messagebox.askokcancel(title, "\n".join(lines[:40]) + ("\n..." if len(lines) > 40 else ""))

    def _start_angle_scan(self) -> None:
        self._pull_ui_into_config()
        points = build_angle_scan_points(self.config, self.geometry, self.current_reference_steps)
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        if self.config.controller.preview_required and not self._show_scan_preview(preview, "Approve angle scan"):
            return
        self._start_scan_common("angle")

    def _start_spiral_scan(self) -> None:
        self._pull_ui_into_config()
        points = build_spiral_scan_points(self.config, self.current_reference_steps)
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        if self.config.controller.preview_required and not self._show_scan_preview(preview, "Approve mirror 2 spiral"):
            return
        self._start_scan_common("spiral")

    def _start_scan_common(self, mode: str) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "A scan is already running.")
            return
        self.measurements.clear()
        self.best_point = None
        self.best_var.set("Best point pending...")
        context = ScanContext(
            reference_steps=dict(self.current_reference_steps),
            signal_label=self.signal_label_var.get(),
            signal_pv=self.signal_pv_var.get(),
        )
        self.status_var.set("Scan running...")
        self.scan_runner.start(mode, context, self._on_measurement_thread, self._on_finish_thread)

    def _stop_scan(self) -> None:
        self.scan_runner.request_stop()
        self.status_var.set("Stop requested after current point.")

    def _move_to_best_point(self) -> None:
        if self.best_point is None:
            messagebox.showinfo("No best point", "Run a scan first.")
            return
        self._move_motor_targets(self.best_point.targets.as_dict(), "Move to best point")

    def _on_measurement_thread(self, measurement: MeasurementRecord) -> None:
        self.root.after(0, self._record_measurement, measurement)

    def _record_measurement(self, measurement: MeasurementRecord) -> None:
        self.measurements.append(measurement)
        self.status_var.set(
            f"Scan point {measurement.point_index + 1}: {measurement.signal_label} "
            f"avg={measurement.signal_average:.6g}"
        )
        self._draw_angle_heatmap()
        self._draw_progress()
        if measurement.mode == "mirror2_spiral":
            self._draw_spiral_map()

    def _on_finish_thread(self, session_dir: Path, best_point: BestPointRecommendation | None) -> None:
        self.root.after(0, self._finish_scan, session_dir, best_point)

    def _finish_scan(self, session_dir: Path, best_point: BestPointRecommendation | None) -> None:
        self.best_point = best_point
        self.last_export_var.set(f"Saved session: {session_dir}")
        if best_point is None:
            self.best_var.set("No best point computed.")
        else:
            self.best_var.set(
                f"Best {best_point.objective}: {best_point.signal_label}={best_point.signal_value:.6g} "
                f"at ax={best_point.angle_x_urad:.2f} µrad, ay={best_point.angle_y_urad:.2f} µrad"
            )
        self.status_var.set("Scan finished.")
        self._save_legacy_state()
        self._save_motor_recovery()
        self._log(f"Scan finished. Saved to {session_dir}")

    def _schedule_signal_poll(self) -> None:
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
        delay = max(100, int(self.poll_interval_var.get()))
        self._poll_after_id = self.root.after(delay, self._poll_signal)

    def _poll_signal(self) -> None:
        self._poll_after_id = None
        try:
            if hasattr(self.signal_backend, "update_target"):
                self.signal_backend.update_target(self.center_x_var.get(), self.center_y_var.get())
            reading = self.signal_backend.read()
            if reading.ok:
                self.signal_live_var.set(f"{reading.value:.6g}")
                self.signal_label_var.set(reading.label)
                self.signal_pv_var.set(reading.pv)
                self._signal_history.append(reading.value)
                self._signal_trace.append((time.time(), reading.value))
                avg = statistics.fmean(self._signal_history)
                std = statistics.pstdev(self._signal_history) if len(self._signal_history) > 1 else 0.0
                self.signal_avg_var.set(f"{avg:.6g}")
                self.signal_std_var.set(f"{std:.3e}")
                self.signal_samples_var.set(str(len(self._signal_history)))
                self.signal_last_update_var.set(time.strftime("%H:%M:%S"))
                self._draw_signal_trace()
            self._refresh_motor_table()
        except Exception as exc:  # noqa: BLE001
            self.signal_live_var.set("ERR")
            self.signal_last_update_var.set(f"Error: {exc}")
            self._log(f"Signal poll failed: {exc}")
        finally:
            self._draw_geometry_preview()
            self._schedule_signal_poll()

    def _refresh_motor_table(self) -> None:
        if not hasattr(self, "controller"):
            return
        for snapshot in self.controller.motor_snapshots():
            self.motor_tree.item(
                snapshot.key,
                values=(
                    snapshot.base,
                    f"{snapshot.rbv:.3f}",
                    f"{snapshot.val:.3f}",
                    snapshot.dmov,
                    snapshot.movn,
                    snapshot.stat,
                    snapshot.sevr,
                    snapshot.egu,
                ),
            )

    def _export_diagnostics(self) -> None:
        diagnostics_path = self.output_root / ("laser_mirror_diagnostics_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
        self.controller.write_diagnostics(diagnostics_path)
        self._log(f"Exported diagnostics to {diagnostics_path}")

    def _draw_signal_trace(self) -> None:
        canvas = self.signal_trace_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 30
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if len(self._signal_trace) < 2:
            canvas.create_text(w // 2, h // 2, text="Waiting for live signal history...", fill="#666666")
            return
        times = [item[0] for item in self._signal_trace]
        values = [item[1] for item in self._signal_trace]
        t0 = min(times)
        tspan = max(max(times) - t0, 1e-6)
        vmin = min(values)
        vmax = max(values)
        vspan = max(vmax - vmin, 1e-9)
        prev = None
        for timestamp, value in self._signal_trace:
            px = margin + (timestamp - t0) / tspan * (w - 2 * margin)
            py = h - margin - (value - vmin) / vspan * (h - 2 * margin)
            if prev is not None:
                canvas.create_line(prev[0], prev[1], px, py, fill="#1d4ed8", width=2)
            prev = (px, py)
        canvas.create_text(w // 2, 14, text=f"{self.signal_label_var.get()} over time", font=("Helvetica", 10, "bold"))

    def _draw_geometry_preview(self) -> None:
        canvas = self.geometry_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        y_mid = h // 2
        m1_x = 80
        fold_x = 155
        m2_x = 220
        und_x = 340
        canvas.create_line(20, y_mid, w - 20, y_mid, fill="#888888", dash=(4, 4))
        for x, label, color in [
            (m1_x, "Mirror 1", "#1d4ed8"),
            (fold_x, "Fixed fold", "#64748b"),
            (m2_x, "Mirror 2", "#0f766e"),
            (und_x, "U125", "#c2410c"),
        ]:
            canvas.create_text(x, 28, text=label, font=("Helvetica", 10, "bold"))
            if label == "U125":
                canvas.create_oval(x - 6, y_mid - 6, x + 6, y_mid + 6, fill=color, outline="")
            else:
                canvas.create_rectangle(x - 8, y_mid - 20, x + 8, y_mid + 20, fill=color)
        poly = self.geometry.ray_polyline(self.center_x_var.get(), self.offset_y_var.get())
        xs = [point[0] for point in poly]
        ys = [point[1] for point in poly]
        x_min = min(xs)
        x_span = max(max(xs) - x_min, 1.0)
        y_abs = max(max(abs(value) for value in ys), 1.0)
        prev = None
        for x_mm, y_mm in poly:
            px = 20 + (x_mm - x_min) / x_span * (w - 40)
            py = y_mid - (y_mm / y_abs) * 55
            if prev is not None:
                canvas.create_line(prev[0], prev[1], px, py, fill="#111827", width=2)
            prev = (px, py)
        canvas.create_text(
            18,
            h - 42,
            anchor="w",
            text=(
                f"Target: offset=({self.offset_x_var.get():.3f}, {self.offset_y_var.get():.3f}) mm, "
                f"center angle=({self.center_x_var.get():.2f}, {self.center_y_var.get():.2f}) µrad"
            ),
        )
        canvas.create_text(18, h - 22, anchor="w", text="Schematic only: one static fold mirror is included for visual context.")

    def _draw_angle_heatmap(self) -> None:
        canvas = self.heatmap_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 48
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        relevant = [row for row in self.measurements if row.mode != "mirror2_spiral"]
        if not relevant:
            canvas.create_text(w // 2, h // 2, text="No angle scan data yet", fill="#666666")
            return
        span_x = max(abs(self.span_x_var.get()), 1e-6)
        span_y = max(abs(self.span_y_var.get()), 1e-6)
        center_x = self.center_x_var.get()
        center_y = self.center_y_var.get()
        values = [row.signal_average for row in relevant if row.signal_average == row.signal_average]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        span = max(hi - lo, 1e-9)
        for row in relevant:
            px = margin + (row.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
            py = h - margin - (row.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            radius = 5
            canvas.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="")
        if self.best_point is not None:
            px = margin + (self.best_point.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
            py = h - margin - (self.best_point.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            canvas.create_line(px - 8, py, px + 8, py, fill="#111827", width=2)
            canvas.create_line(px, py - 8, px, py + 8, fill="#111827", width=2)
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} vs interaction angle", font=("Helvetica", 11, "bold"))
        canvas.create_text(w // 2, h - 18, text="Angle X [µrad]")
        canvas.create_text(18, h // 2, text="Angle Y [µrad]", angle=90)

    def _draw_progress(self) -> None:
        canvas = self.progress_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 40
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if not self.measurements:
            canvas.create_text(w // 2, h // 2, text="No scan progress yet", fill="#666666")
            return
        values = [row.signal_average for row in self.measurements if row.signal_average == row.signal_average]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        span = max(hi - lo, 1e-9)
        prev = None
        for index, row in enumerate(self.measurements):
            px = margin + index / max(len(self.measurements) - 1, 1) * (w - 2 * margin)
            py = h - margin - (row.signal_average - lo) / span * (h - 2 * margin)
            if prev is not None:
                canvas.create_line(prev[0], prev[1], px, py, fill="#1d4ed8", width=2)
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#c2410c", outline="")
            prev = (px, py)
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} during scan", font=("Helvetica", 11, "bold"))

    def _draw_spiral_map(self) -> None:
        canvas = self.spiral_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 48
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        relevant = [row for row in self.measurements if row.mode == "mirror2_spiral"]
        if not relevant:
            canvas.create_text(w // 2, h // 2, text="No spiral scan data yet", fill="#666666")
            return
        xs = [row.commanded_m2_horizontal for row in relevant]
        ys = [row.commanded_m2_vertical for row in relevant]
        vx = max(max(xs) - min(xs), 1e-6)
        vy = max(max(ys) - min(ys), 1e-6)
        values = [row.signal_average for row in relevant if row.signal_average == row.signal_average]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        span = max(hi - lo, 1e-9)
        for row in relevant:
            px = margin + (row.commanded_m2_horizontal - min(xs)) / vx * (w - 2 * margin)
            py = h - margin - (row.commanded_m2_vertical - min(ys)) / vy * (h - 2 * margin)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill=color, outline="")
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} vs mirror 2 position", font=("Helvetica", 11, "bold"))

    def _color_for_value(self, value: float) -> str:
        value = max(0.0, min(1.0, float(value)))
        r = int(255 * value)
        g = int(180 * (1.0 - value) + 40 * value)
        b = int(255 * (1.0 - value))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.debug_text.insert("end", f"[{timestamp}] {message}\n")
        self.debug_text.see("end")

    def on_close(self) -> None:
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if hasattr(self, "scan_runner") and self.scan_runner.is_running():
            if not messagebox.askyesno("Scan still running", "A scan is still running. Stop it and close the application?"):
                return
            self.scan_runner.request_stop()
            self.scan_runner.join(timeout=5.0)
        try:
            self._save_motor_recovery()
            self._save_legacy_state()
            self._save_config()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    app = LaserMirrorApp(root, Path(args.config), force_safe_mode=args.safe_mode, force_write_mode=args.write_mode)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0
