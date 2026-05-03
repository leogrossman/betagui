from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import threading
import time
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .config import AppConfig
from .geometry import LaserMirrorGeometry
from .hardware import (
    MOTOR_LABELS,
    MOTOR_PVS,
    PVFactory,
    SIGNAL_PRESETS,
    DisconnectedController,
    DisconnectedSignalBackend,
    MirrorController,
    SignalBackend,
    SimulatedSignalBackend,
    build_signal_backend,
)
from .layout import default_optics_layout
from .models import (
    BestPointRecommendation,
    MeasurementRecord,
    MirrorAngles,
    MotorTargets,
    PassiveSample,
    PenTestPoint,
    UndulatorTarget,
)
from .monitoring import SessionRecorder
from .pen_test import build_pen_test_sequence
from .scan import ScanContext, ScanRunner, build_angle_scan_points, build_spiral_scan_points
from .state import load_state, save_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSMB laser mirror scan tool")
    parser.add_argument("--safe-mode", action="store_true", help="Use real EPICS readback/signal, but keep motor writes disabled")
    parser.add_argument("--demo-mode", action="store_true", help="Run fully offline with simulated motors and simulated signal")
    parser.add_argument("--write-mode", action="store_true", help="Enable real motor writes (never needed for safe demos)")
    parser.add_argument("--config", default="laser_mirrors_config.json", help="Path to JSON config file")
    return parser


