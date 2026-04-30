from __future__ import annotations

import argparse
import csv
import json
import math
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .core import (
    BeamGeometry,
    GeometryConfig,
    MOTOR_PVS,
    Measurement,
    MotionConfig,
    SIGNAL_PV_CANDIDATES,
    ScanPoint,
    SimP1,
    build_angle_grid,
    build_mirror2_spiral,
    now,
    ramp_values,
)
from .epics_backend import EpicsMotor, PVFactory


class LaserMirrorScanApp:
    def __init__(self, root: tk.Tk, safe_mode: bool, write_mode: bool):
        self.root = root
        self.safe_mode = safe_mode
        self.write_mode = write_mode
        self.root.title("SSMB Laser Mirror Scan")

        self.run_root = Path.cwd() / "laser_mirror_runs"
        self.run_root.mkdir(exist_ok=True)
        self.session_dir = self.run_root / now().replace(":", "").replace(".", "_")
        self.session_dir.mkdir()
        self.log_path = self.session_dir / "run.log"
        self.config_path = self.session_dir / "config.json"
        self.angle_csv = self.session_dir / "angle_scan.csv"
        self.spiral_csv = self.session_dir / "mirror2_spiral.csv"
        self.state_path = Path.cwd() / "laser_mirror_recovery_state.json"
        self.last_command_path = Path.cwd() / "laser_mirror_last_command.json"

        self.geometry = BeamGeometry(GeometryConfig())
        self.motion_cfg = MotionConfig()
        self.factory = PVFactory(safe_mode)
        self.motors = {key: EpicsMotor(key, pv, self.factory) for key, pv in MOTOR_PVS.items()}
        self.reference_steps = {key: 0.0 for key in MOTOR_PVS}

        self.events = queue.Queue()
        self.measurements: list[Measurement] = []
        self.current_plan: list[ScanPoint] = []
        self.current_h_angle = 0.0
        self.current_v_angle = 0.0
        self.current_mode = "angle"
        self.sim_p1 = SimP1()
        self._load_persistent_state_if_any()
        self.p1_pv = None
        self.scan_thread = None
        self.stop_event = threading.Event()

        self._build_ui()
        for m in self.motors.values():
            m.monitor(self._monitor)
        self._read_motors(False)
        self._capture_reference(confirm=False)
        self._log(f"START safe_mode={safe_mode} write_mode={write_mode}")
        self._log(f"session={self.session_dir}")
        self._poll()
        self._drain_events()

    # UI -----------------------------------------------------------------

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(
            top,
            text=("SAFE SIM" if self.safe_mode else "REAL EPICS") + " | " + ("WRITE ENABLED" if self.write_mode else "READ ONLY"),
            font=("TkDefaultFont", 11, "bold"),
        ).pack(side="left")
        ttk.Label(top, text=str(self.session_dir), foreground="#555").pack(side="right")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.overview = ttk.Frame(nb, padding=8)
        self.angle_tab = ttk.Frame(nb, padding=8)
        self.spiral_tab = ttk.Frame(nb, padding=8)
        self.manual_tab = ttk.Frame(nb, padding=8)
        self.log_tab = ttk.Frame(nb, padding=8)

        nb.add(self.overview, text="Overview + Beam")
        nb.add(self.angle_tab, text="Angle scan")
        nb.add(self.spiral_tab, text="Mirror 2 spiral")
        nb.add(self.manual_tab, text="Manual control")
        nb.add(self.log_tab, text="Log")

        self._build_overview()
        self._build_angle()
        self._build_spiral()
        self._build_manual()
        self._build_log()

    def _build_overview(self):
        left = ttk.Frame(self.overview)
        right = ttk.Frame(self.overview)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.overview.columnconfigure(0, weight=1)
        self.overview.columnconfigure(1, weight=1)
        self.overview.rowconfigure(0, weight=1)

        cols = ["key", "pv", "desc", "egu", "val", "rbv", "dmov", "movn", "stat", "sevr"]
        self.motor_tree = ttk.Treeview(left, columns=cols, show="headings", height=8)
        for c in cols:
            self.motor_tree.heading(c, text=c)
            self.motor_tree.column(c, width=100 if c not in ("pv", "desc") else 145)
        self.motor_tree.pack(fill="x")
        for k, m in self.motors.items():
            self.motor_tree.insert("", "end", iid=k, values=[k, m.base, "", "", "", "", "", "", "", ""])

        row = ttk.Frame(left)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Read", command=lambda: self._read_motors(True)).pack(side="left")
        ttk.Button(row, text="Capture RBV as reference", command=lambda: self._capture_reference(True)).pack(side="left", padx=6)
        ttk.Button(row, text="Return to reference", command=self._return_reference).pack(side="left", padx=6)
        ttk.Button(row, text="STOP all", command=self._stop_all).pack(side="left", padx=6)

        self.ref_var = tk.StringVar()
        ttk.Label(left, textvariable=self.ref_var, justify="left").pack(anchor="w")

        p1 = ttk.LabelFrame(left, text="P1 readback", padding=8)
        p1.pack(fill="x", pady=8)
        self.p1_name = tk.StringVar(value="")
        self.signal_kind = tk.StringVar(value="simulated_p1")
        self.p1_live = tk.StringVar(value="simulated")
        ttk.Label(p1, text="Signal").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p1, textvariable=self.signal_kind, values=list(SIGNAL_PV_CANDIDATES.keys()), state="readonly", width=22).grid(row=0, column=1, sticky="w")
        ttk.Button(p1, text="Use preset", command=self._use_signal_preset).grid(row=0, column=2)
        ttk.Label(p1, text="PV").grid(row=1, column=0, sticky="w")
        ttk.Entry(p1, textvariable=self.p1_name, width=40).grid(row=1, column=1)
        ttk.Button(p1, text="Connect", command=self._connect_p1).grid(row=1, column=2)
        ttk.Label(p1, textvariable=self.p1_live).grid(row=2, column=1, sticky="w")

        self.beam_canvas = tk.Canvas(right, bg="white", width=620, height=380, highlightthickness=1, highlightbackground="#ccc")
        self.beam_canvas.pack(fill="both", expand=True)
        self.p1_trace_canvas = tk.Canvas(right, bg="white", width=620, height=170, highlightthickness=1, highlightbackground="#ccc")
        self.p1_trace_canvas.pack(fill="x", pady=(10, 0))

    def _build_angle(self):
        controls = ttk.LabelFrame(self.angle_tab, text="Carsten scan: vary interaction angle while holding offset", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plot = ttk.LabelFrame(self.angle_tab, text="Live 2D P1 map", padding=10)
        plot.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.angle_tab.columnconfigure(1, weight=1)
        self.angle_tab.rowconfigure(0, weight=1)

        self.center_h = tk.DoubleVar(value=0.0)
        self.center_v = tk.DoubleVar(value=0.0)
        self.span_h = tk.DoubleVar(value=400.0)
        self.span_v = tk.DoubleVar(value=400.0)
        self.points_h = tk.IntVar(value=9)
        self.points_v = tk.IntVar(value=9)
        self.offset_h = tk.DoubleVar(value=0.0)
        self.offset_v = tk.DoubleVar(value=0.0)
        self.dwell = tk.DoubleVar(value=0.5)
        self.samples = tk.IntVar(value=3)
        self.angle_mode = tk.StringVar(value="both_2d")
        self.serpentine = tk.BooleanVar(value=True)

        rows = [
            ("Center H angle [µrad]", self.center_h),
            ("Center V angle [µrad]", self.center_v),
            ("Span H angle [µrad]", self.span_h),
            ("Span V angle [µrad]", self.span_v),
            ("Points H", self.points_h),
            ("Points V", self.points_v),
            ("Held H offset [mm]", self.offset_h),
            ("Held V offset [mm]", self.offset_v),
            ("Dwell [s]", self.dwell),
            ("P1 samples", self.samples),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(controls, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(controls, textvariable=var, width=15).grid(row=i, column=1, sticky="e")

        ttk.Label(controls, text="Mode").grid(row=len(rows), column=0, sticky="w")
        ttk.Combobox(controls, textvariable=self.angle_mode, values=["both_2d", "horizontal_only", "vertical_only"], state="readonly", width=15).grid(row=len(rows), column=1)
        ttk.Checkbutton(controls, text="Serpentine", variable=self.serpentine).grid(row=len(rows)+1, column=0, columnspan=2, sticky="w")

        ttk.Button(controls, text="Preview", command=self._preview_angle).grid(row=len(rows)+2, column=0, pady=8)
        ttk.Button(controls, text="Start", command=self._start_angle_scan).grid(row=len(rows)+2, column=1, pady=8)
        ttk.Button(controls, text="Request stop after point", command=self._request_stop).grid(row=len(rows)+3, column=0)
        self.angle_status = tk.StringVar(value="Idle")
        ttk.Label(controls, textvariable=self.angle_status, foreground="#0f766e", wraplength=300).grid(row=len(rows)+4, column=0, columnspan=2, sticky="w")

        self.angle_map = tk.Canvas(plot, bg="white", width=650, height=470, highlightthickness=1, highlightbackground="#ccc")
        self.angle_map.pack(fill="both", expand=True)

    def _build_spiral(self):
        controls = ttk.LabelFrame(self.spiral_tab, text="Legacy-style mirror 2 spiral scan", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plot = ttk.LabelFrame(self.spiral_tab, text="P1 over mirror 2 position", padding=10)
        plot.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.spiral_tab.columnconfigure(1, weight=1)
        self.spiral_tab.rowconfigure(0, weight=1)

        self.sp_center_h = tk.DoubleVar(value=0.0)
        self.sp_center_v = tk.DoubleVar(value=0.0)
        self.sp_step_h = tk.DoubleVar(value=6.0)
        self.sp_step_v = tk.DoubleVar(value=8.0)
        self.sp_turns = tk.IntVar(value=30)
        self.sp_dwell = tk.DoubleVar(value=1.0)
        self.sp_samples = tk.IntVar(value=3)

        rows = [
            ("Mirror 2 H center [steps]", self.sp_center_h),
            ("Mirror 2 V center [steps]", self.sp_center_v),
            ("H step [steps]", self.sp_step_h),
            ("V step [steps]", self.sp_step_v),
            ("Spiral turns", self.sp_turns),
            ("Dwell [s]", self.sp_dwell),
            ("P1 samples", self.sp_samples),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(controls, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(controls, textvariable=var, width=15).grid(row=i, column=1, sticky="e")

        ttk.Button(controls, text="Use current M2 RBV as center", command=self._use_current_m2_center).grid(row=len(rows), column=0, columnspan=2, pady=6)
        ttk.Button(controls, text="Preview", command=self._preview_spiral).grid(row=len(rows)+1, column=0, pady=8)
        ttk.Button(controls, text="Start", command=self._start_spiral_scan).grid(row=len(rows)+1, column=1, pady=8)
        ttk.Button(controls, text="Request stop after point", command=self._request_stop).grid(row=len(rows)+2, column=0)

        self.spiral_status = tk.StringVar(value="Idle")
        ttk.Label(controls, textvariable=self.spiral_status, foreground="#0f766e", wraplength=300).grid(row=len(rows)+3, column=0, columnspan=2, sticky="w")

        self.spiral_map = tk.Canvas(plot, bg="white", width=650, height=470, highlightthickness=1, highlightbackground="#ccc")
        self.spiral_map.pack(fill="both", expand=True)


    def _build_manual(self):
        left = ttk.Frame(self.manual_tab)
        right = ttk.Frame(self.manual_tab)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.manual_tab.columnconfigure(1, weight=1)

        box = ttk.LabelFrame(left, text="Manual motor move", padding=10)
        box.pack(fill="x")
        self.manual_motor = tk.StringVar(value="m2_horizontal")
        self.manual_delta = tk.DoubleVar(value=1.0)
        self.manual_absolute = tk.DoubleVar(value=0.0)

        ttk.Label(box, text="Motor").grid(row=0, column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.manual_motor, values=list(self.motors.keys()), state="readonly", width=18).grid(row=0, column=1, sticky="ew")
        ttk.Label(box, text="Delta [steps]").grid(row=1, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.manual_delta, width=14).grid(row=1, column=1, sticky="w")
        ttk.Button(box, text="Nudge +", command=lambda: self._manual_nudge(+1)).grid(row=2, column=0, pady=6)
        ttk.Button(box, text="Nudge -", command=lambda: self._manual_nudge(-1)).grid(row=2, column=1, pady=6)

        ttk.Label(box, text="Absolute target [steps]").grid(row=3, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.manual_absolute, width=14).grid(row=3, column=1, sticky="w")
        ttk.Button(box, text="Move absolute", command=self._manual_absolute_move).grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)

        safe = ttk.LabelFrame(left, text="Slow motion settings", padding=10)
        safe.pack(fill="x", pady=(10, 0))
        self.max_step_per_put = tk.DoubleVar(value=self.motion_cfg.max_step_per_put)
        self.inter_put_delay = tk.DoubleVar(value=self.motion_cfg.inter_put_delay_s)
        self.settle_s = tk.DoubleVar(value=self.motion_cfg.settle_s)
        self.max_delta_ref = tk.DoubleVar(value=self.motion_cfg.max_delta_from_reference)
        for i, (label, var) in enumerate([
            ("Max steps per put", self.max_step_per_put),
            ("Delay between puts [s]", self.inter_put_delay),
            ("Settle after DMOV [s]", self.settle_s),
            ("Max delta from ref [steps]", self.max_delta_ref),
        ]):
            ttk.Label(safe, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(safe, textvariable=var, width=12).grid(row=i, column=1, sticky="w")
        ttk.Button(safe, text="Apply settings", command=self._apply_motion_settings).grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)

        notes = (
            "Manual moves use the same slow ramp as scans. This reduces IOC/controller stress.\\n"
            "Use 1 step first. Increase only after stable operation.\\n"
            "The recovery file is updated before and after every write command."
        )
        ttk.Label(right, text=notes, wraplength=520, justify="left").pack(anchor="w")

    def _build_log(self):
        self.log_text = tk.Text(self.log_tab, width=120, height=34)
        self.log_text.pack(fill="both", expand=True)


    def _load_persistent_state_if_any(self):
        self.persistent_state = {}
        try:
            if self.state_path.exists():
                self.persistent_state = json.loads(self.state_path.read_text())
        except Exception:
            self.persistent_state = {}

    def _save_persistent_state(self, label="state"):
        data = {
            "timestamp": now(),
            "label": label,
            "safe_mode": self.safe_mode,
            "write_mode": self.write_mode,
            "reference_steps": self.reference_steps,
            "latest_rbv": {},
            "latest_val": {},
        }
        for k, m in self.motors.items():
            try:
                s = m.snapshot()
                data["latest_rbv"][k] = s.rbv
                data["latest_val"][k] = s.val
            except Exception:
                pass
        self.state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        self._log(f"STATE_SAVED {label} {self.state_path}")

    def _save_last_command(self, targets, label="command"):
        data = {
            "timestamp": now(),
            "label": label,
            "targets": targets if isinstance(targets, dict) else asdict(targets),
        }
        self.last_command_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    # Logging / polling ---------------------------------------------------

    def _log(self, msg: str):
        line = f"{now()} {msg}"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
        except Exception:
            pass

    def _monitor(self, key, pv, value):
        self.events.put(f"MONITOR {key} {pv}={value}")

    def _drain_events(self):
        try:
            while True:
                self._log(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(250, self._drain_events)

    def _poll(self):
        self._read_motors(False)
        self._update_p1()
        self._draw_beam()
        self._draw_trace()
        self.root.after(500, self._poll)

    # EPICS / state -------------------------------------------------------

    def _read_motors(self, log=False):
        for k, m in self.motors.items():
            try:
                s = m.snapshot()
                self.motor_tree.item(k, values=[k, m.base, s.desc, s.egu, f"{s.val:.0f}", f"{s.rbv:.0f}", s.dmov, s.movn, s.stat, s.sevr])
                if log:
                    self._log(f"READ {s}")
            except Exception as exc:
                if log:
                    self._log(f"READ_ERROR {k}: {exc}")

    def _capture_reference(self, confirm=True):
        if confirm and not messagebox.askyesno("Capture reference", "Use current RBVs as zero/reference for scans?"):
            return
        for k, m in self.motors.items():
            s = m.snapshot()
            self.reference_steps[k] = s.rbv
        self._update_ref_label()
        self._log(f"REFERENCE {self.reference_steps}")
        self._save_persistent_state("reference")

    def _update_ref_label(self):
        self.ref_var.set("\n".join(f"{k}: {v:.0f} steps" for k, v in self.reference_steps.items()))

    def _use_signal_preset(self):
        self.p1_name.set(SIGNAL_PV_CANDIDATES.get(self.signal_kind.get(), ""))
        self._connect_p1()

    def _connect_p1(self):
        name = self.p1_name.get().strip()
        if not name:
            self.p1_pv = None
            self._log("P1 using simulated readback")
            return
        self.p1_pv = self.factory.pv(name, 0)
        self._log(f"P1 connected {name}")

    def _read_p1(self, ah=0.0, av=0.0) -> float:
        if self.p1_pv is not None:
            try:
                return float(self.p1_pv.get(timeout=0.5))
            except Exception:
                return math.nan
        return self.sim_p1.read(ah, av)

    def _update_p1(self):
        val = self._read_p1(self.current_h_angle, self.current_v_angle)
        self.p1_live.set(f"P1: {val:.5g}" if val == val else "P1: nan")

    def _require_write(self) -> bool:
        if self.write_mode:
            return True
        messagebox.showwarning("Read-only mode", "Restart with --write-mode for real motor writes.")
        self._log("WRITE_BLOCKED")
        return False

    def _apply_motion_settings(self):
        self.motion_cfg.max_step_per_put = max(1.0, float(self.max_step_per_put.get()))
        self.motion_cfg.inter_put_delay_s = max(0.0, float(self.inter_put_delay.get()))
        self.motion_cfg.settle_s = max(0.0, float(self.settle_s.get()))
        self.motion_cfg.max_delta_from_reference = max(1.0, float(self.max_delta_ref.get()))
        self._log(f"MOTION_SETTINGS {asdict(self.motion_cfg)}")

    def _validate_targets_against_reference(self, target_dict: dict[str, float]) -> bool:
        limit = self.motion_cfg.max_delta_from_reference
        for key, value in target_dict.items():
            if abs(value - self.reference_steps[key]) > limit:
                self._log(f"LIMIT_REJECT {key} target={value} reference={self.reference_steps[key]} limit={limit}")
                messagebox.showerror("Soft limit exceeded", f"{key}: target {value:.1f} is more than {limit:.1f} steps from reference.")
                return False
        return True

    def _move_targets(self, targets) -> bool:
        target_dict = targets if isinstance(targets, dict) else asdict(targets)
        if not self._validate_targets_against_reference(target_dict):
            return False
        if not self.write_mode:
            self._log(f"DRY_RUN targets={target_dict}")
            return True

        self._save_persistent_state("before_move")
        self._save_last_command(target_dict, "before_move")

        ok = True
        # Move in synchronized ramps: calculate all intermediate values, then issue one small step per motor per ramp layer.
        starts = {key: self.motors[key].snapshot().rbv for key in target_dict}
        ramps = {key: ramp_values(starts[key], target_dict[key], self.motion_cfg.max_step_per_put) for key in target_dict}
        layers = max(len(v) for v in ramps.values()) if ramps else 0

        for i in range(layers):
            if self.stop_event.is_set():
                self._log("MOVE_ABORTED_BY_STOP_EVENT")
                return False
            layer_targets = {}
            for key, values in ramps.items():
                layer_targets[key] = values[min(i, len(values) - 1)]
            self._log(f"MOVE_LAYER {i+1}/{layers} {layer_targets}")
            for key, value in layer_targets.items():
                self.motors[key].move(value)
                time.sleep(self.motion_cfg.inter_put_delay_s)
            for key in layer_targets:
                self._log(f"WAIT_DMOV {key} timeout={self.motion_cfg.wait_timeout_s}")
                done = self.motors[key].wait_done(self.motion_cfg.wait_timeout_s)
                self._log(f"WAIT_DMOV_DONE {key} done={done}")
                ok = done and ok
            time.sleep(self.motion_cfg.settle_s)

        self._save_persistent_state("after_move")
        return ok

    def _stop_all(self):
        if not self._require_write():
            return
        if not messagebox.askyesno("STOP all", "Write STOP=1 to all four motors?"):
            return
        for m in self.motors.values():
            m.stop()
        self._log("STOP_ALL")

    def _return_reference(self):
        if not self._require_write():
            return
        if not messagebox.askyesno("Return to reference", "Move all four motors back to captured reference?"):
            return
        from .core import MotorTargets
        targets = MotorTargets(**self.reference_steps)
        self._move_targets(targets)


    def _manual_nudge(self, sign: int):
        if not self._require_write():
            return
        key = self.manual_motor.get()
        current = self.motors[key].snapshot().rbv
        target = current + sign * float(self.manual_delta.get())
        if not messagebox.askyesno("Confirm nudge", f"Move {key} from {current:.1f} to {target:.1f} steps?"):
            return
        self._move_targets({key: target})

    def _manual_absolute_move(self):
        if not self._require_write():
            return
        key = self.manual_motor.get()
        target = float(self.manual_absolute.get())
        current = self.motors[key].snapshot().rbv
        if not messagebox.askyesno("Confirm absolute move", f"Move {key} from {current:.1f} to {target:.1f} steps?"):
            return
        self._move_targets({key: target})

    # Planning ------------------------------------------------------------

    def _angle_plan(self):
        return build_angle_grid(
            self.geometry,
            self.reference_steps,
            self.center_h.get(),
            self.center_v.get(),
            self.span_h.get(),
            self.span_v.get(),
            self.points_h.get(),
            self.points_v.get(),
            self.offset_h.get(),
            self.offset_v.get(),
            self.angle_mode.get(),
            self.serpentine.get(),
        )

    def _spiral_plan(self):
        return build_mirror2_spiral(
            self.reference_steps,
            self.sp_center_h.get(),
            self.sp_center_v.get(),
            self.sp_step_h.get(),
            self.sp_step_v.get(),
            self.sp_turns.get(),
        )

    def _preview_angle(self):
        self.current_mode = "angle"
        self.current_plan = self._angle_plan()
        self.measurements = []
        self._draw_angle_map(self.current_plan, [])
        self._write_config("angle_preview")
        self._log(f"ANGLE_PREVIEW points={len(self.current_plan)}")

    def _preview_spiral(self):
        self.current_mode = "spiral"
        self.current_plan = self._spiral_plan()
        self.measurements = []
        self._draw_spiral_map(self.current_plan, [])
        self._write_config("spiral_preview")
        self._log(f"SPIRAL_PREVIEW points={len(self.current_plan)}")

    def _use_current_m2_center(self):
        self.sp_center_h.set(self.motors["m2_horizontal"].snapshot().rbv)
        self.sp_center_v.set(self.motors["m2_vertical"].snapshot().rbv)

    # Running -------------------------------------------------------------


    def _show_preflight(self, plan, title: str, dwell: float, samples: int) -> bool:
        """Show all planned PV writes before any scan starts."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("1050x520")
        ttk.Label(
            win,
            text=(
                f"{title}\n"
                f"points={len(plan)}, dwell={dwell}s, samples={samples}, "
                f"max_step_per_put={self.motion_cfg.max_step_per_put}, "
                f"inter_put_delay={self.motion_cfg.inter_put_delay_s}s, "
                f"settle={self.motion_cfg.settle_s}s\n"
                "The scan waits for .DMOV=1 after each ramp layer and before measuring. "
                "Request Stop stops after the current ramp/point; STOP all is a separate hard stop."
            ),
            justify="left",
            wraplength=1000,
        ).pack(anchor="w", padx=8, pady=8)

        cols = [
            "idx", "mode", "angle_h", "angle_v",
            "m1_h", "m1_v", "m2_h", "m2_v",
            "max_delta_ref", "layers_est"
        ]
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=90 if c not in ("mode",) else 120)
        tree.pack(fill="both", expand=True, padx=8)

        max_overall_delta = 0.0
        worst = ""
        for p in plan:
            t = asdict(p.motor_targets)
            max_delta = max(abs(t[k] - self.reference_steps[k]) for k in t)
            max_overall_delta = max(max_overall_delta, max_delta)
            if max_delta == max_overall_delta:
                worst = f"point {p.index}"
            starts = {k: self.motors[k].snapshot().rbv for k in t}
            layers = max(len(ramp_values(starts[k], t[k], self.motion_cfg.max_step_per_put)) for k in t)
            tree.insert("", "end", values=[
                p.index, p.mode,
                f"{p.angle_h_urad:.3g}", f"{p.angle_v_urad:.3g}",
                f"{t['m1_horizontal']:.1f}", f"{t['m1_vertical']:.1f}",
                f"{t['m2_horizontal']:.1f}", f"{t['m2_vertical']:.1f}",
                f"{max_delta:.1f}", layers,
            ])

        result = {"ok": False}
        status = ttk.Label(
            win,
            text=f"Worst target distance from reference: {max_overall_delta:.1f} steps at {worst}. Soft limit: {self.motion_cfg.max_delta_from_reference:.1f} steps.",
            foreground="#991b1b" if max_overall_delta > self.motion_cfg.max_delta_from_reference else "#0f766e",
            wraplength=1000,
        )
        status.pack(anchor="w", padx=8, pady=8)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)

        def approve():
            result["ok"] = True
            win.destroy()

        def cancel():
            result["ok"] = False
            win.destroy()

        ttk.Button(btns, text="Approve and run", command=approve).pack(side="left")
        ttk.Button(btns, text="Cancel", command=cancel).pack(side="left", padx=8)

        win.transient(self.root)
        win.grab_set()
        self.root.wait_window(win)
        self._log(f"PREFLIGHT {title} approved={result['ok']} points={len(plan)} max_delta={max_overall_delta}")
        return result["ok"]

    def _start_angle_scan(self):
        if not self._require_write():
            return
        plan = self._angle_plan()
        if not self._show_preflight(plan, "Angle scan preflight", self.dwell.get(), self.samples.get()):
            return
        self.current_mode = "angle"
        self._start_scan(plan, self.angle_csv, self.dwell.get(), self.samples.get(), self.angle_status, self._draw_angle_map)

    def _start_spiral_scan(self):
        if not self._require_write():
            return
        plan = self._spiral_plan()
        if not self._show_preflight(plan, "Mirror 2 spiral preflight", self.sp_dwell.get(), self.sp_samples.get()):
            return
        self.current_mode = "spiral"
        self._start_scan(plan, self.spiral_csv, self.sp_dwell.get(), self.sp_samples.get(), self.spiral_status, self._draw_spiral_map)

    def _start_scan(self, plan, csv_path, dwell, samples, status_var, draw_func):
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Scan running", "A scan is already running.")
            return
        self.stop_event.clear()
        self.measurements = []
        self.current_plan = plan
        self._write_config("scan_start")
        self.scan_thread = threading.Thread(target=self._scan_worker, args=(plan, csv_path, dwell, samples, status_var, draw_func), daemon=True)
        self.scan_thread.start()

    def _request_stop(self):
        self.stop_event.set()
        self._log("STOP_REQUESTED")

    def _scan_worker(self, plan: list[ScanPoint], csv_path: Path, dwell: float, samples: int, status_var, draw_func):
        self._log(f"SCAN_START mode={plan[0].mode if plan else 'empty'} points={len(plan)} csv={csv_path}")
        fields = list(asdict(Measurement("", 0, "", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)).keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for p in plan:
                if self.stop_event.is_set():
                    self._log("SCAN_STOPPED")
                    break
                self.current_h_angle = p.angle_h_urad if p.angle_h_urad == p.angle_h_urad else 0.0
                self.current_v_angle = p.angle_v_urad if p.angle_v_urad == p.angle_v_urad else 0.0
                self.root.after(0, lambda p=p: status_var.set(f"Point {p.index}: H={p.angle_h_urad:.3g}, V={p.angle_v_urad:.3g}"))
                self._log(f"POINT {p.index} targets={asdict(p.motor_targets)}")
                ok = self._move_targets(p.motor_targets)
                if not ok:
                    self._log(f"WARN point={p.index} DMOV timeout")
                time.sleep(max(0.0, dwell))
                vals = []
                for _ in range(max(1, int(samples))):
                    vals.append(self._read_p1(self.current_h_angle, self.current_v_angle))
                    time.sleep(0.02)
                good = [v for v in vals if v == v]
                p1 = sum(good) / len(good) if good else math.nan
                snaps = {k: m.snapshot() for k, m in self.motors.items()}
                meas = Measurement(
                    timestamp=now(),
                    index=p.index,
                    mode=p.mode,
                    angle_h_urad=p.angle_h_urad,
                    angle_v_urad=p.angle_v_urad,
                    offset_h_mm=p.offset_h_mm,
                    offset_v_mm=p.offset_v_mm,
                    target_m1_horizontal=p.motor_targets.m1_horizontal,
                    target_m1_vertical=p.motor_targets.m1_vertical,
                    target_m2_horizontal=p.motor_targets.m2_horizontal,
                    target_m2_vertical=p.motor_targets.m2_vertical,
                    rbv_m1_horizontal=snaps["m1_horizontal"].rbv,
                    rbv_m1_vertical=snaps["m1_vertical"].rbv,
                    rbv_m2_horizontal=snaps["m2_horizontal"].rbv,
                    rbv_m2_vertical=snaps["m2_vertical"].rbv,
                    p1=p1,
                    samples=len(good),
                )
                self.measurements.append(meas)
                writer.writerow(asdict(meas))
                f.flush()
                self.root.after(0, lambda: draw_func(plan, self.measurements))
                self._log(f"MEAS point={p.index} p1={p1:.6g}")
        self.root.after(0, lambda: status_var.set(f"Done. CSV: {csv_path}"))
        self._log("SCAN_DONE")

    # Drawing -------------------------------------------------------------

    def _draw_beam(self):
        c = self.beam_canvas
        c.delete("all")
        w = int(c.winfo_width() or 620)
        h = int(c.winfo_height() or 380)
        c.create_text(12, 10, anchor="w", text="Schematic steering geometry: M1 → M2 → undulator center")
        margin = 55
        x_min = -0.35 * self.geometry.cfg.mirror_distance_mm
        x_max = self.geometry.cfg.mirror_distance_mm + self.geometry.cfg.undulator_distance_mm
        y_scale_mm = 25.0

        def map_xy(x_mm, y_mm):
            x = margin + (x_mm - x_min) / (x_max - x_min) * (w - 2 * margin)
            y = h / 2 - y_mm / y_scale_mm * (h * 0.35)
            return x, y

        # horizontal-plane ray shown as red, vertical-plane ray shown as blue with artificial offset
        for angle, offset, color, label, y_shift in [
            (self.current_h_angle, self.offset_h.get() if hasattr(self, "offset_h") else 0.0, "#dc2626", "horizontal plane", -18),
            (self.current_v_angle, self.offset_v.get() if hasattr(self, "offset_v") else 0.0, "#2563eb", "vertical plane", 18),
        ]:
            pts = self.geometry.ray_polyline(angle, offset)
            mapped = []
            for x, y in pts:
                mx, my = map_xy(x, y)
                mapped.append((mx, my + y_shift))
            for a, b in zip(mapped[:-1], mapped[1:]):
                c.create_line(a[0], a[1], b[0], b[1], fill=color, width=2, arrow=tk.LAST if b == mapped[-1] else None)
            c.create_text(w - 150, 35 if color == "#dc2626" else 55, text=label, fill=color, anchor="w")

        md = self.geometry.cfg.mirror_distance_mm
        xu = md + self.geometry.cfg.undulator_distance_mm
        for x, label, fill in [(0, "M1", "#2563eb"), (md, "M2", "#059669"), (xu, "U center", "#ea580c")]:
            mx, my = map_xy(x, 0)
            if label.startswith("M"):
                c.create_line(mx - 15, my - 38, mx + 15, my + 38, fill=fill, width=5)
            else:
                c.create_oval(mx - 8, my - 8, mx + 8, my + 8, fill=fill, outline="")
            c.create_text(mx, my + 55, text=label)

        axis_y = map_xy(0, 0)[1]
        c.create_line(margin, axis_y, w - margin, axis_y, fill="#999", dash=(4, 4))
        c.create_text(15, h - 45, anchor="w", text=f"H angle: {self.current_h_angle:.2f} µrad")
        c.create_text(15, h - 25, anchor="w", text=f"V angle: {self.current_v_angle:.2f} µrad")

    def _draw_trace(self):
        c = self.p1_trace_canvas
        c.delete("all")
        c.create_text(10, 10, anchor="w", text="P1 trace")
        if len(self.measurements) < 2:
            return
        vals = [m.p1 for m in self.measurements if m.p1 == m.p1]
        if len(vals) < 2:
            return
        w = int(c.winfo_width() or 620)
        h = int(c.winfo_height() or 170)
        lo, hi = min(vals), max(vals)
        if hi == lo:
            hi += 1
        pts = []
        for i, v in enumerate(vals):
            x = 35 + i * (w - 60) / max(1, len(vals) - 1)
            y = h - 25 - (v - lo) / (hi - lo) * (h - 55)
            pts.append((x, y))
        for a, b in zip(pts[:-1], pts[1:]):
            c.create_line(a[0], a[1], b[0], b[1], fill="#111827", width=2)

    def _draw_angle_map(self, plan, measurements):
        self._draw_map(self.angle_map, plan, measurements, "angle_h_urad", "angle_v_urad", "H angle [µrad]", "V angle [µrad]")

    def _draw_spiral_map(self, plan, measurements):
        self._draw_map(self.spiral_map, plan, measurements, "target_m2_horizontal", "target_m2_vertical", "M2 horizontal [steps]", "M2 vertical [steps]")

    def _draw_map(self, canvas, plan, measurements, xattr, yattr, xlabel, ylabel):
        c = canvas
        c.delete("all")
        w = int(c.winfo_width() or 650)
        h = int(c.winfo_height() or 470)
        margin = 55
        c.create_text(10, 10, anchor="w", text=f"P1 map: {xlabel} vs {ylabel}")

        if xattr.startswith("angle"):
            xs = [p.angle_h_urad for p in plan]
            ys = [p.angle_v_urad for p in plan]
        else:
            xs = [p.motor_targets.m2_horizontal for p in plan]
            ys = [p.motor_targets.m2_vertical for p in plan]
        if not xs or not ys:
            return
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmin == xmax:
            xmin -= 1
            xmax += 1
        if ymin == ymax:
            ymin -= 1
            ymax += 1

        def xy(x, y):
            px = margin + (x - xmin) / (xmax - xmin) * (w - 2 * margin)
            py = h - margin - (y - ymin) / (ymax - ymin) * (h - 2 * margin)
            return px, py

        c.create_rectangle(margin, margin, w - margin, h - margin, outline="#bbb")
        c.create_text(w / 2, h - 18, text=xlabel)
        c.create_text(20, h / 2, text=ylabel, angle=90)

        for p in plan:
            if xattr.startswith("angle"):
                x, y = p.angle_h_urad, p.angle_v_urad
            else:
                x, y = p.motor_targets.m2_horizontal, p.motor_targets.m2_vertical
            px, py = xy(x, y)
            c.create_oval(px - 2, py - 2, px + 2, py + 2, fill="#ddd", outline="")

        vals = [m.p1 for m in measurements if m.p1 == m.p1]
        lo, hi = (min(vals), max(vals)) if vals else (0, 1)
        if hi == lo:
            hi += 1
        for m in measurements:
            if xattr.startswith("angle"):
                x, y = m.angle_h_urad, m.angle_v_urad
            else:
                x, y = m.target_m2_horizontal, m.target_m2_vertical
            px, py = xy(x, y)
            frac = (m.p1 - lo) / (hi - lo) if m.p1 == m.p1 else 0
            r = 4 + 10 * frac
            fill = "#dc2626" if frac > 0.66 else "#f59e0b" if frac > 0.33 else "#2563eb"
            c.create_oval(px - r, py - r, px + r, py + r, fill=fill, outline="")

    # Config / close ------------------------------------------------------

    def _write_config(self, event):
        cfg = {
            "event": event,
            "safe_mode": self.safe_mode,
            "write_mode": self.write_mode,
            "motor_pvs": MOTOR_PVS,
            "geometry": asdict(self.geometry.cfg),
            "reference_steps": self.reference_steps,
            "p1_pv": self.p1_name.get(),
            "signal_kind": self.signal_kind.get(),
            "motion": asdict(self.motion_cfg),
            "state_path": str(self.state_path),
            "last_command_path": str(self.last_command_path),
        }
        self.config_path.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")

    def close(self):
        if self.scan_thread and self.scan_thread.is_alive():
            if not messagebox.askyesno("Scan running", "Stop scan and close?"):
                return
            self.stop_event.set()
            time.sleep(0.2)
        for m in self.motors.values():
            m.clear_callbacks()
        self._save_persistent_state("close")
        self._log("CLOSED")
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-mode", action="store_true", help="simulate EPICS PVs")
    parser.add_argument("--write-mode", action="store_true", help="enable real EPICS motor writes")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = LaserMirrorScanApp(root, args.safe_mode, args.write_mode)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
