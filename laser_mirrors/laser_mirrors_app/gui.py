from __future__ import annotations

import argparse
from collections import deque
import math
import statistics
import tempfile
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .config import AppConfig
from .geometry import LaserMirrorGeometry
from .hardware import SimulatedP1Backend, build_backends
from .models import MeasurementRecord, MirrorAngles, UndulatorTarget
from .scan import ScanContext, ScanRunner
from .state import load_state, save_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSMB laser mirror scan tool")
    parser.add_argument("--safe-mode", action="store_true", help="Run with simulated motors and simulated P1")
    parser.add_argument("--config", default="laser_mirrors_config.json", help="Path to JSON config file")
    return parser


class LaserMirrorApp:
    def __init__(self, root: tk.Tk, config_path: Path, force_safe_mode: bool = False):
        self.root = root
        self.root.title("SSMB Laser Mirror Angle Scan Tool")
        self.config_path = config_path
        self.config = AppConfig.load(config_path)
        if force_safe_mode:
            self.config.controller.safe_mode = True
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        self.output_root = Path(tempfile.gettempdir()) / "laser_mirror_runs"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.measurements: list[MeasurementRecord] = []
        self._build_state()
        self._build_ui()
        self._connect_backends()
        self._restore_legacy_state()
        self._refresh_geometry_readback()
        self._draw_geometry_preview()
        self._schedule_p1_poll()

    def _build_state(self) -> None:
        self.state_file_path = (self.config_path.parent / self.config.controller.state_file_path).resolve()
        self.recovery_state_path = self.state_file_path.with_name("mirror_state.recovery.ini")
        self.safe_mode_var = tk.BooleanVar(value=self.config.controller.safe_mode)
        self.backend_var = tk.StringVar(value=self.config.controller.backend)
        self.p1_backend_var = tk.StringVar(value=self.config.controller.p1_backend)
        self.p1_pv_var = tk.StringVar(value=self.config.controller.p1_pv)
        self.p1_poll_interval_var = tk.IntVar(value=self.config.controller.p1_poll_interval_ms)
        self.p1_average_window_var = tk.IntVar(value=self.config.controller.p1_average_samples)
        self.offset_x_var = tk.DoubleVar(value=self.config.controller.startup_offset_x_mm)
        self.offset_y_var = tk.DoubleVar(value=self.config.controller.startup_offset_y_mm)
        self.angle_x_var = tk.DoubleVar(value=self.config.controller.startup_angle_x_urad)
        self.angle_y_var = tk.DoubleVar(value=self.config.controller.startup_angle_y_urad)
        self.span_x_var = tk.DoubleVar(value=self.config.scan.span_angle_x_urad)
        self.span_y_var = tk.DoubleVar(value=self.config.scan.span_angle_y_urad)
        self.center_x_var = tk.DoubleVar(value=self.config.scan.center_angle_x_urad)
        self.center_y_var = tk.DoubleVar(value=self.config.scan.center_angle_y_urad)
        self.points_x_var = tk.IntVar(value=self.config.scan.points_x)
        self.points_y_var = tk.IntVar(value=self.config.scan.points_y)
        self.dwell_var = tk.DoubleVar(value=self.config.scan.dwell_s)
        self.samples_var = tk.IntVar(value=self.config.scan.p1_samples_per_point)
        self.objective_var = tk.StringVar(value=self.config.scan.objective)
        self.solve_mode_var = tk.StringVar(value=self.config.scan.solve_mode)
        self.status_var = tk.StringVar(value="Idle")
        self.last_export_var = tk.StringVar(value="No scan saved yet.")
        self.best_point_var = tk.StringVar(value="No best point yet.")
        self.runtime_var = tk.StringVar(value="Backends not connected yet.")
        self.state_path_var = tk.StringVar(value=str(self.state_file_path))
        self.mirror1_x_var = tk.StringVar(value="—")
        self.mirror2_x_var = tk.StringVar(value="—")
        self.mirror1_y_var = tk.StringVar(value="—")
        self.mirror2_y_var = tk.StringVar(value="—")
        self.p1_live_var = tk.StringVar(value="—")
        self.p1_avg_var = tk.StringVar(value="—")
        self.p1_std_var = tk.StringVar(value="—")
        self.p1_samples_used_var = tk.StringVar(value="0")
        self.p1_last_update_var = tk.StringVar(value="Never")
        self.manual_axis_var = tk.StringVar(value="x")
        self.manual_mirror_var = tk.IntVar(value=1)
        self.manual_steps_var = tk.IntVar(value=10)
        self.current_angles_x = MirrorAngles(0.0, 0.0)
        self.current_angles_y = MirrorAngles(0.0, 0.0)
        self._p1_history: deque[float] = deque(maxlen=max(1, self.p1_average_window_var.get()))
        self._p1_trace: deque[tuple[float, float]] = deque(maxlen=300)
        self._p1_poll_after_id: str | None = None

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        self.overview_frame = ttk.Frame(notebook, padding=10)
        self.manual_frame = ttk.Frame(notebook, padding=10)
        self.scan_frame = ttk.Frame(notebook, padding=10)
        self.debug_frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.overview_frame, text="Overview")
        notebook.add(self.manual_frame, text="Manual control")
        notebook.add(self.scan_frame, text="Scan")
        notebook.add(self.debug_frame, text="Debug / Logs")

        self._build_overview()
        self._build_manual_tab()
        self._build_scan_tab()
        self._build_debug_tab()

    def _build_overview(self) -> None:
        left = ttk.Frame(self.overview_frame)
        right = ttk.Frame(self.overview_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.overview_frame.columnconfigure(0, weight=2)
        self.overview_frame.columnconfigure(1, weight=1)
        self.overview_frame.rowconfigure(0, weight=1)

        cfg_box = ttk.LabelFrame(left, text="Machine / controller settings", padding=10)
        cfg_box.pack(fill="x")
        ttk.Checkbutton(cfg_box, text="Safe mode (no real motor moves)", variable=self.safe_mode_var, command=self._safe_mode_changed).grid(row=0, column=0, columnspan=2, sticky="w")
        self._add_labeled_entry(cfg_box, "P1 backend", self.p1_backend_var, 1, readonly=False)
        self._add_labeled_entry(cfg_box, "P1 PV", self.p1_pv_var, 2, width=40)
        self._add_labeled_entry(cfg_box, "P1 poll [ms]", self.p1_poll_interval_var, 3)
        self._add_labeled_entry(cfg_box, "P1 avg samples", self.p1_average_window_var, 4)
        ttk.Button(cfg_box, text="Reconnect backends", command=self._connect_backends).grid(row=5, column=0, pady=(8, 0), sticky="w")
        ttk.Button(cfg_box, text="Save config", command=self._save_config).grid(row=5, column=1, pady=(8, 0), sticky="e")

        target_box = ttk.LabelFrame(left, text="Current undulator target", padding=10)
        target_box.pack(fill="x", pady=(12, 0))
        self._add_labeled_entry(target_box, "Offset X [mm]", self.offset_x_var, 0)
        self._add_labeled_entry(target_box, "Offset Y [mm]", self.offset_y_var, 1)
        self._add_labeled_entry(target_box, "Angle X [µrad]", self.angle_x_var, 2)
        self._add_labeled_entry(target_box, "Angle Y [µrad]", self.angle_y_var, 3)
        ttk.Button(target_box, text="Apply as current reference", command=self._apply_current_reference).grid(row=4, column=0, pady=(8, 0), sticky="w")
        ttk.Button(target_box, text="Save mirror state now", command=self._save_legacy_state).grid(row=4, column=1, pady=(8, 0), sticky="e")

        readback_box = ttk.LabelFrame(left, text="Mirror angles implied by current target", padding=10)
        readback_box.pack(fill="x", pady=(12, 0))
        labels = [
            ("Mirror 1 X [µrad]", self.mirror1_x_var),
            ("Mirror 2 X [µrad]", self.mirror2_x_var),
            ("Mirror 1 Y [µrad]", self.mirror1_y_var),
            ("Mirror 2 Y [µrad]", self.mirror2_y_var),
        ]
        for row, (label, var) in enumerate(labels):
            ttk.Label(readback_box, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(readback_box, textvariable=var).grid(row=row, column=1, sticky="e", pady=2)

        runtime_box = ttk.LabelFrame(right, text="Runtime / state", padding=10)
        runtime_box.pack(fill="x")
        ttk.Label(runtime_box, textvariable=self.runtime_var, wraplength=340, justify="left").pack(anchor="w")
        ttk.Label(runtime_box, text=f"State file: {self.state_file_path}", wraplength=340, justify="left").pack(anchor="w", pady=(6, 0))

        p1_box = ttk.LabelFrame(right, text="Live P1 readback", padding=10)
        p1_box.pack(fill="x", pady=(12, 0))
        p1_rows = [
            ("Instantaneous", self.p1_live_var),
            ("Rolling average", self.p1_avg_var),
            ("Rolling std", self.p1_std_var),
            ("Samples in window", self.p1_samples_used_var),
            ("Last update", self.p1_last_update_var),
        ]
        for row, (label, var) in enumerate(p1_rows):
            ttk.Label(p1_box, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(p1_box, textvariable=var).grid(row=row, column=1, sticky="e", pady=2)
        self.p1_trace_canvas = tk.Canvas(p1_box, width=340, height=140, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.p1_trace_canvas.grid(row=len(p1_rows), column=0, columnspan=2, sticky="ew", pady=(10, 0))

        info = ttk.LabelFrame(right, text="Geometry / concept", padding=10)
        info.pack(fill="x", pady=(12, 0))
        ttk.Label(
            info,
            text=(
                "Mirror 1 and mirror 2 jointly set the laser offset and interaction angle at the undulator.\n"
                "This tool keeps the target point fixed while scanning the angle around that point.\n"
                "Use the new solve mode controls in the Scan tab to either drive both mirrors from the undulator target,\n"
                "or drive one mirror directly while solving the other analytically to hold the point."
            ),
            wraplength=340,
            justify="left",
        ).pack(anchor="w")
        self.geometry_canvas = tk.Canvas(right, width=380, height=280, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.geometry_canvas.pack(fill="both", expand=True, pady=(12, 0))

    def _build_manual_tab(self) -> None:
        left = ttk.Frame(self.manual_frame)
        right = ttk.Frame(self.manual_frame)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.manual_frame.columnconfigure(0, weight=0)
        self.manual_frame.columnconfigure(1, weight=1)
        self.manual_frame.rowconfigure(0, weight=1)

        target_box = ttk.LabelFrame(left, text="Manual moves", padding=10)
        target_box.pack(fill="x")
        ttk.Button(target_box, text="Move to current target now", command=self._move_to_current_target).grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(target_box, text="Return to saved state", command=self._return_to_saved_state).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(target_box, text="Return to recovery state", command=self._return_to_recovery_state).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        nudge_box = ttk.LabelFrame(left, text="Direct mirror nudge", padding=10)
        nudge_box.pack(fill="x", pady=(12, 0))
        ttk.Label(nudge_box, text="Axis").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Combobox(nudge_box, textvariable=self.manual_axis_var, values=["x", "y"], state="readonly", width=8).grid(row=0, column=1, sticky="e", pady=2)
        ttk.Label(nudge_box, text="Mirror").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(nudge_box, textvariable=self.manual_mirror_var, values=[1, 2], state="readonly", width=8).grid(row=1, column=1, sticky="e", pady=2)
        self._add_labeled_entry(nudge_box, "Steps", self.manual_steps_var, 2, width=10)
        ttk.Button(nudge_box, text="Nudge -", command=lambda: self._manual_relative_move(-1)).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(nudge_box, text="Nudge +", command=lambda: self._manual_relative_move(1)).grid(row=3, column=1, sticky="ew", pady=(8, 0))

        notes = ttk.LabelFrame(right, text="Manual control notes", padding=10)
        notes.pack(fill="x")
        ttk.Label(
            notes,
            text=(
                "Use this tab for direct control-room work outside the scan workflow.\n"
                "Move to current target uses the undulator-space offset/angle fields from Overview.\n"
                "Direct nudge sends one relative motor step command to the chosen mirror axis.\n"
                "A recovery snapshot is saved before every real move so you can return to the pre-move state."
            ),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")

    def _build_scan_tab(self) -> None:
        controls = ttk.LabelFrame(self.scan_frame, text="Scan definition", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plots = ttk.LabelFrame(self.scan_frame, text="Live scan view", padding=10)
        plots.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.scan_frame.columnconfigure(0, weight=0)
        self.scan_frame.columnconfigure(1, weight=1)
        self.scan_frame.rowconfigure(0, weight=1)

        self._add_labeled_entry(controls, "Center angle X [µrad]", self.center_x_var, 0)
        self._add_labeled_entry(controls, "Center angle Y [µrad]", self.center_y_var, 1)
        self._add_labeled_entry(controls, "Span X [µrad]", self.span_x_var, 2)
        self._add_labeled_entry(controls, "Span Y [µrad]", self.span_y_var, 3)
        self._add_labeled_entry(controls, "Points X", self.points_x_var, 4)
        self._add_labeled_entry(controls, "Points Y", self.points_y_var, 5)
        self._add_labeled_entry(controls, "Dwell [s]", self.dwell_var, 6)
        self._add_labeled_entry(controls, "P1 samples / point", self.samples_var, 7)
        ttk.Label(controls, text="Solve mode").grid(row=8, column=0, sticky="w", pady=2)
        ttk.Combobox(
            controls,
            textvariable=self.solve_mode_var,
            state="readonly",
            width=22,
            values=[
                "two_mirror_target",
                "mirror1_primary",
                "mirror2_primary",
            ],
        ).grid(row=8, column=1, sticky="e", pady=2)
        ttk.Label(
            controls,
            text=(
                "two_mirror_target: scan target angle at the undulator.\n"
                "mirror1_primary: interpret center/span as mirror 1 angle and solve mirror 2.\n"
                "mirror2_primary: interpret center/span as mirror 2 angle and solve mirror 1."
            ),
            wraplength=320,
            justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(controls, text="Optimize for").grid(row=10, column=0, sticky="w", pady=2)
        ttk.Combobox(controls, textvariable=self.objective_var, values=["max", "min"], state="readonly", width=15).grid(row=10, column=1, sticky="e", pady=2)
        ttk.Button(controls, text="Start scan", command=self._start_scan).grid(row=11, column=0, pady=(8, 0), sticky="w")
        ttk.Button(controls, text="Stop scan", command=self._stop_scan).grid(row=11, column=1, pady=(8, 0), sticky="e")
        ttk.Label(controls, textvariable=self.status_var, foreground="#0f766e").grid(row=12, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.best_point_var, wraplength=320).grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.last_export_var, wraplength=320).grid(row=14, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.heatmap_canvas = tk.Canvas(plots, width=680, height=360, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.heatmap_canvas.pack(fill="both", expand=True)
        self.progress_canvas = tk.Canvas(plots, width=680, height=220, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.progress_canvas.pack(fill="x", pady=(12, 0))

    def _build_debug_tab(self) -> None:
        ttk.Label(self.debug_frame, text="Planned motor commands and debug messages are shown here before / while moving.").pack(anchor="w")
        self.debug_text = tk.Text(self.debug_frame, width=120, height=36)
        self.debug_text.pack(fill="both", expand=True, pady=(8, 0))

    def _add_labeled_entry(self, parent: ttk.Widget, label: str, variable: tk.Variable, row: int, width: int = 18, readonly: bool = False) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        state = "readonly" if readonly else "normal"
        ttk.Entry(parent, textvariable=variable, width=width, state=state).grid(row=row, column=1, sticky="e", pady=2, padx=(10, 0))

    def _safe_mode_changed(self) -> None:
        self.config.controller.safe_mode = self.safe_mode_var.get()
        self._connect_backends()

    def _save_config(self) -> None:
        self._pull_ui_into_config()
        self.config.save(self.config_path)
        self._log(f"Saved config to {self.config_path}")

    def _pull_ui_into_config(self) -> None:
        self.config.controller.safe_mode = self.safe_mode_var.get()
        self.config.controller.p1_backend = self.p1_backend_var.get()
        self.config.controller.p1_pv = self.p1_pv_var.get()
        self.config.controller.p1_poll_interval_ms = max(100, int(self.p1_poll_interval_var.get()))
        self.config.controller.p1_average_samples = max(1, int(self.p1_average_window_var.get()))
        self.config.controller.startup_offset_x_mm = self.offset_x_var.get()
        self.config.controller.startup_offset_y_mm = self.offset_y_var.get()
        self.config.controller.startup_angle_x_urad = self.angle_x_var.get()
        self.config.controller.startup_angle_y_urad = self.angle_y_var.get()
        self.config.scan.center_angle_x_urad = self.center_x_var.get()
        self.config.scan.center_angle_y_urad = self.center_y_var.get()
        self.config.scan.span_angle_x_urad = self.span_x_var.get()
        self.config.scan.span_angle_y_urad = self.span_y_var.get()
        self.config.scan.points_x = self.points_x_var.get()
        self.config.scan.points_y = self.points_y_var.get()
        self.config.scan.dwell_s = self.dwell_var.get()
        self.config.scan.p1_samples_per_point = self.samples_var.get()
        self.config.scan.objective = self.objective_var.get()
        self.config.scan.solve_mode = self.solve_mode_var.get()

    def _connect_backends(self) -> None:
        self._pull_ui_into_config()
        self.geometry = LaserMirrorGeometry(self.config.geometry)
        cmdlib_path = (self.config_path.parent / self.config.controller.picomotor_config_path).resolve().parent / "MirrorControlCmdLib.py"
        try:
            self.mirror_backend, self.p1_backend = build_backends(
                safe_mode=self.config.controller.safe_mode,
                p1_backend_name=self.config.controller.p1_backend,
                p1_pv=self.config.controller.p1_pv,
                cmdlib_path=cmdlib_path,
                debug=self._log,
            )
            self.scan_runner = ScanRunner(
                config=self.config,
                geometry=self.geometry,
                mirror_backend=self.mirror_backend,
                p1_backend=self.p1_backend,
                debug=self._log,
                output_root=self.output_root,
            )
            self.status_var.set(f"Connected: mirror={self.mirror_backend.name}, p1={self.p1_backend.name}")
            self.runtime_var.set(
                f"Mirror backend: {self.mirror_backend.name}\n"
                f"P1 backend: {self.p1_backend.name}\n"
                f"Output root: {self.output_root}"
            )
            self._log(
                "Current raw step readback: "
                f"x(m1={self.mirror_backend.get_position_steps('x', 1)}, m2={self.mirror_backend.get_position_steps('x', 2)}), "
                f"y(m1={self.mirror_backend.get_position_steps('y', 1)}, m2={self.mirror_backend.get_position_steps('y', 2)})"
            )
        except Exception as exc:  # noqa: BLE001
            self.mirror_backend, self.p1_backend = build_backends(
                safe_mode=True,
                p1_backend_name="simulated",
                p1_pv="",
                cmdlib_path=cmdlib_path,
                debug=self._log,
            )
            self.scan_runner = ScanRunner(self.config, self.geometry, self.mirror_backend, self.p1_backend, self._log, self.output_root)
            self.safe_mode_var.set(True)
            self.status_var.set(f"Fell back to safe mode: {exc}")
            self.runtime_var.set(
                "Fell back to safe mode after backend connection failure.\n"
                f"Reason: {exc}\n"
                f"Output root: {self.output_root}"
            )
            self._log(f"Backend connection failed, using safe mode instead: {exc}")
        self._p1_history = deque(maxlen=max(1, self.config.controller.p1_average_samples))

    def _restore_legacy_state(self) -> None:
        snapshot = load_state(self.state_file_path)
        self.current_angles_x = self.geometry.to_mirror_angles(snapshot.last_known_x, "x")
        self.current_angles_y = self.geometry.to_mirror_angles(snapshot.last_known_y, "y")
        self.offset_x_var.set(snapshot.last_set_x.offset_mm)
        self.offset_y_var.set(snapshot.last_set_y.offset_mm)
        self.angle_x_var.set(snapshot.last_set_x.angle_urad)
        self.angle_y_var.set(snapshot.last_set_y.angle_urad)
        self._log(f"Loaded mirror state from {self.state_file_path}")

    def _save_legacy_state(self) -> None:
        requested_x, requested_y = self._requested_targets()
        save_state(
            self.state_file_path,
            self.geometry,
            self.current_angles_x,
            self.current_angles_y,
            requested_x,
            requested_y,
        )
        self._log(f"Saved mirror state to {self.state_file_path}")

    def _save_recovery_state(self) -> None:
        requested_x, requested_y = self._requested_targets()
        save_state(
            self.recovery_state_path,
            self.geometry,
            self.current_angles_x,
            self.current_angles_y,
            requested_x,
            requested_y,
        )
        self._log(f"Saved recovery snapshot to {self.recovery_state_path}")

    def _requested_targets(self) -> tuple[UndulatorTarget, UndulatorTarget]:
        return (
            UndulatorTarget(offset_mm=self.offset_x_var.get(), angle_urad=self.angle_x_var.get()),
            UndulatorTarget(offset_mm=self.offset_y_var.get(), angle_urad=self.angle_y_var.get()),
        )

    def _apply_current_reference(self) -> None:
        self._refresh_geometry_readback()
        self.current_angles_x = MirrorAngles(float(self.mirror1_x_var.get()), float(self.mirror2_x_var.get()))
        self.current_angles_y = MirrorAngles(float(self.mirror1_y_var.get()), float(self.mirror2_y_var.get()))
        self._log("Applied current undulator target as the active mirror reference.")

    def _move_to_current_target(self) -> None:
        """Move both planes to the currently requested undulator target immediately."""
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan before using manual move.")
            return
        self._save_recovery_state()
        requested_x, requested_y = self._requested_targets()
        target_angles_x = self.geometry.to_mirror_angles(requested_x, "x")
        target_angles_y = self.geometry.to_mirror_angles(requested_y, "y")
        self._move_single_axis_to_angles("x", self.current_angles_x, target_angles_x)
        self._move_single_axis_to_angles("y", self.current_angles_y, target_angles_y)
        self.current_angles_x = target_angles_x
        self.current_angles_y = target_angles_y
        self._save_legacy_state()
        self._refresh_geometry_readback()
        self.status_var.set("Moved mirrors to the requested target.")

    def _manual_relative_move(self, direction: int) -> None:
        """Send a direct relative step command for debugging and operator nudging."""
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan before nudging mirrors manually.")
            return
        self._save_recovery_state()
        axis = self.manual_axis_var.get()
        mirror_index = int(self.manual_mirror_var.get())
        steps = int(self.manual_steps_var.get()) * int(direction)
        self._log(f"Manual nudge: axis={axis} mirror={mirror_index} steps={steps}")
        self.mirror_backend.relative_move(axis, mirror_index, steps)
        angle_delta = self.geometry.steps_to_angle_delta(steps, axis, mirror_index)
        current = self.current_angles_x if axis == "x" else self.current_angles_y
        updated = MirrorAngles(
            mirror1_urad=current.mirror1_urad + (angle_delta if mirror_index == 1 else 0.0),
            mirror2_urad=current.mirror2_urad + (angle_delta if mirror_index == 2 else 0.0),
        )
        if axis == "x":
            self.current_angles_x = updated
        else:
            self.current_angles_y = updated
        self._save_legacy_state()
        self._refresh_geometry_readback()

    def _return_to_saved_state(self) -> None:
        snapshot = load_state(self.state_file_path)
        self._restore_snapshot(snapshot, description="saved state")

    def _return_to_recovery_state(self) -> None:
        snapshot = load_state(self.recovery_state_path)
        self._restore_snapshot(snapshot, description="recovery state")

    def _restore_snapshot(self, snapshot, description: str) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan running", "Stop the running scan before restoring a mirror state.")
            return
        target_angles_x = self.geometry.to_mirror_angles(snapshot.last_known_x, "x")
        target_angles_y = self.geometry.to_mirror_angles(snapshot.last_known_y, "y")
        self._move_single_axis_to_angles("x", self.current_angles_x, target_angles_x)
        self._move_single_axis_to_angles("y", self.current_angles_y, target_angles_y)
        self.current_angles_x = target_angles_x
        self.current_angles_y = target_angles_y
        self.offset_x_var.set(snapshot.last_set_x.offset_mm)
        self.offset_y_var.set(snapshot.last_set_y.offset_mm)
        self.angle_x_var.set(snapshot.last_set_x.angle_urad)
        self.angle_y_var.set(snapshot.last_set_y.angle_urad)
        self._refresh_geometry_readback()
        self._save_legacy_state()
        self.status_var.set(f"Returned mirrors to {description}.")

    def _move_single_axis_to_angles(self, axis: str, current: MirrorAngles, target: MirrorAngles) -> None:
        """Apply the minimum relative step sequence needed to reach a target state in one plane."""
        delta_m1 = target.mirror1_urad - current.mirror1_urad
        delta_m2 = target.mirror2_urad - current.mirror2_urad
        steps_m1 = self.geometry.angle_delta_to_steps(delta_m1, axis, mirror_index=1)
        steps_m2 = self.geometry.angle_delta_to_steps(delta_m2, axis, mirror_index=2)
        if steps_m1:
            self._log(f"Manual target move: axis={axis} mirror=1 steps={steps_m1}")
            self.mirror_backend.relative_move(axis, 1, steps_m1)
        if steps_m2:
            self._log(f"Manual target move: axis={axis} mirror=2 steps={steps_m2}")
            self.mirror_backend.relative_move(axis, 2, steps_m2)

    def _refresh_geometry_readback(self) -> None:
        target_x = UndulatorTarget(offset_mm=self.offset_x_var.get(), angle_urad=self.angle_x_var.get())
        target_y = UndulatorTarget(offset_mm=self.offset_y_var.get(), angle_urad=self.angle_y_var.get())
        angles_x = self.geometry.to_mirror_angles(target_x, "x")
        angles_y = self.geometry.to_mirror_angles(target_y, "y")
        self.mirror1_x_var.set(f"{angles_x.mirror1_urad:.2f}")
        self.mirror2_x_var.set(f"{angles_x.mirror2_urad:.2f}")
        self.mirror1_y_var.set(f"{angles_y.mirror1_urad:.2f}")
        self.mirror2_y_var.set(f"{angles_y.mirror2_urad:.2f}")
        self._draw_geometry_preview()

    def _draw_geometry_preview(self) -> None:
        canvas = self.geometry_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        y_mid = h // 2
        canvas.create_line(30, y_mid, w - 30, y_mid, fill="#888888", dash=(4, 4))
        m1_x = 90
        m2_x = 180
        und_x = 330
        canvas.create_text(m1_x, 40, text="Mirror 1", font=("Helvetica", 11, "bold"))
        canvas.create_text(m2_x, 40, text="Mirror 2", font=("Helvetica", 11, "bold"))
        canvas.create_text(und_x, 40, text="U125 center", font=("Helvetica", 11, "bold"))
        canvas.create_rectangle(m1_x - 8, y_mid - 25, m1_x + 8, y_mid + 25, fill="#1d4ed8")
        canvas.create_rectangle(m2_x - 8, y_mid - 25, m2_x + 8, y_mid + 25, fill="#0f766e")
        canvas.create_oval(und_x - 6, y_mid - 6, und_x + 6, y_mid + 6, fill="#c2410c")
        target_x = UndulatorTarget(offset_mm=self.offset_x_var.get(), angle_urad=self.angle_x_var.get())
        target_y = UndulatorTarget(offset_mm=self.offset_y_var.get(), angle_urad=self.angle_y_var.get())
        beam_y = y_mid - max(min(target_y.offset_mm * 4.0, 100.0), -100.0)
        canvas.create_line(30, y_mid, m1_x, y_mid, fill="#111827", width=2)
        canvas.create_line(m1_x, y_mid, m2_x, beam_y, fill="#111827", width=2)
        canvas.create_line(m2_x, beam_y, und_x, beam_y - target_x.angle_urad * 0.02, fill="#111827", width=2)
        canvas.create_text(und_x + 20, beam_y - target_x.angle_urad * 0.02, text=f"offset≈({target_x.offset_mm:.2f} mm, {target_y.offset_mm:.2f} mm)\nangle≈({target_x.angle_urad:.1f} µrad, {target_y.angle_urad:.1f} µrad)", anchor="w")

    def _schedule_p1_poll(self) -> None:
        if self._p1_poll_after_id is not None:
            self.root.after_cancel(self._p1_poll_after_id)
        delay = max(100, int(self.p1_poll_interval_var.get()))
        self._p1_poll_after_id = self.root.after(delay, self._poll_p1)

    def _poll_p1(self) -> None:
        self._p1_poll_after_id = None
        try:
            if hasattr(self.p1_backend, "update_target"):
                self.p1_backend.update_target(self.angle_x_var.get(), self.angle_y_var.get())
            value = float(self.p1_backend.read())
            if value == value:
                self._p1_history.append(value)
                self._p1_trace.append((time.time(), value))
                self.p1_live_var.set(f"{value:.6g}")
                avg = statistics.fmean(self._p1_history)
                std = statistics.pstdev(self._p1_history) if len(self._p1_history) > 1 else 0.0
                self.p1_avg_var.set(f"{avg:.6g}")
                self.p1_std_var.set(f"{std:.3e}")
                self.p1_samples_used_var.set(str(len(self._p1_history)))
                self.p1_last_update_var.set(time.strftime("%H:%M:%S"))
                self._draw_live_p1_trace()
        except Exception as exc:  # noqa: BLE001
            self.p1_live_var.set("ERR")
            self.p1_last_update_var.set(f"Error: {exc}")
            self._log(f"P1 polling error: {exc}")
        finally:
            self._schedule_p1_poll()

    def _draw_live_p1_trace(self) -> None:
        canvas = self.p1_trace_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 30
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if len(self._p1_trace) < 2:
            canvas.create_text(w // 2, h // 2, text="Waiting for P1 history...", fill="#666666")
            return
        times = [item[0] for item in self._p1_trace]
        values = [item[1] for item in self._p1_trace]
        t_min = min(times)
        t_span = max(max(times) - t_min, 1e-6)
        v_min = min(values)
        v_span = max(max(values) - v_min, 1e-9)
        previous = None
        for timestamp, value in self._p1_trace:
            px = margin + (timestamp - t_min) / t_span * (w - 2 * margin)
            py = h - margin - (value - v_min) / v_span * (h - 2 * margin)
            if previous is not None:
                canvas.create_line(previous[0], previous[1], px, py, fill="#1d4ed8", width=2)
            previous = (px, py)
        canvas.create_text(w // 2, 14, text="Live P1 vs time", font=("Helvetica", 10, "bold"))

    def _start_scan(self) -> None:
        if self.scan_runner.is_running():
            messagebox.showinfo("Scan already running", "Stop the active scan first.")
            return
        self.measurements.clear()
        self._pull_ui_into_config()
        self._refresh_geometry_readback()
        requested_x, requested_y = self._requested_targets()
        context = ScanContext(
            angles_x=self.current_angles_x,
            angles_y=self.current_angles_y,
            offset_x_mm=self.offset_x_var.get(),
            offset_y_mm=self.offset_y_var.get(),
            requested_x=requested_x,
            requested_y=requested_y,
        )
        self.heatmap_canvas.delete("all")
        self.progress_canvas.delete("all")
        self.status_var.set("Scan running...")
        self.best_point_var.set("Best point pending...")
        self.scan_runner.start(context, on_measurement=self._on_measurement_thread, on_finish=self._on_finish_thread)

    def _stop_scan(self) -> None:
        self.scan_runner.request_stop()
        self.status_var.set("Stopping scan...")

    def _on_measurement_thread(self, measurement: MeasurementRecord) -> None:
        self.root.after(0, self._record_measurement, measurement)

    def _record_measurement(self, measurement: MeasurementRecord) -> None:
        self.measurements.append(measurement)
        self.current_angles_x = MirrorAngles(measurement.mirror1_x_urad, measurement.mirror2_x_urad)
        self.current_angles_y = MirrorAngles(measurement.mirror1_y_urad, measurement.mirror2_y_urad)
        self._draw_heatmap()
        self._draw_progress()
        self.status_var.set(f"Scan running: point {measurement.point_index + 1}, P1={measurement.p1_value:.4f}")

    def _on_finish_thread(self, session_dir: Path) -> None:
        self.root.after(0, self._finish_scan, session_dir)

    def _finish_scan(self, session_dir: Path) -> None:
        self.status_var.set("Scan finished.")
        self._update_best_point()
        self.last_export_var.set(f"Saved session: {session_dir}")
        self._save_legacy_state()
        self._log(f"Scan finished. Data saved in {session_dir}")

    def _update_best_point(self) -> None:
        if not self.measurements:
            self.best_point_var.set("No best point available.")
            return
        objective = self.objective_var.get() or "max"
        best = min(self.measurements, key=lambda item: item.p1_value) if objective == "min" else max(self.measurements, key=lambda item: item.p1_value)
        self.best_point_var.set(
            f"Best ({objective}) P1={best.p1_value:.4f} at "
            f"angle_x={best.angle_x_urad:.1f} µrad, angle_y={best.angle_y_urad:.1f} µrad, "
            f"offset=({best.offset_x_mm:.2f}, {best.offset_y_mm:.2f}) mm"
        )

    def _draw_heatmap(self) -> None:
        canvas = self.heatmap_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 50
        span_x = max(self.span_x_var.get(), 1.0)
        span_y = max(self.span_y_var.get(), 1.0)
        center_x = self.center_x_var.get()
        center_y = self.center_y_var.get()
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        for measurement in self.measurements:
            px = margin + (measurement.angle_x_urad - (center_x - span_x / 2.0)) / span_x * (w - 2 * margin)
            py = h - margin - (measurement.angle_y_urad - (center_y - span_y / 2.0)) / span_y * (h - 2 * margin)
            color = self._color_for_p1(measurement.p1_value)
            canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill=color, outline="")
        canvas.create_text(w // 2, 20, text="P1 map vs target interaction angle at fixed undulator point", font=("Helvetica", 12, "bold"))
        canvas.create_text(w // 2, h - 18, text="Angle X [µrad]")
        canvas.create_text(18, h // 2, text="Angle Y [µrad]", angle=90)

    def _draw_progress(self) -> None:
        canvas = self.progress_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 45
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if not self.measurements:
            return
        max_p1 = max(m.p1_value for m in self.measurements)
        min_p1 = min(m.p1_value for m in self.measurements)
        span = max(max_p1 - min_p1, 1e-6)
        prev = None
        for idx, m in enumerate(self.measurements):
            px = margin + idx / max(len(self.measurements) - 1, 1) * (w - 2 * margin)
            py = h - margin - (m.p1_value - min_p1) / span * (h - 2 * margin)
            if prev:
                canvas.create_line(prev[0], prev[1], px, py, fill="#1d4ed8", width=2)
            prev = (px, py)
            canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#c2410c", outline="")
        canvas.create_text(w // 2, 18, text="P1 trace during scan", font=("Helvetica", 11, "bold"))

    def _color_for_p1(self, value: float) -> str:
        value = max(0.0, min(1.0, value))
        r = int(255 * value)
        g = int(180 * (1.0 - value) + 40 * value)
        b = int(255 * (1.0 - value))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _log(self, message: str) -> None:
        self.debug_text.insert("end", message + "\n")
        self.debug_text.see("end")

    def on_close(self) -> None:
        if self._p1_poll_after_id is not None:
            self.root.after_cancel(self._p1_poll_after_id)
            self._p1_poll_after_id = None
        if self.scan_runner.is_running():
            if not messagebox.askyesno("Scan still running", "A scan is still running. Stop it and close the application?"):
                return
            self.scan_runner.request_stop()
            self.scan_runner.join(timeout=3.0)
        try:
            self._save_legacy_state()
            self._save_config()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    app = LaserMirrorApp(root, Path(args.config), force_safe_mode=args.safe_mode)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0