class ToolTip:
    """Small hover tooltip for compact control-room explanations."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _show(self, _event=None) -> None:
        if self._window is not None:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            win,
            text=self.text,
            justify="left",
            background="#fff7d6",
            relief="solid",
            borderwidth=1,
            wraplength=320,
            padx=8,
            pady=6,
        )
        label.pack()
        self._window = win

    def _hide(self, _event=None) -> None:
        if self._window is not None:
            self._window.destroy()
            self._window = None


class LaserMirrorApp:
    """Control-room UI for mirror steering, passive monitoring, and diagnostics.

    The design intentionally keeps the previously validated motion core:
    `MirrorController.move_absolute_group(...)` remains the single place where
    real motor motion is executed. New features such as passive monitoring and
    pen testing therefore reuse the same safety checks instead of bypassing
    them with ad-hoc PV writes.
    """

    def __init__(
        self,
        root: tk.Tk,
        config_path: Path,
        force_safe_mode: bool = False,
        force_write_mode: bool = False,
        force_demo_mode: bool = False,
    ):
        self.root = root
        self.root.title("SSMB Laser Mirror Angle Scan Tool")
        self.config_path = config_path
        self.config = AppConfig.load(config_path)
        self.demo_mode = force_demo_mode
        if force_demo_mode:
            self.config.controller.safe_mode = True
            self.config.controller.write_mode = False
        if force_safe_mode:
            self.config.controller.safe_mode = True
            self.config.controller.write_mode = False
        if force_write_mode:
            self.config.controller.write_mode = True
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        self.output_root = self._resolve_output_root(self.config.controller.output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.session_recorder = SessionRecorder(self.output_root)
        self.session_start = time.time()
        self.measurements: list[MeasurementRecord] = []
        self.best_point: BestPointRecommendation | None = None
        self.pen_test_rows: list[dict[str, float | str]] = []
        self._poll_after_id: str | None = None
        self._signal_history: deque[float] = deque(maxlen=max(1, self.config.controller.p1_average_samples))
        self._signal_trace: deque[tuple[float, float]] = deque(maxlen=400)
        self._passive_samples: deque[PassiveSample] = deque(maxlen=max(200, self.config.controller.motor_history_points * 4))
        self._motor_history: dict[str, deque[tuple[float, float]]] = {
            key: deque(maxlen=max(50, self.config.controller.motor_history_points)) for key in MOTOR_PVS
        }
        self._last_passive_sample: PassiveSample | None = None
        self._pen_test_thread: threading.Thread | None = None
        self._pen_test_stop = threading.Event()
        self._build_state()
        self._build_ui()
        self._restore_legacy_state()
        self._connect_backends()
        self._draw_geometry_preview()
        self._schedule_signal_poll()
        self._log(f"Application session directory: {self.session_recorder.session_dir}")

    def _resolve_output_root(self, configured: str) -> Path:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (self.config_path.parent / path).resolve()
        return path

    def _build_state(self) -> None:
        self.safe_mode_var = tk.BooleanVar(value=self.config.controller.safe_mode)
        self.write_mode_var = tk.BooleanVar(value=self.config.controller.write_mode)
        self.signal_preset_var = tk.StringVar(value=self._preset_from_pv(self.config.controller.signal_pv))
        self.signal_pv_var = tk.StringVar(value=self.config.controller.signal_pv)
        self.signal_label_var = tk.StringVar(value=self.config.controller.signal_label)
        self.output_root_var = tk.StringVar(value=str(self.output_root))
        self.poll_interval_var = tk.IntVar(value=self.config.controller.p1_poll_interval_ms)
        self.average_samples_var = tk.IntVar(value=self.config.controller.p1_average_samples)
        self.max_step_var = tk.DoubleVar(value=self.config.controller.max_step_per_put)
        self.delay_var = tk.DoubleVar(value=self.config.controller.inter_put_delay_s)
        self.settle_var = tk.DoubleVar(value=self.config.controller.settle_s)
        self.max_delta_var = tk.DoubleVar(value=self.config.controller.max_delta_from_reference)
        self.max_absolute_move_var = tk.DoubleVar(value=self.config.controller.max_absolute_move_steps)
        self.use_manual_motor_limits_var = tk.BooleanVar(value=self.config.controller.use_manual_motor_limits)
        self.ignore_invalid_ioc_limits_var = tk.BooleanVar(value=self.config.controller.ignore_invalid_ioc_limits)
        self.manual_limit_vars = {
            key: {
                "llm": tk.DoubleVar(value=getattr(self.config.controller, f"{key}_llm")),
                "hlm": tk.DoubleVar(value=getattr(self.config.controller, f"{key}_hlm")),
            }
            for key in MOTOR_PVS
        }
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
        self.interpolate_angle_map_var = tk.BooleanVar(value=False)
        self.spiral_step_x_var = tk.DoubleVar(value=self.config.scan.spiral_step_x)
        self.spiral_step_y_var = tk.DoubleVar(value=self.config.scan.spiral_step_y)
        self.spiral_turns_var = tk.IntVar(value=self.config.scan.spiral_turns)
        self.spiral_target_var = tk.StringVar(value=self.config.scan.spiral_target)
        self.spiral_strategy_var = tk.StringVar(value=self.config.scan.spiral_strategy)
        self.manual_motor_var = tk.StringVar(value="m2_horizontal")
        self.manual_delta_var = tk.DoubleVar(value=1.0)
        self.manual_absolute_var = tk.DoubleVar(value=0.0)
        self.passive_x_motor_var = tk.StringVar(value="m1_horizontal")
        self.passive_y_motor_var = tk.StringVar(value="m2_horizontal")
        self.passive_metric_var = tk.StringVar(value="selected_signal")
        self.passive_view_mode_var = tk.StringVar(value="motor_map")
        self.passive_history_limit_var = tk.IntVar(value=4000)
        self.passive_history_start_back_var = tk.IntVar(value=4000)
        self.passive_history_end_back_var = tk.IntVar(value=0)
        self.passive_status_var = tk.StringVar(value="No passive sweep reconstructed yet.")
        self.pen_motor_var = tk.StringVar(value="m2_horizontal")
        self.pen_start_var = tk.DoubleVar(value=self.config.controller.pen_test_start_steps)
        self.pen_stop_var = tk.DoubleVar(value=self.config.controller.pen_test_stop_steps)
        self.pen_increment_var = tk.DoubleVar(value=self.config.controller.pen_test_step_increment)
        self.pen_cycles_var = tk.IntVar(value=self.config.controller.pen_test_cycles_per_level)
        self.pen_pause_var = tk.DoubleVar(value=self.config.controller.pen_test_pause_s)
        self.pen_status_var = tk.StringVar(value="Pen test idle.")
        self.mode_help_var = tk.StringVar(value=self._scan_mode_help_text())
        self.scale_summary_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Idle")
        self.runtime_var = tk.StringVar(value="Backends not connected yet.")
        self.best_var = tk.StringVar(value="No best point yet.")
        self.last_export_var = tk.StringVar(value="No scan saved yet.")
        self.search_status_var = tk.StringVar(value="No position search run yet.")
        self.signal_live_var = tk.StringVar(value="—")
        self.signal_avg_var = tk.StringVar(value="—")
        self.signal_std_var = tk.StringVar(value="—")
        self.signal_samples_var = tk.StringVar(value="0")
        self.signal_last_update_var = tk.StringVar(value="Never")
        self.reference_var = tk.StringVar(value="Reference not captured yet.")
        self.state_path_var = tk.StringVar(value=self.config.controller.state_file_path)
        self.current_reference_steps: dict[str, float] = {key: 0.0 for key in MOTOR_PVS}
        self.pending_refine_preview: list[ScanPoint] = []
        self._canvas_points: dict[str, list[dict[str, object]]] = {}
        self.legacy_state_path = (self.config_path.parent / self.config.controller.state_file_path).resolve()
        self.motor_recovery_path = (self.config_path.parent / self.config.controller.motor_recovery_path).resolve()
        self.last_command_path = (self.config_path.parent / self.config.controller.last_command_path).resolve()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)
        self.overview_frame = ttk.Frame(notebook, padding=10)
        self.manual_frame = ttk.Frame(notebook, padding=10)
        self.angle_frame = ttk.Frame(notebook, padding=10)
        self.advanced_frame = ttk.Frame(notebook, padding=10)
        self.spiral_frame = ttk.Frame(notebook, padding=10)
        self.optics_frame = ttk.Frame(notebook, padding=10)
        self.passive_frame = ttk.Frame(notebook, padding=10)
        self.pen_frame = ttk.Frame(notebook, padding=10)
        self.debug_frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.overview_frame, text="Overview")
        notebook.add(self.manual_frame, text="Manual control")
        notebook.add(self.angle_frame, text="Angle scan")
        notebook.add(self.advanced_frame, text="Advanced scans")
        notebook.add(self.spiral_frame, text="Position search")
        notebook.add(self.optics_frame, text="Optics / Geometry")
        notebook.add(self.passive_frame, text="Passive monitor")
        notebook.add(self.pen_frame, text="Controller pen test")
        notebook.add(self.debug_frame, text="Debug / Logs")
        self._build_overview()
        self._build_manual()
        self._build_angle()
        self._build_advanced()
        self._build_spiral()
        self._build_optics()
        self._build_passive()
        self._build_pen_test()
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
        ttk.Checkbutton(top, text="Safe mode (real readback, no writes)", variable=self.safe_mode_var, command=self._safe_mode_changed).grid(row=0, column=0, columnspan=2, sticky="w")
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
        ttk.Checkbutton(top, text="Use manual motor limits", variable=self.use_manual_motor_limits_var).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(top, text="Ignore invalid IOC HLM/LLM", variable=self.ignore_invalid_ioc_limits_var).grid(row=12, column=0, columnspan=2, sticky="w")
        ttk.Label(top, text="Output root").grid(row=13, column=0, sticky="w", pady=(8, 0))
        output_row = ttk.Frame(top)
        output_row.grid(row=13, column=1, sticky="ew", pady=(8, 0))
        ttk.Entry(output_row, textvariable=self.output_root_var, width=28).pack(side="left", fill="x", expand=True)
        ttk.Button(output_row, text="Browse…", command=self._browse_output_root).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Reconnect backends", command=self._connect_backends).grid(row=14, column=0, pady=(8, 0), sticky="w")
        ttk.Button(top, text="Save config", command=self._save_config).grid(row=14, column=1, pady=(8, 0), sticky="e")
        self._add_help_button(
            top,
            14,
            "The selected signal preset is what all live plots and scans color by.\n"
            "Safe mode still reads the real EPICS signal and motor readback.\n"
            "In write mode every move still goes through the same ramped, DMOV-waiting safety path.",
        )

        target = ttk.LabelFrame(left, text="Undulator-space target", padding=10)
        target.pack(fill="x", pady=(10, 0))
        self._add_labeled_entry(target, "Offset X [mm]", self.offset_x_var, 0)
        self._add_labeled_entry(target, "Offset Y [mm]", self.offset_y_var, 1)
        ttk.Button(target, text="Save current mirror state", command=self._save_motor_recovery).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Return to startup reference", command=self._return_to_reference).grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Return to saved motor state", command=self._return_to_recovery_state).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(target, text="Capture current RBV as reference", command=self._capture_reference).grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(target, textvariable=self.reference_var, wraplength=580, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._add_help_button(
            target,
            4,
            "Reference RBV is the anchor for all computed angle-scan targets.\n"
            "Always capture a fresh reference when the controller has been restarted or when you are unsure whether the saved center is still valid.",
        )

        limits = ttk.LabelFrame(left, text="Motor limits / overrides", padding=10)
        limits.pack(fill="x", pady=(10, 0))
        ttk.Label(limits, text="Motor").grid(row=0, column=0, sticky="w")
        ttk.Label(limits, text="Manual LLM").grid(row=0, column=1, sticky="e")
        ttk.Label(limits, text="Manual HLM").grid(row=0, column=2, sticky="e")
        for row, key in enumerate(MOTOR_PVS, start=1):
            ttk.Label(limits, text=MOTOR_LABELS.get(key, key)).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(limits, textvariable=self.manual_limit_vars[key]["llm"], width=10).grid(row=row, column=1, sticky="e", padx=(6, 0), pady=2)
            ttk.Entry(limits, textvariable=self.manual_limit_vars[key]["hlm"], width=10).grid(row=row, column=2, sticky="e", padx=(6, 0), pady=2)
        buttons = ttk.Frame(limits)
        buttons.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Seed around current RBV ±250", command=self._seed_manual_limits_from_current).pack(side="left")
        ttk.Button(buttons, text="Copy IOC limits", command=self._copy_ioc_limits_to_manual).pack(side="left", padx=(8, 0))
        ttk.Label(limits, text="If IOC HLM/LLM are 0 or otherwise broken, enable manual limits here and reconnect.", wraplength=640, justify="left").grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.motor_tree = ttk.Treeview(
            left,
            columns=("motor", "pv", "rbv", "val", "llm", "hlm", "limit_src", "dmov", "movn", "stat", "sevr", "egu"),
            show="headings",
            height=8,
        )
        for key, title, width in [
            ("motor", "Motor", 150),
            ("pv", "PV", 170),
            ("rbv", "RBV", 80),
            ("val", "VAL", 80),
            ("llm", "LLM", 80),
            ("hlm", "HLM", 80),
            ("limit_src", "Limit src", 90),
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
            self.motor_tree.insert(
                "",
                "end",
                iid=key,
                text=key,
                values=(MOTOR_LABELS.get(key, key), pv, "", "", "", "", "", "", "", "", "", ""),
            )

        self.signal_box = ttk.LabelFrame(right, text="Live signal readout", padding=10)
        self.signal_box.pack(fill="x")
        self._labeled_value(self.signal_box, "Label", self.signal_label_var, 0)
        self._labeled_value(self.signal_box, "Instantaneous", self.signal_live_var, 1)
        self._labeled_value(self.signal_box, "Rolling average", self.signal_avg_var, 2)
        self._labeled_value(self.signal_box, "Rolling std", self.signal_std_var, 3)
        self._labeled_value(self.signal_box, "Samples in window", self.signal_samples_var, 4)
        self._labeled_value(self.signal_box, "Last update", self.signal_last_update_var, 5)
        self.signal_trace_canvas = tk.Canvas(self.signal_box, width=360, height=180, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.signal_trace_canvas.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        info = ttk.LabelFrame(right, text="Runtime", padding=10)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, textvariable=self.runtime_var, wraplength=420, justify="left").pack(anchor="w")
        ttk.Label(info, text=f"Legacy state file: {self.legacy_state_path}", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, text=f"Motor recovery file: {self.motor_recovery_path}", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, text=f"Last command file: {self.last_command_path}", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(info, text=f"Application session: {self.session_recorder.session_dir}", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))

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
                "Every real command is written to the debug log, session log, and last-command file.\n"
                "Use tiny steps first. Prefer graceful scan stop over hard `.STOP` unless needed."
            ),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")
        self._attach_tooltip(
            box,
            "Manual moves use the same safe ramped `.VAL` logic as scans.\n"
            "That means the controller sees small step layers with DMOV waits instead of one violent jump.",
        )

    def _build_angle(self) -> None:
        controls = ttk.LabelFrame(self.angle_frame, text="Standard fixed-position angle scan", padding=10)
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
        self._add_labeled_combo(controls, "Sweep plane", self.scan_mode_var, ["vertical_only", "horizontal_only"], 8)
        self._add_labeled_combo(controls, "Compensation mode", self.solve_mode_var, ["mirror1_primary", "mirror2_primary"], 9)
        self._add_labeled_combo(controls, "Objective", self.objective_var, ["max", "min"], 10)
        ttk.Checkbutton(controls, text="Interpolated background", variable=self.interpolate_angle_map_var, command=self._refresh_plots).grid(row=11, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Explain scan modes", command=self._show_scan_mode_help).grid(row=12, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Why this scan?", command=self._show_angle_theory).grid(row=12, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Preview commands", command=self._preview_angle_scan).grid(row=13, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start angle scan", command=self._start_angle_scan).grid(row=13, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Request stop", command=self._stop_scan).grid(row=14, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Move to best point", command=self._move_to_best_point).grid(row=14, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.mode_help_var, wraplength=340, justify="left").grid(row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.status_var, wraplength=340, justify="left").grid(row=16, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.best_var, wraplength=340, justify="left").grid(row=17, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.last_export_var, wraplength=340, justify="left").grid(row=18, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Save angle plot (.ps)", command=lambda: self._save_canvas_postscript(self.heatmap_canvas, "angle_scan_map.ps")).grid(row=19, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.scale_summary_var, wraplength=340, justify="left").grid(row=20, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._add_help_button(
            controls,
            20,
            "2D angle map meaning:\n"
            "• each dot = one actually measured scan point\n"
            "• the active scan plane changes while the orthogonal plane stays fixed\n"
            "• x/y coordinates = requested interaction-angle coordinates at the undulator, not raw motor coordinates\n"
            "• color = average of the selected signal over the samples-per-point window\n"
            "• cross marker = current recommended best point (max or min)\n\n"
            "This is the standard workflow after you already found a good laser position: keep the hit position fixed, vary angle, and identify the optimum."
            "\nOptional interpolation only paints a visual background between measured points; the dots remain the ground truth.",
        )

        self.heatmap_canvas = tk.Canvas(plots, width=760, height=380, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.heatmap_canvas.pack(fill="both", expand=True)
        self.progress_canvas = tk.Canvas(plots, width=760, height=240, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.progress_canvas.pack(fill="x", pady=(10, 0))
        self._attach_tooltip(
            self.heatmap_canvas,
            "Angle heatmap:\n"
            "The plotted points are the measured scan samples.\n"
            "Colors encode the average selected signal at each point.\n"
            "For separate horizontal-only and vertical-only runs, the canvas can combine them into a quasi-2D cross map.\n"
            "Optional interpolation paints a tiled background between measured points, but the dots remain the real data.",
        )
        self._attach_tooltip(
            self.progress_canvas,
            "Progress trace:\n"
            "Signal average vs scan index in acquisition order.\n"
            "Useful for spotting drift, hysteresis, or a time trend during the scan.",
        )
        self.heatmap_canvas.bind("<Button-1>", lambda event: self._inspect_canvas_point("angle", event))
        self.progress_canvas.bind("<Button-1>", lambda event: self._inspect_canvas_point("progress", event))

    def _build_advanced(self) -> None:
        info = ttk.LabelFrame(self.advanced_frame, text="Experimental / advanced scan modes", padding=10)
        info.pack(fill="x")
        ttk.Label(
            info,
            text=(
                "Use this tab when you want broader exploratory scans rather than the standard one-plane fixed-position angle scan.\n"
                "The controls below still drive the same scan engine and the same saved output files."
            ),
            wraplength=820,
            justify="left",
        ).pack(anchor="w")

        controls = ttk.LabelFrame(self.advanced_frame, text="Advanced angle presets", padding=10)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="Set 2D angle map", command=self._configure_advanced_2d).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(controls, text="Set direct two-mirror solve", command=self._configure_direct_target_mode).grid(row=0, column=1, sticky="ew")
        ttk.Label(
            controls,
            text=(
                "2D angle map: scans horizontal and vertical angle together.\n"
                "Direct two-mirror solve: both mirrors are solved from the requested undulator-space target instead of using one primary mirror plus a compensator."
            ),
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_optics(self) -> None:
        left = ttk.Frame(self.optics_frame)
        right = ttk.Frame(self.optics_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.optics_frame.columnconfigure(0, weight=3)
        self.optics_frame.columnconfigure(1, weight=2)
        self.optics_frame.rowconfigure(0, weight=1)

        schematic = ttk.LabelFrame(left, text="PoP II steering layout", padding=10)
        schematic.pack(fill="both", expand=True)
        self.geometry_canvas = tk.Canvas(schematic, width=780, height=480, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.geometry_canvas.pack(fill="both", expand=True)
        self._attach_tooltip(
            self.geometry_canvas,
            "This is the ordered PoP II steering schematic.\n"
            "Mirror 1 → Mirror 2 → undulator distances stay exact.\n"
            "Upstream optics are drawn in documented order for context, not as surveyed CAD coordinates.",
        )

        helper = ttk.LabelFrame(right, text="Angle / step scale helper", padding=10)
        helper.pack(fill="x")
        ttk.Label(
            helper,
            text=(
                "Use this to sanity-check the scan span against motor steps.\n"
                "The estimates below use the current angle spans and the calibrated µrad/step factors."
            ),
            wraplength=360,
            justify="left",
        ).pack(anchor="w")
        ttk.Label(helper, textvariable=self.scale_summary_var, wraplength=360, justify="left").pack(anchor="w", pady=(8, 0))

        notes = ttk.LabelFrame(right, text="Sweep / solve interpretation", padding=10)
        notes.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(
            notes,
            text=(
                "Sweep mode chooses which undulator-space angle coordinates are scanned.\n"
                "Solve mode chooses how the mirrors cooperate to realize that target.\n\n"
                "Recommended default:\n"
                "• vertical_only\n"
                "• mirror1_primary or mirror2_primary\n"
                "That keeps the beam position fixed as well as possible while varying angle in one plane."
            ),
            wraplength=360,
            justify="left",
        ).pack(anchor="w")

    def _build_spiral(self) -> None:
        controls = ttk.LabelFrame(self.spiral_frame, text="Best-position finder", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.LabelFrame(self.spiral_frame, text="Position-search map", padding=10)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.spiral_frame.columnconfigure(1, weight=1)
        self.spiral_frame.rowconfigure(0, weight=1)
        self._add_labeled_combo(controls, "Moving mirror pair", self.spiral_target_var, ["mirror2", "mirror1"], 0)
        self._add_labeled_combo(controls, "Search strategy", self.spiral_strategy_var, ["classic_spiral", "local_refine"], 1)
        self._add_labeled_entry(controls, "Step X [steps]", self.spiral_step_x_var, 2)
        self._add_labeled_entry(controls, "Step Y [steps]", self.spiral_step_y_var, 3)
        self._add_labeled_entry(controls, "Turns", self.spiral_turns_var, 4)
        ttk.Button(controls, text="Preview commands", command=self._preview_spiral_scan).grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start search", command=self._start_spiral_scan).grid(row=5, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Preview local refine", command=self._preview_local_refine).grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start local refine", command=self._start_local_refine).grid(row=6, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Move to best point", command=self._move_to_best_point).grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Request stop", command=self._stop_scan).grid(row=7, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Save search plot (.ps)", command=lambda: self._save_canvas_postscript(self.spiral_canvas, "position_search_map.ps")).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.search_status_var, wraplength=340, justify="left").grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._add_help_button(
            controls,
            9,
            "Position finder:\n"
            "This is the first step of the workflow. Search for the best laser position using one mirror pair, then use that result as the center for the fixed-position angle scan.\n"
            "Classic spiral does a coarse search. Local refine uses the current best point as the center and searches a tighter neighborhood.",
        )
        self.spiral_canvas = tk.Canvas(plots, width=760, height=440, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.spiral_canvas.pack(fill="both", expand=True)
        self._attach_tooltip(
            self.spiral_canvas,
            "Position-search map:\n"
            "Each point is plotted at the commanded mirror-pair step position and colored by the measured signal average.\n"
            "The black cross is the current best measured point. Blue hollow markers indicate the next suggested local-refine region.",
        )
        self.spiral_canvas.bind("<Button-1>", lambda event: self._inspect_canvas_point("spiral", event))

    def _build_passive(self) -> None:
        controls = ttk.LabelFrame(self.passive_frame, text="Passive monitor / reconstruction", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.Frame(self.passive_frame)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.passive_frame.columnconfigure(1, weight=1)
        self.passive_frame.rowconfigure(0, weight=1)
        self._add_labeled_combo(controls, "View mode", self.passive_view_mode_var, ["motor_map", "time_vs_metric"], 0)
        self._add_labeled_combo(controls, "Metric", self.passive_metric_var, self._passive_metric_choices(), 1)
        self._add_labeled_entry(controls, "Recent samples", self.passive_history_limit_var, 2)
        self._add_labeled_entry(controls, "Start back", self.passive_history_start_back_var, 3)
        self._add_labeled_entry(controls, "End back", self.passive_history_end_back_var, 4)
        self._add_labeled_combo(controls, "X motor", self.passive_x_motor_var, list(MOTOR_PVS.keys()), 5)
        self._add_labeled_combo(controls, "Y motor", self.passive_y_motor_var, list(MOTOR_PVS.keys()), 6)
        ttk.Button(controls, text="Clear passive buffer", command=self._clear_passive_buffer).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Save passive plot (.ps)", command=lambda: self._save_canvas_postscript(self.passive_map_canvas, "passive_reconstruction.ps")).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.passive_status_var, wraplength=340, justify="left").grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(
            controls,
            text=(
                "This tab keeps logging passive motor RBVs plus the selected signal at every poll.\n"
                "It also records the other configured live sensors, so you can recolor the same passive history by P1, sigma, or center signals later."
            ),
            wraplength=340,
            justify="left",
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._add_help_button(
            controls,
            10,
            "Passive mode does not need this GUI to move the mirrors.\n"
            "It records all four motor RBVs plus the configured live signals every poll and lets you re-view the recent history in different ways.",
        )

        map_box = ttk.LabelFrame(plots, text="Observed parameter-space map", padding=10)
        map_box.pack(fill="both", expand=True)
        self.passive_map_canvas = tk.Canvas(map_box, width=760, height=320, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.passive_map_canvas.pack(fill="both", expand=True)
        trend_box = ttk.LabelFrame(plots, text="Signal and motor traces", padding=10)
        trend_box.pack(fill="both", expand=True, pady=(10, 0))
        self.passive_trend_canvas = tk.Canvas(trend_box, width=760, height=260, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.passive_trend_canvas.pack(fill="both", expand=True)
        self._attach_tooltip(
            self.passive_map_canvas,
            "Passive view:\n"
            "You can show either a motor-parameter map or a time-vs-metric plot.\n"
            "Click a point to inspect all four motor positions and the recorded signal values at that sample.",
        )
        self.passive_map_canvas.bind("<Button-1>", lambda event: self._inspect_canvas_point("passive_map", event))
        self.passive_trend_canvas.bind("<Button-1>", lambda event: self._inspect_canvas_point("passive_trend", event))

    def _build_pen_test(self) -> None:
        controls = ttk.LabelFrame(self.pen_frame, text="Experimental controller pen test", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.LabelFrame(self.pen_frame, text="Pen-test signal response", padding=10)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.pen_frame.columnconfigure(1, weight=1)
        self.pen_frame.rowconfigure(0, weight=1)
        self._add_labeled_combo(controls, "Motor", self.pen_motor_var, list(MOTOR_PVS.keys()), 0)
        self._add_labeled_entry(controls, "Start amplitude [steps]", self.pen_start_var, 1)
        self._add_labeled_entry(controls, "Stop amplitude [steps]", self.pen_stop_var, 2)
        self._add_labeled_entry(controls, "Increment [steps]", self.pen_increment_var, 3)
        self._add_labeled_entry(controls, "Cycles / level", self.pen_cycles_var, 4)
        self._add_labeled_entry(controls, "Pause [s]", self.pen_pause_var, 5)
        ttk.Button(controls, text="Preview pen test", command=self._preview_pen_test).grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Start pen test", command=self._start_pen_test).grid(row=6, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Request stop", command=self._stop_pen_test).grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="STOP all (emergency)", command=self._hard_stop).grid(row=7, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(controls, textvariable=self.pen_status_var, wraplength=340, justify="left").grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(
            controls,
            text=(
                "This is intentionally experimental and conservative.\n"
                "It ramps one motor around the captured reference in tiny back-and-forth moves,\n"
                "returns to reference after each level, and logs signal + alarm state to help diagnose IOC/controller crashes."
            ),
            wraplength=340,
            justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._add_help_button(
            controls,
            9,
            "Pen test:\n"
            "A very cautious stress probe for the motor controller.\n"
            "It moves one motor by small amplitudes around the current reference, returns to center after each level, and logs alarm/state behavior.",
        )

        self.pen_canvas = tk.Canvas(plots, width=760, height=420, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.pen_canvas.pack(fill="both", expand=True)
        self._attach_tooltip(
            self.pen_canvas,
            "Pen-test trace:\n"
            "Signal response over the commanded diagnostic sequence.\n"
            "Use it together with the logged alarm and DMOV/MOVN state to understand controller limits.",
        )

    def _build_debug(self) -> None:
        ttk.Label(self.debug_frame, text="Diagnostics, planned commands, and runtime logs.").pack(anchor="w")
        row = ttk.Frame(self.debug_frame)
        row.pack(fill="x", pady=(8, 8))
        ttk.Button(row, text="Refresh motor diagnostics", command=self._refresh_motor_table).pack(side="left")
        ttk.Button(row, text="Export diagnostics JSON", command=self._export_diagnostics).pack(side="left", padx=6)
        self.debug_text = tk.Text(self.debug_frame, width=140, height=32)
        self.debug_text.pack(fill="both", expand=True)

    def _attach_tooltip(self, widget: tk.Widget, text: str) -> None:
        ToolTip(widget, text)

    def _add_help_button(self, parent: ttk.Widget, row: int, text: str) -> None:
        button = ttk.Button(parent, text="?", width=2, command=lambda: messagebox.showinfo("Help", text))
        button.grid(row=row, column=2, padx=(6, 0), sticky="w")
        self._attach_tooltip(button, text)

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

    def _passive_metric_choices(self) -> list[str]:
        return ["selected_signal"] + list(SIGNAL_PRESETS.keys())

    def _scan_mode_help_text(self) -> str:
        return (
            "Standard use is a 1D PRIMARY scan in one plane at a time: horizontal-only or vertical-only,\n"
            "with one mirror driving and the other counter-steering to keep the same interaction point.\n"
            "Start with mirror1_primary if mirror 1 should be the driving mirror and mirror 2 should hold the point.\n"
            "Use mirror2_primary if commissioning shows the opposite is more stable. two_mirror_target is a direct\n"
            "undulator-space solve and is less close to the standard fixed-position angle sweep."
        )

    def _show_scan_mode_help(self) -> None:
        messagebox.showinfo(
            "Scan modes",
            (
                "Sweep modes:\n"
                "• horizontal_only: change horizontal interaction angle, keep vertical fixed.\n"
                "• vertical_only: change vertical interaction angle, keep horizontal fixed.\n"
                "• both_2d: 2D extension when you want a full angle map instead of a single-plane line scan.\n\n"
                "Solve modes:\n"
                "• two_mirror_target: solve both mirrors directly from the desired undulator offset + angle.\n"
                "  Good for target-space scans, but not the most literal fixed-position angle sweep.\n"
                "• mirror1_primary: sweep mirror 1, analytically solve mirror 2 to keep the point fixed.\n"
                "• mirror2_primary: sweep mirror 2, analytically solve mirror 1 to keep the point fixed.\n\n"
                "Closest to the standard operating idea:\n"
                "Use one of the PRIMARY modes together with horizontal_only or vertical_only.\n"
                "The right default depends on which mirror you trust more as the driving mirror in the control room.\n"
                "This app defaults to mirror1_primary."
            ),
        )

    def _configure_advanced_2d(self) -> None:
        self.scan_mode_var.set("both_2d")
        self.mode_help_var.set(
            "Advanced 2D map enabled. This scans both horizontal and vertical angle together.\n"
            "Use it after the 1D scans are behaving well."
        )
        self._refresh_plots()

    def _configure_direct_target_mode(self) -> None:
        self.solve_mode_var.set("two_mirror_target")
        self.mode_help_var.set(
            "Direct target solve enabled. Both mirrors are solved directly from the requested undulator-space target.\n"
            "This is useful for experimentation, but less close to the standard compensating one-plane scan."
        )
        self._refresh_plots()

    def _show_angle_theory(self) -> None:
        messagebox.showinfo(
            "Why this angle scan exists",
            (
                "The goal is not to scan one mirror in isolation. The point is to vary the interaction angle of the laser at the undulator "
                "while keeping the hit point in space as fixed as possible.\n\n"
                "That is why two mirrors matter:\n"
                "• one mirror is the deliberate steering mirror\n"
                "• the other mirror counter-steers so the beam still hits the same interaction point\n\n"
                "Standard operating interpretation:\n"
                "• do a horizontal-only scan when you want to study horizontal crossing-angle sensitivity\n"
                "• do a vertical-only scan when you want to study vertical crossing-angle sensitivity\n"
                "• use both_2d only when you explicitly want the full 2D landscape\n\n"
                "Physics meaning of the plot:\n"
                "• in both_2d: x/y axes are the horizontal/vertical interaction angles and color is the measured response\n"
                "• in horizontal_only or vertical_only: the plot becomes a proper 1D signal-vs-angle scan in the active plane\n\n"
                "Why not plot only motor steps?\n"
                "• motor coordinates are implementation details\n"
                "• the experiment cares about overlap and modulation versus interaction angle\n"
                "• therefore angle space is the physics-facing map, while the exact motor targets are still saved in the session files\n\n"
                "What can be optimized:\n"
                "• P1 or P3 if you want a physics-facing overlap / modulation metric\n"
                "• QPD sigmaX / sigmaY / centerX if you want a transport or beam-shape diagnostic instead\n\n"
                "Solve modes:\n"
                "• two_mirror_target: solve both mirrors from the requested undulator-space target directly\n"
                "• mirror1_primary: mirror 1 is the scanned mirror, mirror 2 counter-steers to hold point\n"
                "• mirror2_primary: mirror 2 is the scanned mirror, mirror 1 counter-steers to hold point\n\n"
                "The most literal implementation of the fixed-position angle sweep is one of the primary modes."
            ),
        )

    def _pull_ui_into_config(self) -> None:
        self.config.controller.safe_mode = self.safe_mode_var.get()
        self.config.controller.write_mode = self.write_mode_var.get()
        preset = self.signal_preset_var.get()
        if preset in SIGNAL_PRESETS:
            label, pv = SIGNAL_PRESETS[preset]
            self.signal_pv_var.set(pv)
            self.signal_label_var.set(label)
        self.config.controller.signal_pv = self.signal_pv_var.get()
        self.config.controller.signal_label = self.signal_label_var.get()
        self.config.controller.output_root = self.output_root_var.get()
        self.config.controller.p1_poll_interval_ms = max(100, int(self.poll_interval_var.get()))
        self.config.controller.p1_average_samples = max(1, int(self.average_samples_var.get()))
        self.config.controller.max_step_per_put = max(0.1, float(self.max_step_var.get()))
        self.config.controller.inter_put_delay_s = max(0.0, float(self.delay_var.get()))
        self.config.controller.settle_s = max(0.0, float(self.settle_var.get()))
        self.config.controller.max_delta_from_reference = max(1.0, float(self.max_delta_var.get()))
        self.config.controller.max_absolute_move_steps = max(1.0, float(self.max_absolute_move_var.get()))
        self.config.controller.use_manual_motor_limits = bool(self.use_manual_motor_limits_var.get())
        self.config.controller.ignore_invalid_ioc_limits = bool(self.ignore_invalid_ioc_limits_var.get())
        for key in MOTOR_PVS:
            setattr(self.config.controller, f"{key}_llm", float(self.manual_limit_vars[key]["llm"].get()))
            setattr(self.config.controller, f"{key}_hlm", float(self.manual_limit_vars[key]["hlm"].get()))
        self.config.controller.startup_offset_x_mm = float(self.offset_x_var.get())
        self.config.controller.startup_offset_y_mm = float(self.offset_y_var.get())
        self.config.controller.pen_test_start_steps = max(0.1, float(self.pen_start_var.get()))
        self.config.controller.pen_test_stop_steps = max(self.config.controller.pen_test_start_steps, float(self.pen_stop_var.get()))
        self.config.controller.pen_test_step_increment = max(0.1, float(self.pen_increment_var.get()))
        self.config.controller.pen_test_cycles_per_level = max(1, int(self.pen_cycles_var.get()))
        self.config.controller.pen_test_pause_s = max(0.0, float(self.pen_pause_var.get()))
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
        self.config.scan.spiral_target = self.spiral_target_var.get()
        self.config.scan.spiral_strategy = self.spiral_strategy_var.get()
        self._update_scale_summary()

    def _save_config(self) -> None:
        self._pull_ui_into_config()
        self.config.save(self.config_path)
        self._log(f"Saved config to {self.config_path}")

    def _browse_output_root(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_root_var.get() or str(self.config_path.parent))
        if chosen:
            self.output_root_var.set(chosen)
            self._log(f"Selected output root: {chosen}")

    def _safe_mode_changed(self) -> None:
        if self.safe_mode_var.get():
            self.write_mode_var.set(False)
        self._connect_backends()

    def _write_mode_changed(self) -> None:
        if self.write_mode_var.get() and self.safe_mode_var.get():
            self.safe_mode_var.set(False)
        self._connect_backends()

    def _update_scale_summary(self) -> None:
        span_x = abs(float(self.span_x_var.get()))
        span_y = abs(float(self.span_y_var.get()))
        half_x = span_x / 2.0
        half_y = span_y / 2.0
        values = {
            "M1 H": self.geometry.angle_delta_to_steps(half_x, "x", 1),
            "M2 H": self.geometry.angle_delta_to_steps(half_x, "x", 2),
            "M1 V": self.geometry.angle_delta_to_steps(half_y, "y", 1),
            "M2 V": self.geometry.angle_delta_to_steps(half_y, "y", 2),
        }
        self.scale_summary_var.set(
            "Half-span step estimate from current angle span:\n"
            f"Horizontal ±{half_x:.1f} µrad -> M1 ≈ {values['M1 H']} steps, M2 ≈ {values['M2 H']} steps\n"
            f"Vertical ±{half_y:.1f} µrad -> M1 ≈ {values['M1 V']} steps, M2 ≈ {values['M2 V']} steps\n"
            "This is only the angle part. Counter-steering / fixed-position compensation can shift the actual targets."
        )

    def _connect_backends(self) -> None:
        self._pull_ui_into_config()
        self.output_root = self._resolve_output_root(self.output_root_var.get())
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        self._update_scale_summary()
        if self.demo_mode:
            self.factory = PVFactory(True)
            self.controller = MirrorController(self.config.controller, self.factory, self._log)
            self.current_reference_steps = self.controller.capture_reference()
            self.signal_backend = SimulatedSignalBackend(self.signal_label_var.get() or "Simulated signal")
            self.passive_signal_backends = {key: SimulatedSignalBackend(label) for key, (label, _pv) in SIGNAL_PRESETS.items()}
            self.scan_runner = ScanRunner(self.config, self.geometry, self.controller, self.signal_backend, self._log, self.output_root)
            self.runtime_var.set(
                "Offline demo backend ready\n"
                "motors=simulated, signal=simulated\n"
                f"output_root={self.output_root}"
            )
            self.status_var.set("Demo mode connected.")
            self.reference_var.set("Reference RBV: " + ", ".join(f"{key}={value:.2f}" for key, value in self.current_reference_steps.items()))
            self._refresh_motor_table()
            return
        try:
            self.factory = PVFactory(False)
            self.controller = MirrorController(self.config.controller, self.factory, self._log)
            self.current_reference_steps = self.controller.capture_reference()
            self.signal_backend = build_signal_backend(
                False,
                self.signal_preset_var.get(),
                self.signal_pv_var.get(),
                self.factory,
            )
            self.passive_signal_backends = {
                key: SignalBackend(label, pv, self.factory)
                for key, (label, pv) in SIGNAL_PRESETS.items()
            }
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
            self.factory = None
            self.controller = DisconnectedController(self.config.controller, str(exc), self._log)
            self.current_reference_steps = self.controller.capture_reference()
            self.signal_backend = DisconnectedSignalBackend(
                self.signal_label_var.get() or "Signal",
                self.signal_pv_var.get() or "disconnected",
                str(exc),
            )
            self.passive_signal_backends = {
                key: DisconnectedSignalBackend(label, pv, str(exc))
                for key, (label, pv) in SIGNAL_PRESETS.items()
            }
            self.scan_runner = ScanRunner(self.config, self.geometry, self.controller, self.signal_backend, self._log, self.output_root)
            self.runtime_var.set(f"Backend connection failed; UI kept in disconnected read-only state.\nReason: {exc}")
            self.status_var.set("Disconnected / read-only.")
            self.reference_var.set("Reference RBV unavailable: EPICS disconnected.")
            self._refresh_motor_table()
            self._log(f"Backend connection failed; using disconnected read-only state: {exc}")

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
        self._log("STOP all issued.")

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
        self._pull_ui_into_config()
        points = build_angle_scan_points(self.config, self.geometry, self.current_reference_steps)
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        self._show_scan_preview(preview, "Angle scan preview")

    def _preview_spiral_scan(self) -> None:
        self._pull_ui_into_config()
        points = build_spiral_scan_points(self.config, self.current_reference_steps, target_pair=self.spiral_target_var.get())
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        self._show_scan_preview(preview, "Position search preview")

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
        self._refresh_active_signal_backend()
        points = build_spiral_scan_points(self.config, self.current_reference_steps, target_pair=self.spiral_target_var.get())
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        if self.config.controller.preview_required and not self._show_scan_preview(preview, "Approve position search"):
            return
        self.pending_refine_preview = []
        self.search_status_var.set("Position search running...")
        self._start_scan_common("spiral")

    def _preview_local_refine(self) -> None:
        points = self._build_local_refine_points()
        if points is None:
            return
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        self.pending_refine_preview = points
        self._draw_spiral_map()
        self._show_scan_preview(preview, "Local refine preview")

    def _start_local_refine(self) -> None:
        self._refresh_active_signal_backend()
        points = self._build_local_refine_points()
        if points is None:
            return
        preview = self.scan_runner.build_preview(points, self.current_reference_steps)
        if self.config.controller.preview_required and not self._show_scan_preview(preview, "Approve local refine"):
            return
        self.pending_refine_preview = points
        self.measurements.clear()
        self.best_point = None
        self.best_var.set("Best point pending...")
        context = ScanContext(
            reference_steps=dict(self.current_reference_steps),
            signal_label=self.signal_label_var.get(),
            signal_pv=self.signal_pv_var.get(),
        )
        self.status_var.set("Local refine running...")
        self.search_status_var.set("Local refine running around current best point...")
        self.scan_runner.start_custom("position_refine", points, context, self._on_measurement_thread, self._on_finish_thread)

    def _refresh_active_signal_backend(self) -> None:
        self._pull_ui_into_config()
        if self.demo_mode:
            self.signal_backend = SimulatedSignalBackend(self.signal_label_var.get() or "Simulated signal")
        elif self.factory is not None:
            try:
                self.signal_backend = build_signal_backend(
                    False,
                    self.signal_preset_var.get(),
                    self.signal_pv_var.get(),
                    self.factory,
                )
            except Exception as exc:  # noqa: BLE001
                self.signal_backend = DisconnectedSignalBackend(
                    self.signal_label_var.get() or "Signal",
                    self.signal_pv_var.get() or "disconnected",
                    str(exc),
                )
        if hasattr(self.signal_backend, "label"):
            self.signal_label_var.set(getattr(self.signal_backend, "label"))
        if hasattr(self.signal_backend, "pv_name"):
            self.signal_pv_var.set(getattr(self.signal_backend, "pv_name"))
        self.scan_runner = ScanRunner(self.config, self.geometry, self.controller, self.signal_backend, self._log, self.output_root)

    def _start_scan_common(self, mode: str) -> None:
        self._refresh_active_signal_backend()
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

    def _build_local_refine_points(self) -> list[ScanPoint] | None:
        if self.best_point is None:
            messagebox.showinfo("No best point", "Run a position search first.")
            return None
        step_x = max(1.0, float(self.spiral_step_x_var.get()) / 2.0)
        step_y = max(1.0, float(self.spiral_step_y_var.get()) / 2.0)
        target_pair = self.spiral_target_var.get()
        center_targets = self.best_point.targets
        points: list[ScanPoint] = []
        index = 0
        for dy in (-step_y, 0.0, step_y):
            for dx in (-step_x, 0.0, step_x):
                targets_dict = center_targets.as_dict()
                if target_pair == "mirror1":
                    targets_dict["m1_horizontal"] += dx
                    targets_dict["m1_vertical"] += dy
                else:
                    targets_dict["m2_horizontal"] += dx
                    targets_dict["m2_vertical"] += dy
                points.append(
                    ScanPoint(
                        index=index,
                        mode=f"{target_pair}_refine",
                        angle_x_urad=math.nan,
                        angle_y_urad=math.nan,
                        offset_x_mm=math.nan,
                        offset_y_mm=math.nan,
                        targets=MotorTargets(**targets_dict),
                    )
                )
                index += 1
        return points

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
        if measurement.mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine"):
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
        if self.scan_runner.last_error:
            self.status_var.set("Scan finished with warning/error.")
        else:
            self.status_var.set("Scan finished.")
        if best_point is not None and any(mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine") for mode in {row.mode for row in self.measurements}):
            relevant = [row for row in self.measurements if row.mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine")]
            start_row = relevant[0] if relevant else None
            if start_row is not None:
                start_signal = start_row.signal_average
                deviation = best_point.signal_value - start_signal
                target_pair = "mirror1" if best_point.targets.m1_horizontal != start_row.commanded_m1_horizontal or best_point.targets.m1_vertical != start_row.commanded_m1_vertical else "mirror2"
                if target_pair == "mirror1":
                    dx = best_point.targets.m1_horizontal - start_row.commanded_m1_horizontal
                    dy = best_point.targets.m1_vertical - start_row.commanded_m1_vertical
                else:
                    dx = best_point.targets.m2_horizontal - start_row.commanded_m2_horizontal
                    dy = best_point.targets.m2_vertical - start_row.commanded_m2_vertical
                self.search_status_var.set(
                    f"Recommended optimum: {best_point.signal_label}={best_point.signal_value:.6g}; "
                    f"start={start_signal:.6g}; Δsignal={deviation:.6g}; Δsteps=({dx:.1f}, {dy:.1f}). "
                    "Use local refine for a tighter search around this peak."
                )
            else:
                self.search_status_var.set(
                    f"Recommended optimum: {best_point.signal_label}={best_point.signal_value:.6g}. "
                    "Use local refine for a tighter search around this peak."
                )
        self._save_legacy_state()
        self._save_motor_recovery()
        self._log(f"Scan finished. Saved to {session_dir}")
        if self.scan_runner.last_error:
            messagebox.showwarning(
                "Scan warning",
                "The scan stopped with a motor/controller warning.\n\n"
                f"{self.scan_runner.last_error}\n\n"
                "The GUI stayed alive and saved the partial session data. "
                "Please inspect the motor table, debug log, and saved session before continuing.",
            )

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
            passive_extras: dict[str, float] = {}
            for key, backend in getattr(self, "passive_signal_backends", {}).items():
                try:
                    if hasattr(backend, "update_target"):
                        backend.update_target(self.center_x_var.get(), self.center_y_var.get())
                    extra = backend.read()
                    passive_extras[key] = extra.value if extra.ok else math.nan
                except Exception:
                    passive_extras[key] = math.nan
            snapshots = self.controller.motor_snapshots()
            elapsed = time.time() - self.session_start
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
                for snapshot in snapshots:
                    self._motor_history[snapshot.key].append((elapsed, snapshot.rbv))
                sample = PassiveSample(
                    elapsed_s=elapsed,
                    signal_label=reading.label,
                    signal_pv=reading.pv,
                    signal_value=reading.value,
                    m1_horizontal=self._snapshot_value(snapshots, "m1_horizontal"),
                    m1_vertical=self._snapshot_value(snapshots, "m1_vertical"),
                    m2_horizontal=self._snapshot_value(snapshots, "m2_horizontal"),
                    m2_vertical=self._snapshot_value(snapshots, "m2_vertical"),
                    dmov_all=int(all(snapshot.dmov for snapshot in snapshots)),
                    movn_any=int(any(snapshot.movn for snapshot in snapshots)),
                    extra_signals=passive_extras,
                )
                if self._should_record_passive_sample(sample):
                    self._passive_samples.append(sample)
                    if self.config.controller.passive_log_enabled:
                        self.session_recorder.record_sample(sample)
                    self._last_passive_sample = sample
                self._draw_passive_map()
                self._draw_passive_trend()
            self._refresh_motor_table(snapshots)
        except Exception as exc:  # noqa: BLE001
            self.signal_live_var.set("ERR")
            self.signal_last_update_var.set(f"Error: {exc}")
            self._log(f"Signal poll failed: {exc}")
        finally:
            self._draw_geometry_preview()
            self._schedule_signal_poll()

    def _snapshot_value(self, snapshots, key: str) -> float:
        for snapshot in snapshots:
            if snapshot.key == key:
                return snapshot.rbv
        return math.nan

    def _passive_metric_value(self, sample: PassiveSample) -> float:
        metric = self.passive_metric_var.get()
        if metric == "selected_signal":
            return sample.signal_value
        return sample.extra_signals.get(metric, math.nan)

    def _recent_passive_samples(self) -> list[PassiveSample]:
        samples = list(self._passive_samples)
        limit = max(1, int(self.passive_history_limit_var.get()))
        if len(samples) > limit:
            samples = samples[-limit:]
        start_back = max(0, int(self.passive_history_start_back_var.get()))
        end_back = max(0, int(self.passive_history_end_back_var.get()))
        if start_back < end_back:
            start_back, end_back = end_back, start_back
        start_idx = max(0, len(samples) - start_back)
        end_idx = len(samples) - end_back if end_back > 0 else len(samples)
        sliced = samples[start_idx:end_idx]
        return sliced if sliced else samples[-1:] if samples else []

    def _register_canvas_points(self, name: str, points: list[dict[str, object]]) -> None:
        self._canvas_points[name] = points

    def _inspect_canvas_point(self, name: str, event) -> None:
        points = self._canvas_points.get(name, [])
        if not points:
            return
        best = min(points, key=lambda row: (float(row["x"]) - event.x) ** 2 + (float(row["y"]) - event.y) ** 2)
        payload = best.get("payload", {})
        if not isinstance(payload, dict):
            return
        lines = []
        for key, value in payload.items():
            if isinstance(value, float):
                lines.append(f"{key}: {value:.6g}")
            else:
                lines.append(f"{key}: {value}")
        messagebox.showinfo("Point details", "\n".join(lines))

    def _passive_payload(self, sample: PassiveSample, metric_name: str, metric_value: float) -> dict[str, object]:
        payload: dict[str, object] = {
            "timestamp": sample.timestamp_iso,
            "elapsed_s": sample.elapsed_s,
            "metric": metric_name,
            "metric_value": metric_value,
            "selected_signal_label": sample.signal_label,
            "selected_signal_value": sample.signal_value,
            "m1_horizontal": sample.m1_horizontal,
            "m1_vertical": sample.m1_vertical,
            "m2_horizontal": sample.m2_horizontal,
            "m2_vertical": sample.m2_vertical,
            "dmov_all": sample.dmov_all,
            "movn_any": sample.movn_any,
        }
        for key, value in sample.extra_signals.items():
            payload[f"signal_{key}"] = value
        return payload

    def _measurement_payload(self, row: MeasurementRecord) -> dict[str, object]:
        return {
            "timestamp": row.timestamp_iso,
            "mode": row.mode,
            "point_index": row.point_index,
            "angle_x_urad": row.angle_x_urad,
            "angle_y_urad": row.angle_y_urad,
            "offset_x_mm": row.offset_x_mm,
            "offset_y_mm": row.offset_y_mm,
            "signal_average": row.signal_average,
            "signal_std": row.signal_std,
            "m1_horizontal": row.rbv_m1_horizontal,
            "m1_vertical": row.rbv_m1_vertical,
            "m2_horizontal": row.rbv_m2_horizontal,
            "m2_vertical": row.rbv_m2_vertical,
        }

    def _should_record_passive_sample(self, sample: PassiveSample) -> bool:
        if self.config.controller.passive_log_all_samples:
            return True
        if self._last_passive_sample is None:
            return True
        signal_delta = abs(sample.signal_value - self._last_passive_sample.signal_value)
        if signal_delta >= self.config.controller.passive_capture_min_signal_delta:
            return True
        for key in MOTOR_PVS:
            if abs(getattr(sample, key) - getattr(self._last_passive_sample, key)) >= self.config.controller.passive_capture_min_motor_delta_steps:
                return True
        return False

    def _format_limit_value(self, value) -> str:
        if value is None:
            return "—"
        try:
            value = float(value)
        except Exception:
            return "—"
        if value != value:
            return "—"
        return f"{value:.3f}"

    def _seed_manual_limits_from_current(self) -> None:
        if not hasattr(self, "controller"):
            return
        margin = max(250.0, float(self.max_absolute_move_var.get()))
        for key, snapshot in {s.key: s for s in self.controller.motor_snapshots()}.items():
            self.manual_limit_vars[key]["llm"].set(snapshot.rbv - margin)
            self.manual_limit_vars[key]["hlm"].set(snapshot.rbv + margin)
        self.use_manual_motor_limits_var.set(True)
        self._log(f"Seeded manual motor limits around current RBV with ±{margin:.1f} steps.")

    def _copy_ioc_limits_to_manual(self) -> None:
        if not hasattr(self, "controller"):
            return
        copied = 0
        for snapshot in self.controller.motor_snapshots():
            if getattr(self.controller, '_usable_limit_pair', lambda *_: False)(snapshot.llm, snapshot.hlm):
                self.manual_limit_vars[snapshot.key]["llm"].set(float(snapshot.llm))
                self.manual_limit_vars[snapshot.key]["hlm"].set(float(snapshot.hlm))
                copied += 1
        if copied:
            self.use_manual_motor_limits_var.set(True)
            self._log(f"Copied IOC limits into manual override entries for {copied} motor(s).")
        else:
            self._log("IOC limits were not usable for any motor; nothing copied.")

    def _refresh_motor_table(self, snapshots=None) -> None:
        if not hasattr(self, "controller"):
            return
        snapshots = snapshots or self.controller.motor_snapshots()
        for snapshot in snapshots:
            eff_llm, eff_hlm, limit_src = self.controller.effective_limits(snapshot.key, snapshot)
            self.motor_tree.item(
                snapshot.key,
                values=(
                    MOTOR_LABELS.get(snapshot.key, snapshot.key),
                    snapshot.base,
                    f"{snapshot.rbv:.3f}",
                    f"{snapshot.val:.3f}",
                    self._format_limit_value(eff_llm),
                    self._format_limit_value(eff_hlm),
                    limit_src,
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
        margin = 34
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

    def _refresh_plots(self) -> None:
        """Redraw all plot canvases after a view/control toggle.

        Keep this method tiny and defensive because Tk widgets may not all exist
        yet if a startup/build sequence is changed later. This method is used by
        checkboxes/buttons in the UI and should never be allowed to crash the
        whole application.
        """

        try:
            if hasattr(self, "heatmap_canvas"):
                self._draw_angle_heatmap()
            if hasattr(self, "progress_canvas"):
                self._draw_progress()
            if hasattr(self, "spiral_canvas"):
                self._draw_spiral_map()
            if hasattr(self, "passive_map_canvas"):
                self._draw_passive_map()
            if hasattr(self, "passive_trend_canvas"):
                self._draw_passive_trend()
            if hasattr(self, "signal_trace_canvas"):
                self._draw_signal_trace()
            if hasattr(self, "pen_canvas"):
                self._draw_pen_test_plot()
            if hasattr(self, "optics_canvas"):
                self._draw_geometry_preview()
            self._update_scale_summary()
        except Exception as exc:  # noqa: BLE001
            self._log(f"plot refresh warning: {exc}")

    def _current_targets_from_motors(self) -> tuple[UndulatorTarget, UndulatorTarget]:
        current = self.controller.current_steps()
        horizontal = MirrorAngles(
            self.geometry.steps_to_urad(current["m1_horizontal"] - self.current_reference_steps["m1_horizontal"], "x", 1),
            self.geometry.steps_to_urad(current["m2_horizontal"] - self.current_reference_steps["m2_horizontal"], "x", 2),
        )
        vertical = MirrorAngles(
            self.geometry.steps_to_urad(current["m1_vertical"] - self.current_reference_steps["m1_vertical"], "y", 1),
            self.geometry.steps_to_urad(current["m2_vertical"] - self.current_reference_steps["m2_vertical"], "y", 2),
        )
        return self.geometry.to_undulator_target(horizontal, "x"), self.geometry.to_undulator_target(vertical, "y")

    def _draw_geometry_preview(self) -> None:
        canvas = self.geometry_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        layout = default_optics_layout()
        x_values = [component.x_mm for component in layout]
        x_min = min(x_values)
        x_span = max(max(x_values) - x_min, 1.0)
        top_y = h * 0.34
        bottom_y = h * 0.72
        hx_target, vy_target = self._current_targets_from_motors()

        def map_x(x_mm: float) -> float:
            return 24 + (x_mm - x_min) / x_span * (w - 48)

        def map_y(base_y: float, y_mm: float) -> float:
            return base_y - y_mm * 0.18

        canvas.create_text(18, 12, anchor="w", text="PoP II steering layout (ordered from source material + exact steering distances)", font=("Helvetica", 10, "bold"))
        canvas.create_text(18, 30, anchor="w", text="Upper lane: horizontal steering plane   Lower lane: vertical steering plane", fill="#475569")
        canvas.create_line(20, top_y, w - 20, top_y, fill="#cbd5e1", dash=(4, 4))
        canvas.create_line(20, bottom_y, w - 20, bottom_y, fill="#cbd5e1", dash=(4, 4))

        colors = {
            "laser": "#7c3aed",
            "optic": "#0f766e",
            "lens": "#2563eb",
            "mirror": "#dc2626",
            "diagnostic": "#059669",
            "interaction": "#ea580c",
            "label": "#111827",
        }
        for component in layout:
            px = map_x(component.x_mm)
            py_top = map_y(top_y, component.y_mm)
            py_bottom = map_y(bottom_y, component.y_mm)
            color = colors.get(component.kind, "#334155")
            if component.kind == "lens":
                canvas.create_oval(px - 6, py_top - 14, px + 6, py_top + 14, outline=color, width=2)
                canvas.create_oval(px - 6, py_bottom - 14, px + 6, py_bottom + 14, outline=color, width=2)
            elif component.kind == "mirror":
                canvas.create_rectangle(px - 5, py_top - 18, px + 5, py_top + 18, fill=color, outline="")
                canvas.create_rectangle(px - 5, py_bottom - 18, px + 5, py_bottom + 18, fill=color, outline="")
            elif component.kind == "interaction":
                canvas.create_oval(px - 6, py_top - 6, px + 6, py_top + 6, fill=color, outline="")
                canvas.create_oval(px - 6, py_bottom - 6, px + 6, py_bottom + 6, fill=color, outline="")
            else:
                canvas.create_rectangle(px - 4, py_top - 10, px + 4, py_top + 10, fill=color, outline="")
                canvas.create_rectangle(px - 4, py_bottom - 10, px + 4, py_bottom + 10, fill=color, outline="")
            if component.kind != "label":
                canvas.create_text(px, py_top - 24, text=component.label, font=("Helvetica", 8), angle=0)
        h_poly = self.geometry.ray_polyline(hx_target.angle_urad, hx_target.offset_mm)
        v_poly = self.geometry.ray_polyline(vy_target.angle_urad, vy_target.offset_mm)
        for poly, base_y, color in ((h_poly, top_y, "#1d4ed8"), (v_poly, bottom_y, "#16a34a")):
            prev = None
            y_abs = max(max(abs(value) for _, value in poly), 1.0)
            for x_mm, y_mm in poly:
                px = map_x(x_mm)
                py = base_y - (y_mm / y_abs) * 42
                if prev is not None:
                    canvas.create_line(prev[0], prev[1], px, py, fill=color, width=2)
                prev = (px, py)
        canvas.create_text(
            18,
            h - 38,
            anchor="w",
            text=(
                f"Live inferred target: H offset={hx_target.offset_mm:.3f} mm angle={hx_target.angle_urad:.2f} µrad | "
                f"V offset={vy_target.offset_mm:.3f} mm angle={vy_target.angle_urad:.2f} µrad"
            ),
        )
        canvas.create_text(18, h - 20, anchor="w", text="Critical distances are exact; upstream optics positions are schematic but ordered from the PoP II layout.")

    def _draw_angle_heatmap(self) -> None:
        canvas = self.heatmap_canvas
        canvas.delete("all")
        points_meta: list[dict[str, object]] = []
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
        unique_x = sorted({row.angle_x_urad for row in relevant if row.angle_x_urad == row.angle_x_urad})
        unique_y = sorted({row.angle_y_urad for row in relevant if row.angle_y_urad == row.angle_y_urad})
        modes = {row.mode for row in relevant}
        if len(unique_y) == 1 and len(unique_x) >= 1:
            self._draw_angle_line_plot(canvas, relevant, margin, w, h, lo, span, "horizontal")
            return
        if len(unique_x) == 1 and len(unique_y) >= 1:
            self._draw_angle_line_plot(canvas, relevant, margin, w, h, lo, span, "vertical")
            return
        if modes.issubset({"horizontal_only", "vertical_only"}) and "horizontal_only" in modes and "vertical_only" in modes:
            self._draw_angle_cross_map(canvas, relevant, margin, w, h, center_x, center_y, span_x, span_y, lo, span)
            return
        if self.interpolate_angle_map_var.get():
            x_values = unique_x
            y_values = unique_y
            if len(x_values) >= 2 and len(y_values) >= 2:
                x_edges = self._midpoint_edges(x_values)
                y_edges = self._midpoint_edges(y_values)
                samples_by_xy = {(row.angle_x_urad, row.angle_y_urad): row for row in relevant}
                for x_index, x_value in enumerate(x_values):
                    for y_index, y_value in enumerate(y_values):
                        row = samples_by_xy.get((x_value, y_value))
                        if row is None or row.signal_average != row.signal_average:
                            continue
                        left = margin + (x_edges[x_index] - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
                        right = margin + (x_edges[x_index + 1] - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
                        top = h - margin - (y_edges[y_index + 1] - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
                        bottom = h - margin - (y_edges[y_index] - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
                        color = self._color_for_value((row.signal_average - lo) / span)
                        canvas.create_rectangle(left, top, right, bottom, fill=color, outline="")
        for row in relevant:
            px = margin + (row.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
            py = h - margin - (row.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            radius = 5
            canvas.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="")
            points_meta.append({"x": px, "y": py, "payload": self._measurement_payload(row)})
        if self.best_point is not None:
            px = margin + (self.best_point.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
            py = h - margin - (self.best_point.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            canvas.create_line(px - 8, py, px + 8, py, fill="#111827", width=2)
            canvas.create_line(px, py - 8, px, py + 8, fill="#111827", width=2)
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} vs interaction angle", font=("Helvetica", 11, "bold"))
        canvas.create_text(w // 2, h - 18, text="Angle X [µrad]")
        canvas.create_text(18, h // 2, text="Angle Y [µrad]", angle=90)
        self._register_canvas_points("angle", points_meta)

    def _draw_angle_line_plot(
        self,
        canvas: tk.Canvas,
        rows: list[MeasurementRecord],
        margin: int,
        width: int,
        height: int,
        lo: float,
        span: float,
        axis: str,
    ) -> None:
        points_meta: list[dict[str, object]] = []
        sorted_rows = sorted(rows, key=lambda row: row.angle_x_urad if axis == "horizontal" else row.angle_y_urad)
        x_values = [row.angle_x_urad if axis == "horizontal" else row.angle_y_urad for row in sorted_rows]
        x_lo = min(x_values)
        x_hi = max(x_values)
        x_span = max(x_hi - x_lo, 1e-9)
        prev = None
        for row, x_value in zip(sorted_rows, x_values):
            px = margin + (x_value - x_lo) / x_span * (width - 2 * margin)
            py = height - margin - (row.signal_average - lo) / span * (height - 2 * margin)
            if prev is not None:
                canvas.create_line(prev[0], prev[1], px, py, fill="#1d4ed8", width=2)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill=color, outline="")
            prev = (px, py)
            points_meta.append({"x": px, "y": py, "payload": self._measurement_payload(row)})
        if self.best_point is not None:
            best_x = self.best_point.angle_x_urad if axis == "horizontal" else self.best_point.angle_y_urad
            px = margin + (best_x - x_lo) / x_span * (width - 2 * margin)
            best_y = self.best_point.signal_value
            py = height - margin - (best_y - lo) / span * (height - 2 * margin)
            canvas.create_line(px - 8, py, px + 8, py, fill="#111827", width=2)
            canvas.create_line(px, py - 8, px, py + 8, fill="#111827", width=2)
        axis_label = "Angle X [µrad]" if axis == "horizontal" else "Angle Y [µrad]"
        fixed_label = "Angle Y fixed" if axis == "horizontal" else "Angle X fixed"
        canvas.create_text(width // 2, 18, text=f"{self.signal_label_var.get()} vs {axis_label}", font=("Helvetica", 11, "bold"))
        canvas.create_text(width // 2, height - 18, text=axis_label)
        canvas.create_text(18, height // 2, text=self.signal_label_var.get(), angle=90)
        canvas.create_text(width - 18, 20, anchor="e", text=fixed_label, fill="#475569")
        self._register_canvas_points("angle", points_meta)

    def _draw_angle_cross_map(
        self,
        canvas: tk.Canvas,
        rows: list[MeasurementRecord],
        margin: int,
        width: int,
        height: int,
        center_x: float,
        center_y: float,
        span_x: float,
        span_y: float,
        lo: float,
        span: float,
    ) -> None:
        points_meta: list[dict[str, object]] = []
        horizontal_rows = [row for row in rows if row.mode == "horizontal_only"]
        vertical_rows = [row for row in rows if row.mode == "vertical_only"]
        if self.interpolate_angle_map_var.get():
            x_values = sorted({row.angle_x_urad for row in horizontal_rows if row.angle_x_urad == row.angle_x_urad})
            y_values = sorted({row.angle_y_urad for row in vertical_rows if row.angle_y_urad == row.angle_y_urad})
            if len(x_values) >= 2:
                x_edges = self._midpoint_edges(x_values)
                band_half_height = max((h - 2 * margin) * 0.03, 8)
                for index, x_value in enumerate(x_values):
                    row = next((candidate for candidate in horizontal_rows if candidate.angle_x_urad == x_value), None)
                    if row is None or row.signal_average != row.signal_average:
                        continue
                    left = margin + (x_edges[index] - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin)
                    right = margin + (x_edges[index + 1] - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin)
                    mid_y = height - margin - (center_y - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
                    color = self._color_for_value((row.signal_average - lo) / span)
                    canvas.create_rectangle(left, mid_y - band_half_height, right, mid_y + band_half_height, fill=color, outline="")
            if len(y_values) >= 2:
                y_edges = self._midpoint_edges(y_values)
                band_half_width = max((width - 2 * margin) * 0.03, 8)
                for index, y_value in enumerate(y_values):
                    row = next((candidate for candidate in vertical_rows if candidate.angle_y_urad == y_value), None)
                    if row is None or row.signal_average != row.signal_average:
                        continue
                    bottom = height - margin - (y_edges[index] - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
                    top = height - margin - (y_edges[index + 1] - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
                    mid_x = margin + (center_x - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin)
                    color = self._color_for_value((row.signal_average - lo) / span)
                    canvas.create_rectangle(mid_x - band_half_width, top, mid_x + band_half_width, bottom, fill=color, outline="")
        for row in horizontal_rows + vertical_rows:
            px = margin + (row.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin)
            py = height - margin - (row.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill=color, outline="")
            points_meta.append({"x": px, "y": py, "payload": self._measurement_payload(row)})
        canvas.create_line(
            margin,
            height - margin - (center_y - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin),
            width - margin,
            height - margin - (center_y - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin),
            fill="#94a3b8",
            dash=(4, 4),
        )
        canvas.create_line(
            margin + (center_x - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin),
            margin,
            margin + (center_x - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin),
            height - margin,
            fill="#94a3b8",
            dash=(4, 4),
        )
        if self.best_point is not None:
            px = margin + (self.best_point.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (width - 2 * margin)
            py = height - margin - (self.best_point.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            canvas.create_line(px - 8, py, px + 8, py, fill="#111827", width=2)
            canvas.create_line(px, py - 8, px, py + 8, fill="#111827", width=2)
        canvas.create_text(width // 2, 18, text=f"{self.signal_label_var.get()} quasi-2D cross map", font=("Helvetica", 11, "bold"))
        canvas.create_text(width // 2, height - 18, text="Angle X [µrad]")
        canvas.create_text(18, height // 2, text="Angle Y [µrad]", angle=90)
        canvas.create_text(
            width - 18,
            20,
            anchor="e",
            text="Combined horizontal-only + vertical-only scans",
            fill="#475569",
        )
        self._register_canvas_points("angle", points_meta)

    @staticmethod
    def _midpoint_edges(values: list[float]) -> list[float]:
        if len(values) == 1:
            value = values[0]
            return [value - 0.5, value + 0.5]
        edges = [values[0] - (values[1] - values[0]) / 2.0]
        for left, right in zip(values, values[1:]):
            edges.append((left + right) / 2.0)
        edges.append(values[-1] + (values[-1] - values[-2]) / 2.0)
        return edges

    def _draw_progress(self) -> None:
        canvas = self.progress_canvas
        canvas.delete("all")
        points_meta: list[dict[str, object]] = []
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
            points_meta.append(
                {
                    "x": px,
                    "y": py,
                    "payload": {
                        "mode": row.mode,
                        "point_index": row.point_index,
                        "signal_average": row.signal_average,
                        "signal_std": row.signal_std,
                        "m1_horizontal": row.rbv_m1_horizontal,
                        "m1_vertical": row.rbv_m1_vertical,
                        "m2_horizontal": row.rbv_m2_horizontal,
                        "m2_vertical": row.rbv_m2_vertical,
                    },
                }
            )
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} during scan", font=("Helvetica", 11, "bold"))
        self._register_canvas_points("progress", points_meta)

    def _draw_spiral_map(self) -> None:
        canvas = self.spiral_canvas
        canvas.delete("all")
        points_meta: list[dict[str, object]] = []
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 48
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        relevant = [
            row
            for row in self.measurements
            if row.mode in ("mirror1_spiral", "mirror2_spiral", "mirror1_refine", "mirror2_refine")
        ]
        if not relevant:
            canvas.create_text(w // 2, h // 2, text="No position-search data yet", fill="#666666")
            return
        pair = "mirror1" if any(row.mode.startswith("mirror1") for row in relevant) else "mirror2"
        x_attr = "commanded_m1_horizontal" if pair == "mirror1" else "commanded_m2_horizontal"
        y_attr = "commanded_m1_vertical" if pair == "mirror1" else "commanded_m2_vertical"
        xs = [getattr(row, x_attr) for row in relevant]
        ys = [getattr(row, y_attr) for row in relevant]
        vx = max(max(xs) - min(xs), 1e-6)
        vy = max(max(ys) - min(ys), 1e-6)
        values = [row.signal_average for row in relevant if row.signal_average == row.signal_average]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        span = max(hi - lo, 1e-9)
        for row in relevant:
            px = margin + (getattr(row, x_attr) - min(xs)) / vx * (w - 2 * margin)
            py = h - margin - (getattr(row, y_attr) - min(ys)) / vy * (h - 2 * margin)
            color = self._color_for_value((row.signal_average - lo) / span if row.signal_average == row.signal_average else 0.0)
            canvas.create_oval(px - 4, py - 4, px + 4, py + 4, fill=color, outline="")
            points_meta.append(
                {
                    "x": px,
                    "y": py,
                    "payload": {
                        "mode": row.mode,
                        "signal_average": row.signal_average,
                        "signal_std": row.signal_std,
                        "m1_horizontal": row.rbv_m1_horizontal,
                        "m1_vertical": row.rbv_m1_vertical,
                        "m2_horizontal": row.rbv_m2_horizontal,
                        "m2_vertical": row.rbv_m2_vertical,
                    },
                }
            )
        if self.best_point is not None:
            best_x = self.best_point.targets.m1_horizontal if pair == "mirror1" else self.best_point.targets.m2_horizontal
            best_y = self.best_point.targets.m1_vertical if pair == "mirror1" else self.best_point.targets.m2_vertical
            px = margin + (best_x - min(xs)) / vx * (w - 2 * margin)
            py = h - margin - (best_y - min(ys)) / vy * (h - 2 * margin)
            canvas.create_line(px - 8, py, px + 8, py, fill="#111827", width=2)
            canvas.create_line(px, py - 8, px, py + 8, fill="#111827", width=2)
        for point in self.pending_refine_preview:
            preview_x = point.targets.m1_horizontal if pair == "mirror1" else point.targets.m2_horizontal
            preview_y = point.targets.m1_vertical if pair == "mirror1" else point.targets.m2_vertical
            px = margin + (preview_x - min(xs)) / vx * (w - 2 * margin)
            py = h - margin - (preview_y - min(ys)) / vy * (h - 2 * margin)
            canvas.create_oval(px - 6, py - 6, px + 6, py + 6, outline="#2563eb", width=2)
        label = "mirror 1" if pair == "mirror1" else "mirror 2"
        canvas.create_text(w // 2, 18, text=f"{self.signal_label_var.get()} vs {label} position", font=("Helvetica", 11, "bold"))
        canvas.create_text(w // 2, h - 18, text=f"{label} horizontal [steps]")
        canvas.create_text(18, h // 2, text=f"{label} vertical [steps]", angle=90)
        self._register_canvas_points("spiral", points_meta)

    def _draw_passive_map(self) -> None:
        canvas = self.passive_map_canvas
        canvas.delete("all")
        points_meta: list[dict[str, object]] = []
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 48
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        samples = self._recent_passive_samples()
        if len(samples) < 2:
            canvas.create_text(w // 2, h // 2, text="Waiting for passive motor/signal history...", fill="#666666")
            return
        metric_name = self.passive_metric_var.get()
        values = [self._passive_metric_value(sample) for sample in samples]
        finite_values = [value for value in values if value == value]
        lo = min(finite_values) if finite_values else 0.0
        hi = max(finite_values) if finite_values else 1.0
        v_span = max(hi - lo, 1e-9)
        if self.passive_view_mode_var.get() == "time_vs_metric":
            times = [sample.elapsed_s for sample in samples]
            t_span = max(max(times) - min(times), 1e-6)
            prev = None
            for sample, metric in zip(samples, values):
                if metric != metric:
                    continue
                px = margin + (sample.elapsed_s - min(times)) / t_span * (w - 2 * margin)
                py = h - margin - (metric - lo) / v_span * (h - 2 * margin)
                if prev is not None:
                    canvas.create_line(prev[0], prev[1], px, py, fill="#1d4ed8", width=2)
                color = self._color_for_value((metric - lo) / v_span)
                canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=color, outline="")
                prev = (px, py)
                points_meta.append({"x": px, "y": py, "payload": self._passive_payload(sample, metric_name, metric)})
            canvas.create_text(w // 2, 18, text=f"Passive {metric_name} vs time", font=("Helvetica", 11, "bold"))
            canvas.create_text(w // 2, h - 18, text="Elapsed time [s]")
            canvas.create_text(18, h // 2, text=metric_name, angle=90)
            self.passive_status_var.set(f"Passive history window: {len(samples)} recent samples shown as time trace.")
            self._register_canvas_points("passive_map", points_meta)
            return
        x_key = self.passive_x_motor_var.get()
        y_key = self.passive_y_motor_var.get()
        xs = [getattr(sample, x_key) for sample in samples]
        ys = [getattr(sample, y_key) for sample in samples]
        x_span = max(max(xs) - min(xs), 1e-6)
        y_span = max(max(ys) - min(ys), 1e-6)
        best_index = max(
            range(len(samples)),
            key=lambda idx: self._passive_metric_value(samples[idx]) if self._passive_metric_value(samples[idx]) == self._passive_metric_value(samples[idx]) else -math.inf,
        )
        best = samples[best_index]
        for sample, metric in zip(samples, values):
            px = margin + (getattr(sample, x_key) - min(xs)) / x_span * (w - 2 * margin)
            py = h - margin - (getattr(sample, y_key) - min(ys)) / y_span * (h - 2 * margin)
            color = self._color_for_value((metric - lo) / v_span if metric == metric else 0.0)
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill=color, outline="")
            points_meta.append({"x": px, "y": py, "payload": self._passive_payload(sample, metric_name, metric)})
        best_x = margin + (getattr(best, x_key) - min(xs)) / x_span * (w - 2 * margin)
        best_y = h - margin - (getattr(best, y_key) - min(ys)) / y_span * (h - 2 * margin)
        canvas.create_line(best_x - 8, best_y, best_x + 8, best_y, fill="#111827", width=2)
        canvas.create_line(best_x, best_y - 8, best_x, best_y + 8, fill="#111827", width=2)
        self.passive_status_var.set(
            f"Passive reconstruction: {len(samples)} samples | best {metric_name}={self._passive_metric_value(best):.6g} "
            f"at {x_key}={getattr(best, x_key):.2f}, {y_key}={getattr(best, y_key):.2f}"
        )
        canvas.create_text(w // 2, 18, text=f"Passive {metric_name} map from observed mirror motion", font=("Helvetica", 11, "bold"))
        canvas.create_text(w // 2, h - 18, text=f"{x_key} [steps]")
        canvas.create_text(18, h // 2, text=f"{y_key} [steps]", angle=90)
        self._register_canvas_points("passive_map", points_meta)

    def _draw_passive_trend(self) -> None:
        canvas = self.passive_trend_canvas
        canvas.delete("all")
        points_meta: list[dict[str, object]] = []
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 40
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        samples = self._recent_passive_samples()
        if len(samples) < 2:
            canvas.create_text(w // 2, h // 2, text="Waiting for passive trend history...", fill="#666666")
            return
        x_key = self.passive_x_motor_var.get()
        y_key = self.passive_y_motor_var.get()
        series = [
            (self.passive_metric_var.get(), [self._passive_metric_value(sample) for sample in samples], "#1d4ed8"),
            (x_key, [getattr(sample, x_key) for sample in samples], "#dc2626"),
            (y_key, [getattr(sample, y_key) for sample in samples], "#16a34a"),
        ]
        for label, values, color in series:
            lo = min(values)
            hi = max(values)
            span = max(hi - lo, 1e-9)
            prev = None
            for idx, value in enumerate(values):
                px = margin + idx / max(len(values) - 1, 1) * (w - 2 * margin)
                py = h - margin - (value - lo) / span * (h - 2 * margin)
                if prev is not None:
                    canvas.create_line(prev[0], prev[1], px, py, fill=color, width=2)
                prev = (px, py)
                if label == self.passive_metric_var.get():
                    points_meta.append({"x": px, "y": py, "payload": self._passive_payload(samples[idx], label, value)})
            canvas.create_text(w - 140, 18 + 16 * series.index((label, values, color)), anchor="w", text=label, fill=color)
        canvas.create_text(w // 2, 18, text="Passive signal + motor traces (each trace scaled to its own range)", font=("Helvetica", 11, "bold"))
        self._register_canvas_points("passive_trend", points_meta)

    def _clear_passive_buffer(self) -> None:
        self._passive_samples.clear()
        for history in self._motor_history.values():
            history.clear()
        self._signal_trace.clear()
        self._signal_history.clear()
        self.passive_status_var.set("Passive buffer cleared.")
        self._draw_passive_map()
        self._draw_passive_trend()
        self._draw_signal_trace()

    def _preview_pen_test(self) -> None:
        sequence = self._build_pen_test_plan()
        if not sequence:
            messagebox.showinfo("Pen test", "No pen-test points generated.")
            return
        lines = [
            f"#{point.index} {point.motor_key} -> {point.target_steps:.2f} steps "
            f"(amp={point.amplitude_steps:.2f}, dwell={point.dwell_s:.2f}s, {point.note})"
            for point in sequence[:36]
        ]
        if len(sequence) > 36:
            lines.append(f"... {len(sequence) - 36} more steps omitted")
        messagebox.showinfo("Pen test preview", "\n".join(lines))

    def _build_pen_test_plan(self) -> list[PenTestPoint]:
        current = self.controller.current_steps()
        reference = current.get(self.pen_motor_var.get(), 0.0)
        return build_pen_test_sequence(
            self.pen_motor_var.get(),
            reference,
            self.pen_start_var.get(),
            self.pen_stop_var.get(),
            self.pen_increment_var.get(),
            self.pen_cycles_var.get(),
            self.pen_pause_var.get(),
        )

    def _start_pen_test(self) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan first.")
            return
        if self._pen_test_thread is not None and self._pen_test_thread.is_alive():
            messagebox.showinfo("Pen test running", "A pen test is already running.")
            return
        sequence = self._build_pen_test_plan()
        if not sequence:
            messagebox.showinfo("Pen test", "No pen-test points generated.")
            return
        preview = "\n".join(
            f"#{point.index} {point.motor_key} -> {point.target_steps:.2f} steps ({point.note})"
            for point in sequence[:24]
        )
        if not messagebox.askokcancel(
            "Approve pen test",
            preview + ("\n..." if len(sequence) > 24 else "") + "\n\nProceed with this cautious sequence?",
        ):
            return
        self.pen_test_rows.clear()
        self._pen_test_stop.clear()
        self.pen_status_var.set("Pen test running...")
        self._save_motor_recovery()
        self._pen_test_thread = threading.Thread(target=self._run_pen_test, args=(sequence,), daemon=True)
        self._pen_test_thread.start()

    def _stop_pen_test(self) -> None:
        self._pen_test_stop.set()
        self.pen_status_var.set("Pen-test stop requested.")

    def _run_pen_test(self, sequence: list[PenTestPoint]) -> None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        session_dir = self.output_root / f"laser_mirror_pen_test_{stamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "plan.json").write_text(json.dumps([point.__dict__ for point in sequence], indent=2))
        csv_path = session_dir / "pen_test.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp_iso",
                    "index",
                    "motor_key",
                    "amplitude_steps",
                    "target_steps",
                    "dwell_s",
                    "signal_value",
                    "rbv_after",
                    "dmov",
                    "movn",
                    "stat",
                    "sevr",
                    "note",
                ],
            )
            writer.writeheader()
            for point in sequence:
                if self._pen_test_stop.is_set():
                    break
                current = self.controller.current_steps()
                targets = dict(current)
                targets[point.motor_key] = point.target_steps
                try:
                    self.controller.move_absolute_group(
                        targets,
                        request_stop=self._pen_test_stop.is_set,
                        command_logger=self._append_command_record,
                        command_path=self.last_command_path,
                    )
                    time.sleep(point.dwell_s)
                    reading = self.signal_backend.read()
                    snapshot = next(snapshot for snapshot in self.controller.motor_snapshots() if snapshot.key == point.motor_key)
                    row = {
                        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "index": point.index,
                        "motor_key": point.motor_key,
                        "amplitude_steps": point.amplitude_steps,
                        "target_steps": point.target_steps,
                        "dwell_s": point.dwell_s,
                        "signal_value": reading.value if reading.ok else math.nan,
                        "rbv_after": snapshot.rbv,
                        "dmov": snapshot.dmov,
                        "movn": snapshot.movn,
                        "stat": snapshot.stat,
                        "sevr": snapshot.sevr,
                        "note": point.note,
                    }
                    writer.writerow(row)
                    handle.flush()
                    self.pen_test_rows.append(row)
                    self.root.after(0, self._draw_pen_test_plot)
                    self.root.after(0, lambda msg=f"Pen test point {point.index + 1}/{len(sequence)} complete": self.pen_status_var.set(msg))
                except Exception as exc:  # noqa: BLE001
                    self.root.after(0, lambda exc=exc: self.pen_status_var.set(f"Pen test failed: {exc}"))
                    self._log(f"Pen test failed: {exc}")
                    break
        self.root.after(0, lambda: self.pen_status_var.set(f"Pen test finished. Saved to {session_dir}"))
        self._log(f"Pen test finished. Saved to {session_dir}")

    def _draw_pen_test_plot(self) -> None:
        canvas = self.pen_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 40
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if not self.pen_test_rows:
            canvas.create_text(w // 2, h // 2, text="No pen-test data yet", fill="#666666")
            return
        values = [float(row["signal_value"]) for row in self.pen_test_rows if row["signal_value"] == row["signal_value"]]
        lo = min(values) if values else 0.0
        hi = max(values) if values else 1.0
        span = max(hi - lo, 1e-9)
        prev = None
        for idx, row in enumerate(self.pen_test_rows):
            px = margin + idx / max(len(self.pen_test_rows) - 1, 1) * (w - 2 * margin)
            py = h - margin - (float(row["signal_value"]) - lo) / span * (h - 2 * margin)
            if prev is not None:
                canvas.create_line(prev[0], prev[1], px, py, fill="#7c3aed", width=2)
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#ea580c", outline="")
            prev = (px, py)
        canvas.create_text(w // 2, 18, text="Pen-test signal response", font=("Helvetica", 11, "bold"))

    def _save_canvas_postscript(self, canvas: tk.Canvas, default_name: str) -> None:
        path = filedialog.asksaveasfilename(
            title="Save plot",
            initialdir=str(self.output_root),
            initialfile=default_name,
            defaultextension=".ps",
            filetypes=[("PostScript", "*.ps"), ("All files", "*.*")],
        )
        if not path:
            return
        canvas.postscript(file=path, colormode="color")
        self._log(f"Saved plot to {path}")

    def _color_for_value(self, value: float) -> str:
        value = max(0.0, min(1.0, float(value)))
        r = int(255 * value)
        g = int(180 * (1.0 - value) + 40 * value)
        b = int(255 * (1.0 - value))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        if hasattr(self, "debug_text"):
            self.debug_text.insert("end", f"[{timestamp}] {message}\n")
            self.debug_text.see("end")
        if hasattr(self, "session_recorder"):
            self.session_recorder.log(message)

    def on_close(self) -> None:
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if hasattr(self, "scan_runner") and self.scan_runner.is_running():
            if not messagebox.askyesno("Scan still running", "A scan is still running. Stop it and close the application?"):
                return
            self.scan_runner.request_stop()
            self.scan_runner.join(timeout=5.0)
        if self._pen_test_thread is not None and self._pen_test_thread.is_alive():
            self._pen_test_stop.set()
            self._pen_test_thread.join(timeout=5.0)
        try:
            self._save_motor_recovery()
            self._save_legacy_state()
            self._save_config()
            self.session_recorder.write_summary(
                {
                    "closed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "output_root": str(self.output_root),
                    "passive_samples_recorded": len(self._passive_samples),
                    "scan_measurements": len(self.measurements),
                    "pen_test_rows": len(self.pen_test_rows),
                    "safe_mode": self.safe_mode_var.get(),
                    "write_mode": self.write_mode_var.get(),
                }
            )
            self.session_recorder.close()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    app = LaserMirrorApp(
        root,
        Path(args.config),
        force_safe_mode=args.safe_mode,
        force_write_mode=args.write_mode,
        force_demo_mode=args.demo_mode,
    )
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0
