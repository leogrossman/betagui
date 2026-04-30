#!/usr/bin/env python3
"""
SSMB Laser Mirror Angle Scan GUI

Single-file EPICS GUI for the laser-mirror angle scan Carsten described:

    scan the laser interaction angle at the undulator
    while keeping the interaction point / offset fixed using both mirrors.

Default mode is read-only + simulated preview of planned moves.
Real writes require --write-mode.

Examples
--------
Read-only GUI connected to EPICS:
    python3 laser_angle_scan_gui.py

Offline simulation:
    python3 laser_angle_scan_gui.py --safe-mode

Allow real PV.put() motion commands:
    python3 laser_angle_scan_gui.py --write-mode

Known motor PV mapping
----------------------
MNF1C1L2RP -> Mirror 1 vertical
MNF1C2L2RP -> Mirror 1 horizontal
MNF2C1L2RP -> Mirror 2 vertical
MNF2C2L2RP -> Mirror 2 horizontal

These are EPICS motor records with EGU=steps, RTYP=motor, plus RBV/DMOV/MOVN/STOP.

Important assumptions
---------------------
- The legacy mirror geometry/calibration is still valid:
    mirror separation: 2285 mm
    mirror 2 to undulator center: 6010 mm
    horizontal step scale: 2.75 µrad/step
    vertical step scale: 1.89 µrad/step
- Motor PV units are steps.
- The app treats the current motor positions as the current optical reference.
- Target angle scans are implemented as relative changes around that reference.

This file intentionally avoids any .NET/NewFocus CmdLib code.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import queue
import random
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


# =============================================================================
# Defaults
# =============================================================================

MOTOR_PVS = {
    "m1_vertical": "MNF1C1L2RP",
    "m1_horizontal": "MNF1C2L2RP",
    "m2_vertical": "MNF2C1L2RP",
    "m2_horizontal": "MNF2C2L2RP",
}

DEFAULT_P1_PV = ""  # fill in later if known, e.g. "SCOPE1ZULP:h1p1:rdAmpl"


# =============================================================================
# Utility
# =============================================================================

def iso_now() -> str:
    return dt.datetime.now().isoformat(timespec="milliseconds")


def safe_float(x, default=math.nan) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def linspace(center: float, span: float, n: int) -> list[float]:
    n = max(1, int(n))
    if n == 1:
        return [float(center)]
    lo = center - span / 2.0
    hi = center + span / 2.0
    return [lo + i * (hi - lo) / (n - 1) for i in range(n)]


def rectangular_spiral(step_x: float, step_y: float, turns: int) -> list[tuple[float, float]]:
    """Generate a square/rectangular spiral in angle space."""
    x, y = 0.0, 0.0
    coords = [(x, y)]
    directions = [(step_x, 0.0), (0.0, step_y), (-step_x, 0.0), (0.0, -step_y)]
    length = 1
    direction_index = 0
    increases = 0
    for _ in range(max(0, turns)):
        dx, dy = directions[direction_index]
        for _ in range(length):
            x += dx
            y += dy
            coords.append((x, y))
        direction_index = (direction_index + 1) % 4
        increases += 1
        if increases % 2 == 0:
            length += 1
    return coords


# =============================================================================
# EPICS / safe-mode PV abstraction
# =============================================================================

class SimPV:
    def __init__(self, name: str, initial=0):
        self.name = name
        self.value = initial
        self.connected = True
        self.callbacks = []

    def get(self, timeout=None):
        return self.value

    def put(self, value, wait=False, timeout=None):
        self.value = value
        for cb in list(self.callbacks):
            try:
                cb(pvname=self.name, value=value, timestamp=time.time())
            except Exception:
                pass
        return True

    def add_callback(self, cb):
        self.callbacks.append(cb)

    def clear_callbacks(self):
        self.callbacks.clear()


class PVFactory:
    def __init__(self, safe_mode: bool):
        self.safe_mode = safe_mode
        self.cache = {}
        self.PV = None
        if not safe_mode:
            from epics import PV  # type: ignore
            self.PV = PV

    def pv(self, name: str, initial=0):
        if name in self.cache:
            return self.cache[name]
        if self.safe_mode:
            p = SimPV(name, initial=initial)
        else:
            p = self.PV(name, connection_timeout=1.0)
        self.cache[name] = p
        return p


@dataclass
class MotorSnapshot:
    key: str
    base: str
    desc: str
    egu: str
    val: float
    rbv: float
    dmov: int
    movn: int
    stat: str
    sevr: str
    rtyp: str


class EpicsMotor:
    def __init__(self, key: str, base: str, factory: PVFactory):
        self.key = key
        self.base = base
        self.factory = factory

        self.val = factory.pv(base + ".VAL", 0)
        self.rbv = factory.pv(base + ".RBV", 0)
        self.dmov = factory.pv(base + ".DMOV", 1)
        self.movn = factory.pv(base + ".MOVN", 0)
        self.stop_pv = factory.pv(base + ".STOP", 0)
        self.desc = factory.pv(base + ".DESC", key)
        self.egu = factory.pv(base + ".EGU", "steps")
        self.stat = factory.pv(base + ".STAT", "NO_ALARM")
        self.sevr = factory.pv(base + ".SEVR", "NO_ALARM")
        self.rtyp = factory.pv(base + ".RTYP", "motor")

    def snapshot(self) -> MotorSnapshot:
        return MotorSnapshot(
            key=self.key,
            base=self.base,
            desc=str(self.desc.get(timeout=0.3)),
            egu=str(self.egu.get(timeout=0.3)),
            val=safe_float(self.val.get(timeout=0.3)),
            rbv=safe_float(self.rbv.get(timeout=0.3)),
            dmov=int(safe_float(self.dmov.get(timeout=0.3), 0)),
            movn=int(safe_float(self.movn.get(timeout=0.3), 0)),
            stat=str(self.stat.get(timeout=0.3)),
            sevr=str(self.sevr.get(timeout=0.3)),
            rtyp=str(self.rtyp.get(timeout=0.3)),
        )

    def move_absolute(self, target_steps: float):
        self.val.put(float(target_steps), wait=False)
        if self.factory.safe_mode:
            self.movn.put(1)
            self.dmov.put(0)
            self.rbv.put(float(target_steps))
            self.val.put(float(target_steps))
            self.movn.put(0)
            self.dmov.put(1)

    def wait_done(self, timeout_s: float = 20.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                if int(float(self.dmov.get(timeout=0.2))) == 1:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def stop(self):
        self.stop_pv.put(1, wait=False)

    def monitor(self, callback):
        for field, pv in [
            ("VAL", self.val),
            ("RBV", self.rbv),
            ("DMOV", self.dmov),
            ("MOVN", self.movn),
            ("STAT", self.stat),
            ("SEVR", self.sevr),
        ]:
            fullname = self.base + "." + field

            def cb(pvname=None, value=None, timestamp=None, field=field, fullname=fullname, **kwargs):
                callback(self.key, fullname, value)

            try:
                pv.add_callback(cb)
            except Exception as exc:
                callback(self.key, fullname, f"<callback error: {exc}>")

    def clear_callbacks(self):
        for pv in [self.val, self.rbv, self.dmov, self.movn, self.stop_pv, self.stat, self.sevr]:
            try:
                pv.clear_callbacks()
            except Exception:
                pass


class SimulatedP1:
    """Demo P1 response as a Gaussian in angle space."""

    def __init__(self):
        self.center_h = 75.0
        self.center_v = -40.0
        self.width_h = 140.0
        self.width_v = 110.0
        self.noise = 0.02
        self.last_h = 0.0
        self.last_v = 0.0

    def update_angle(self, h_urad: float, v_urad: float):
        self.last_h = h_urad
        self.last_v = v_urad

    def read(self) -> float:
        dh = (self.last_h - self.center_h) / self.width_h
        dv = (self.last_v - self.center_v) / self.width_v
        return max(0.0, math.exp(-(dh * dh + dv * dv)) + random.uniform(-self.noise, self.noise))


# =============================================================================
# Geometry
# =============================================================================

@dataclass
class GeometryConfig:
    mirror_distance_mm: float = 2285.0
    undulator_distance_mm: float = 6010.0
    horizontal_urad_per_step: float = 2.75
    vertical_urad_per_step: float = 1.89
    mirror2_horizontal_sign: float = -1.0
    mirror2_vertical_sign: float = 1.0


@dataclass
class MirrorDeltasSteps:
    m1_horizontal: float
    m1_vertical: float
    m2_horizontal: float
    m2_vertical: float


class BeamGeometry:
    def __init__(self, cfg: GeometryConfig):
        self.cfg = cfg

    def target_to_angles_urad(self, offset_mm: float, angle_urad: float, plane: str) -> tuple[float, float]:
        """
        Legacy transform: desired offset and angle at undulator -> mirror angle pair.

        This returns mirror angular states relative to a zero reference.
        In this app we use it as relative deltas around the current reference.
        """
        md = self.cfg.mirror_distance_mm
        ud = self.cfg.undulator_distance_mm

        offset_angle = -offset_mm / (2.0 * md) * 1e6
        m1_from_angle = angle_urad / 2.0 * ud / md
        m2_from_angle = angle_urad / 2.0 + m1_from_angle

        m1 = m1_from_angle + offset_angle
        m2 = m2_from_angle + offset_angle

        if plane == "horizontal":
            m2 *= self.cfg.mirror2_horizontal_sign
        elif plane == "vertical":
            m2 *= self.cfg.mirror2_vertical_sign
        else:
            raise ValueError(f"unknown plane: {plane}")

        return m1, m2

    def urad_to_steps(self, angle_urad: float, plane: str) -> float:
        scale = self.cfg.horizontal_urad_per_step if plane == "horizontal" else self.cfg.vertical_urad_per_step
        return angle_urad / scale

    def target_to_step_deltas(
        self,
        offset_h_mm: float,
        offset_v_mm: float,
        angle_h_urad: float,
        angle_v_urad: float,
    ) -> MirrorDeltasSteps:
        m1h_urad, m2h_urad = self.target_to_angles_urad(offset_h_mm, angle_h_urad, "horizontal")
        m1v_urad, m2v_urad = self.target_to_angles_urad(offset_v_mm, angle_v_urad, "vertical")

        return MirrorDeltasSteps(
            m1_horizontal=self.urad_to_steps(m1h_urad, "horizontal"),
            m2_horizontal=self.urad_to_steps(m2h_urad, "horizontal"),
            m1_vertical=self.urad_to_steps(m1v_urad, "vertical"),
            m2_vertical=self.urad_to_steps(m2v_urad, "vertical"),
        )


# =============================================================================
# App
# =============================================================================

class LaserAngleScanApp:
    def __init__(self, root: tk.Tk, safe_mode: bool, write_mode: bool):
        self.root = root
        self.safe_mode = safe_mode
        self.write_mode = write_mode
        self.root.title("SSMB Laser Mirror Angle Scan")

        self.log_dir = Path.cwd() / "laser_angle_scan_runs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"laser_angle_scan_{self.session_id}.log"
        self.csv_path = self.log_dir / f"laser_angle_scan_{self.session_id}.csv"
        self.config_path = self.log_dir / f"laser_angle_scan_{self.session_id}_config.json"

        self.events: "queue.Queue[str]" = queue.Queue()
        self.factory = PVFactory(safe_mode=safe_mode)
        self.motors = {key: EpicsMotor(key, base, self.factory) for key, base in MOTOR_PVS.items()}
        self.geometry = BeamGeometry(GeometryConfig())

        self.p1_sim = SimulatedP1()
        self.p1_pv_obj = None

        self.reference_steps = {key: 0.0 for key in MOTOR_PVS}
        self.current_angle_h_urad = 0.0
        self.current_angle_v_urad = 0.0
        self.measurements = []

        self.scan_thread: threading.Thread | None = None
        self.stop_scan_event = threading.Event()

        self._build_ui()
        for motor in self.motors.values():
            motor.monitor(self._monitor_callback)

        self._read_once(log=False)
        self._capture_reference_from_readback(confirm=False)
        self._log(f"START safe_mode={self.safe_mode} write_mode={self.write_mode}")
        self._log(f"log={self.log_path}")
        self._poll()
        self._drain_events()
        self._draw_beam()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        mode = ("SAFE SIMULATION" if self.safe_mode else "REAL EPICS")
        write = ("WRITE ENABLED" if self.write_mode else "READ ONLY")
        ttk.Label(top, text=f"{mode} | {write}", font=("TkDefaultFont", 11, "bold")).pack(side="left")
        ttk.Label(top, text=str(self.log_path), foreground="#555").pack(side="right")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)

        self.overview_tab = ttk.Frame(notebook, padding=8)
        self.scan_tab = ttk.Frame(notebook, padding=8)
        self.plan_tab = ttk.Frame(notebook, padding=8)
        self.log_tab = ttk.Frame(notebook, padding=8)

        notebook.add(self.overview_tab, text="Overview")
        notebook.add(self.scan_tab, text="Angle Scan")
        notebook.add(self.plan_tab, text="Plan / Data")
        notebook.add(self.log_tab, text="Log")

        self._build_overview_tab()
        self._build_scan_tab()
        self._build_plan_tab()
        self._build_log_tab()

    def _build_overview_tab(self):
        left = ttk.Frame(self.overview_tab)
        right = ttk.Frame(self.overview_tab)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.overview_tab.columnconfigure(0, weight=1)
        self.overview_tab.columnconfigure(1, weight=1)
        self.overview_tab.rowconfigure(0, weight=1)

        columns = ["key", "base", "desc", "egu", "val", "rbv", "dmov", "movn", "stat", "sevr"]
        self.motor_tree = ttk.Treeview(left, columns=columns, show="headings", height=8)
        for col in columns:
            self.motor_tree.heading(col, text=col)
            self.motor_tree.column(col, width=105 if col not in ("base", "desc") else 150)
        self.motor_tree.pack(fill="x")
        for key, motor in self.motors.items():
            self.motor_tree.insert("", "end", iid=key, values=[key, motor.base, "", "", "", "", "", "", "", ""])

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Read once", command=lambda: self._read_once(log=True)).pack(side="left")
        ttk.Button(btns, text="Capture current RBV as reference", command=lambda: self._capture_reference_from_readback(confirm=True)).pack(side="left", padx=6)
        ttk.Button(btns, text="STOP all", command=self._stop_all).pack(side="left", padx=6)

        ref_box = ttk.LabelFrame(left, text="Reference motor steps", padding=8)
        ref_box.pack(fill="x", pady=(10, 0))
        self.reference_var = tk.StringVar(value="")
        ttk.Label(ref_box, textvariable=self.reference_var, justify="left").pack(anchor="w")

        p1_box = ttk.LabelFrame(left, text="P1 / signal readback", padding=8)
        p1_box.pack(fill="x", pady=(10, 0))
        self.p1_pv_name_var = tk.StringVar(value=DEFAULT_P1_PV)
        self.p1_live_var = tk.StringVar(value="—")
        ttk.Label(p1_box, text="P1 PV name").grid(row=0, column=0, sticky="w")
        ttk.Entry(p1_box, textvariable=self.p1_pv_name_var, width=45).grid(row=0, column=1, sticky="ew")
        ttk.Button(p1_box, text="Connect P1", command=self._connect_p1).grid(row=0, column=2, padx=4)
        ttk.Label(p1_box, text="Live P1").grid(row=1, column=0, sticky="w")
        ttk.Label(p1_box, textvariable=self.p1_live_var).grid(row=1, column=1, sticky="w")
        p1_box.columnconfigure(1, weight=1)

        self.beam_canvas = tk.Canvas(right, width=520, height=360, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.beam_canvas.pack(fill="both", expand=True)

        self.trace_canvas = tk.Canvas(right, width=520, height=170, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.trace_canvas.pack(fill="x", pady=(10, 0))

    def _build_scan_tab(self):
        controls = ttk.LabelFrame(self.scan_tab, text="Carsten angle scan: scan angle, hold offset fixed", padding=10)
        controls.grid(row=0, column=0, sticky="nsew")
        plotbox = ttk.LabelFrame(self.scan_tab, text="Live map", padding=10)
        plotbox.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.scan_tab.columnconfigure(0, weight=0)
        self.scan_tab.columnconfigure(1, weight=1)
        self.scan_tab.rowconfigure(0, weight=1)

        self.center_h_var = tk.DoubleVar(value=0.0)
        self.center_v_var = tk.DoubleVar(value=0.0)
        self.span_h_var = tk.DoubleVar(value=400.0)
        self.span_v_var = tk.DoubleVar(value=400.0)
        self.points_h_var = tk.IntVar(value=9)
        self.points_v_var = tk.IntVar(value=9)
        self.offset_h_var = tk.DoubleVar(value=0.0)
        self.offset_v_var = tk.DoubleVar(value=0.0)
        self.dwell_var = tk.DoubleVar(value=0.5)
        self.samples_var = tk.IntVar(value=3)
        self.scan_pattern_var = tk.StringVar(value="grid_serpentine")

        rows = [
            ("Center angle horizontal [µrad]", self.center_h_var),
            ("Center angle vertical [µrad]", self.center_v_var),
            ("Span horizontal [µrad]", self.span_h_var),
            ("Span vertical [µrad]", self.span_v_var),
            ("Points horizontal", self.points_h_var),
            ("Points vertical", self.points_v_var),
            ("Held offset horizontal [mm]", self.offset_h_var),
            ("Held offset vertical [mm]", self.offset_v_var),
            ("Dwell [s]", self.dwell_var),
            ("P1 samples / point", self.samples_var),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(controls, text=label).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(controls, textvariable=var, width=18).grid(row=i, column=1, sticky="e", pady=2)

        ttk.Label(controls, text="Pattern").grid(row=len(rows), column=0, sticky="w", pady=2)
        ttk.Combobox(
            controls,
            textvariable=self.scan_pattern_var,
            values=["grid_serpentine", "grid_raster", "spiral"],
            state="readonly",
            width=18,
        ).grid(row=len(rows), column=1, sticky="e", pady=2)

        row = len(rows) + 1
        ttk.Button(controls, text="Preview plan", command=self._preview_plan).grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Start scan", command=self._start_scan).grid(row=row, column=1, sticky="e", pady=(8, 0))
        row += 1
        ttk.Button(controls, text="Stop scan", command=self._request_stop_scan).grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Button(controls, text="Return to reference", command=self._return_to_reference).grid(row=row, column=1, sticky="e", pady=(8, 0))

        self.scan_status_var = tk.StringVar(value="Idle.")
        ttk.Label(controls, textvariable=self.scan_status_var, foreground="#0f766e", wraplength=300).grid(row=row+1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        note = (
            "Read-only mode previews/logs only. Real motion requires --write-mode. "
            "All motor commands are absolute EPICS motor .VAL setpoints in steps, computed relative to the captured reference."
        )
        ttk.Label(controls, text=note, foreground="#555", wraplength=310, justify="left").grid(row=row+2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.map_canvas = tk.Canvas(plotbox, width=620, height=420, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        self.map_canvas.pack(fill="both", expand=True)

    def _build_plan_tab(self):
        self.plan_text = tk.Text(self.plan_tab, height=34, width=120)
        self.plan_text.pack(fill="both", expand=True)
        ttk.Button(self.plan_tab, text="Save current config JSON", command=self._save_config_json).pack(anchor="w", pady=(8, 0))

    def _build_log_tab(self):
        self.log_text = tk.Text(self.log_tab, height=34, width=120)
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ logging

    def _log(self, msg: str):
        line = f"{iso_now()} {msg}"
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        try:
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
        except Exception:
            pass

    def _monitor_callback(self, key: str, pvname: str, value):
        self.events.put(f"MONITOR {key} {pvname}={value}")

    def _drain_events(self):
        try:
            while True:
                self._log(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(250, self._drain_events)

    # ------------------------------------------------------------------ read/update

    def _poll(self):
        self._read_once(log=False)
        self._update_p1_live()
        self._draw_beam()
        self.root.after(500, self._poll)

    def _read_once(self, log=True):
        for key, motor in self.motors.items():
            try:
                snap = motor.snapshot()
                self.motor_tree.item(
                    key,
                    values=[
                        snap.key, snap.base, snap.desc, snap.egu,
                        f"{snap.val:.0f}", f"{snap.rbv:.0f}",
                        snap.dmov, snap.movn, snap.stat, snap.sevr,
                    ],
                )
                if log:
                    self._log(f"READ {snap}")
            except Exception as exc:
                if log:
                    self._log(f"READ_ERROR {key}: {exc}")

    def _connect_p1(self):
        name = self.p1_pv_name_var.get().strip()
        if not name:
            self.p1_pv_obj = None
            self._log("P1 disconnected / using simulated P1")
            return
        try:
            self.p1_pv_obj = self.factory.pv(name, initial=0)
            self._log(f"P1 connected: {name}")
        except Exception as exc:
            self.p1_pv_obj = None
            self._log(f"P1 connect failed: {exc}")

    def _update_p1_live(self):
        try:
            val = self._read_p1()
            self.p1_live_var.set(f"{val:.6g}")
        except Exception:
            self.p1_live_var.set("—")

    def _read_p1(self) -> float:
        if self.p1_pv_obj is not None:
            return safe_float(self.p1_pv_obj.get(timeout=0.5))
        return self.p1_sim.read()

    def _capture_reference_from_readback(self, confirm: bool):
        if confirm:
            if not messagebox.askyesno("Capture reference", "Use current motor RBVs as the zero/reference state for the angle scan?"):
                return
        refs = {}
        for key, motor in self.motors.items():
            snap = motor.snapshot()
            refs[key] = snap.rbv if not math.isnan(snap.rbv) else snap.val
        self.reference_steps = refs
        self._update_reference_label()
        self._log(f"REFERENCE_CAPTURED {self.reference_steps}")

    def _update_reference_label(self):
        text = "\n".join(f"{k}: {v:.0f} steps" for k, v in self.reference_steps.items())
        self.reference_var.set(text)

    # ------------------------------------------------------------------ scan planning

    def _build_angle_points(self) -> list[tuple[int, float, float]]:
        pattern = self.scan_pattern_var.get()
        center_h = self.center_h_var.get()
        center_v = self.center_v_var.get()

        if pattern == "spiral":
            n = max(int(self.points_h_var.get()), int(self.points_v_var.get()), 1)
            step_h = self.span_h_var.get() / max(n - 1, 1)
            step_v = self.span_v_var.get() / max(n - 1, 1)
            coords = rectangular_spiral(step_h, step_v, turns=max(1, n * 2))
            return [(i, center_h + h, center_v + v) for i, (h, v) in enumerate(coords)]

        hs = linspace(center_h, self.span_h_var.get(), self.points_h_var.get())
        vs = linspace(center_v, self.span_v_var.get(), self.points_v_var.get())
        out = []
        idx = 0
        for row, v in enumerate(vs):
            h_iter = list(hs)
            if pattern == "grid_serpentine" and row % 2:
                h_iter.reverse()
            for h in h_iter:
                out.append((idx, h, v))
                idx += 1
        return out

    def _targets_for_angle(self, angle_h_urad: float, angle_v_urad: float) -> dict[str, float]:
        deltas = self.geometry.target_to_step_deltas(
            offset_h_mm=self.offset_h_var.get(),
            offset_v_mm=self.offset_v_var.get(),
            angle_h_urad=angle_h_urad,
            angle_v_urad=angle_v_urad,
        )
        return {
            "m1_horizontal": self.reference_steps["m1_horizontal"] + deltas.m1_horizontal,
            "m2_horizontal": self.reference_steps["m2_horizontal"] + deltas.m2_horizontal,
            "m1_vertical": self.reference_steps["m1_vertical"] + deltas.m1_vertical,
            "m2_vertical": self.reference_steps["m2_vertical"] + deltas.m2_vertical,
        }

    def _preview_plan(self):
        points = self._build_angle_points()
        lines = []
        lines.append("Angle scan preview")
        lines.append(f"write_mode={self.write_mode}, safe_mode={self.safe_mode}")
        lines.append(f"reference_steps={self.reference_steps}")
        lines.append("")
        lines.append("index, angle_h_urad, angle_v_urad, m1h, m1v, m2h, m2v")
        for idx, ah, av in points[:500]:
            t = self._targets_for_angle(ah, av)
            lines.append(
                f"{idx}, {ah:.3f}, {av:.3f}, "
                f"{t['m1_horizontal']:.1f}, {t['m1_vertical']:.1f}, "
                f"{t['m2_horizontal']:.1f}, {t['m2_vertical']:.1f}"
            )
        if len(points) > 500:
            lines.append(f"... truncated, total points={len(points)}")
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("end", "\n".join(lines))
        self._draw_map(preview_points=points, measurements=self.measurements)
        self._log(f"PLAN_PREVIEW points={len(points)}")

    # ------------------------------------------------------------------ motion

    def _require_write(self) -> bool:
        if self.write_mode:
            return True
        messagebox.showwarning("Read-only mode", "Restart with --write-mode for real PV.put() commands.")
        self._log("BLOCKED_WRITE read-only mode")
        return False

    def _put_targets(self, targets: dict[str, float]):
        if not self.write_mode:
            self._log(f"DRY_RUN_TARGETS {targets}")
            return True
        for key, target in targets.items():
            self.motors[key].move_absolute(float(target))
        ok = True
        for key in targets:
            ok = self.motors[key].wait_done(timeout_s=30.0) and ok
        return ok

    def _start_scan(self):
        if not self._require_write():
            self._preview_plan()
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Scan running", "A scan is already running.")
            return
        points = self._build_angle_points()
        if not messagebox.askyesno("Confirm real scan", f"Start real EPICS write scan with {len(points)} points?"):
            return
        self.stop_scan_event.clear()
        self.measurements.clear()
        self._save_config_json()
        self.scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self.scan_thread.start()

    def _request_stop_scan(self):
        self.stop_scan_event.set()
        self._log("SCAN_STOP_REQUESTED")

    def _scan_worker(self):
        points = self._build_angle_points()
        dwell = max(0.0, self.dwell_var.get())
        samples = max(1, int(self.samples_var.get()))
        self._log(f"SCAN_START points={len(points)} csv={self.csv_path}")
        self.root.after(0, lambda: self.scan_status_var.set("Scan running..."))

        try:
            with self.csv_path.open("w", newline="", encoding="utf-8") as f:
                fields = [
                    "timestamp", "index", "angle_h_urad", "angle_v_urad",
                    "target_m1_horizontal", "target_m1_vertical",
                    "target_m2_horizontal", "target_m2_vertical",
                    "rbv_m1_horizontal", "rbv_m1_vertical",
                    "rbv_m2_horizontal", "rbv_m2_vertical",
                    "p1", "samples",
                ]
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()

                for idx, ah, av in points:
                    if self.stop_scan_event.is_set():
                        self._log("SCAN_STOPPED_BY_USER")
                        break

                    targets = self._targets_for_angle(ah, av)
                    self.current_angle_h_urad = ah
                    self.current_angle_v_urad = av
                    self.p1_sim.update_angle(ah, av)

                    self._log(f"SCAN_POINT index={idx} angle_h={ah:.3f} angle_v={av:.3f} targets={targets}")
                    self.root.after(0, lambda idx=idx, ah=ah, av=av: self.scan_status_var.set(f"Point {idx}: H={ah:.2f} µrad, V={av:.2f} µrad"))

                    ok = self._put_targets(targets)
                    if not ok:
                        self._log(f"SCAN_WARN index={idx} not all motors reached DMOV before timeout")

                    time.sleep(dwell)

                    p1_samples = []
                    for _ in range(samples):
                        value = self._read_p1()
                        if value == value:
                            p1_samples.append(value)
                        time.sleep(0.02)
                    p1 = sum(p1_samples) / len(p1_samples) if p1_samples else math.nan

                    snaps = {key: motor.snapshot() for key, motor in self.motors.items()}

                    row = {
                        "timestamp": iso_now(),
                        "index": idx,
                        "angle_h_urad": ah,
                        "angle_v_urad": av,
                        "target_m1_horizontal": targets["m1_horizontal"],
                        "target_m1_vertical": targets["m1_vertical"],
                        "target_m2_horizontal": targets["m2_horizontal"],
                        "target_m2_vertical": targets["m2_vertical"],
                        "rbv_m1_horizontal": snaps["m1_horizontal"].rbv,
                        "rbv_m1_vertical": snaps["m1_vertical"].rbv,
                        "rbv_m2_horizontal": snaps["m2_horizontal"].rbv,
                        "rbv_m2_vertical": snaps["m2_vertical"].rbv,
                        "p1": p1,
                        "samples": len(p1_samples),
                    }
                    writer.writerow(row)
                    f.flush()
                    self.measurements.append(row)
                    self._log(f"SCAN_MEAS index={idx} p1={p1:.6g}")
                    self.root.after(0, lambda: self._draw_map(preview_points=points, measurements=self.measurements))

            self._log("SCAN_FINISHED")
            self.root.after(0, lambda: self.scan_status_var.set(f"Finished. CSV: {self.csv_path}"))
        except Exception as exc:
            self._log(f"SCAN_ERROR {type(exc).__name__}: {exc}")
            self.root.after(0, lambda: self.scan_status_var.set(f"Error: {exc}"))

    def _return_to_reference(self):
        if not self._require_write():
            return
        if not messagebox.askyesno("Return to reference", "Move all four motors back to captured reference steps?"):
            return
        self._log(f"RETURN_REFERENCE {self.reference_steps}")
        self._put_targets(dict(self.reference_steps))

    def _stop_all(self):
        if not self._require_write():
            return
        if not messagebox.askyesno("STOP all", "Write STOP=1 to all four motor records?"):
            return
        for key, motor in self.motors.items():
            try:
                motor.stop()
                self._log(f"STOP {key}")
            except Exception as exc:
                self._log(f"STOP_ERROR {key}: {exc}")

    # ------------------------------------------------------------------ drawing

    def _draw_beam(self):
        c = self.beam_canvas
        c.delete("all")
        w = int(c.winfo_width() or 520)
        h = int(c.winfo_height() or 360)
        mid = h // 2

        # optical line
        c.create_line(40, mid, w - 40, mid, fill="#999", dash=(4, 4))
        x1 = 120
        x2 = 250
        xu = w - 80

        c.create_text(x1, 35, text="M1", font=("TkDefaultFont", 11, "bold"))
        c.create_text(x2, 35, text="M2", font=("TkDefaultFont", 11, "bold"))
        c.create_text(xu, 35, text="Undulator", font=("TkDefaultFont", 11, "bold"))

        # use latest planned angles for schematic tilt
        ah = self.current_angle_h_urad
        av = self.current_angle_v_urad
        tilt1 = max(-25, min(25, ah / 25))
        tilt2 = max(-25, min(25, av / 25))

        c.create_line(x1 - 18, mid - 35 + tilt1, x1 + 18, mid + 35 - tilt1, width=5, fill="#2563eb")
        c.create_line(x2 - 18, mid - 35 + tilt2, x2 + 18, mid + 35 - tilt2, width=5, fill="#059669")
        c.create_oval(xu - 7, mid - 7, xu + 7, mid + 7, fill="#ea580c", outline="")

        # beam schematic
        y0 = mid + max(-60, min(60, av / 5))
        y1 = mid + max(-50, min(50, av / 6))
        y2 = mid + max(-45, min(45, av / 7))
        c.create_line(45, y0, x1, y1, fill="#dc2626", width=2)
        c.create_line(x1, y1, x2, y2, fill="#dc2626", width=2)
        c.create_line(x2, y2, xu, mid, fill="#dc2626", width=2, arrow=tk.LAST)

        c.create_text(20, h - 45, anchor="w", text=f"Angle H: {ah:.2f} µrad")
        c.create_text(20, h - 25, anchor="w", text=f"Angle V: {av:.2f} µrad")

        # trace
        self._draw_trace()

    def _draw_trace(self):
        c = self.trace_canvas
        c.delete("all")
        w = int(c.winfo_width() or 520)
        h = int(c.winfo_height() or 170)
        c.create_text(10, 10, anchor="w", text="P1 trace")
        if not self.measurements:
            c.create_text(w // 2, h // 2, text="No scan data yet", fill="#777")
            return
        vals = [safe_float(m["p1"]) for m in self.measurements if safe_float(m["p1"]) == safe_float(m["p1"])]
        if len(vals) < 2:
            return
        lo, hi = min(vals), max(vals)
        if hi == lo:
            hi = lo + 1
        pts = []
        for i, v in enumerate(vals[-200:]):
            x = 35 + i * (w - 60) / max(1, len(vals[-200:]) - 1)
            y = h - 25 - (v - lo) / (hi - lo) * (h - 55)
            pts.append((x, y))
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            c.create_line(x0, y0, x1, y1, fill="#2563eb", width=2)
        c.create_text(w - 10, 20, anchor="e", text=f"last={vals[-1]:.4g}")

    def _draw_map(self, preview_points=None, measurements=None):
        c = self.map_canvas
        c.delete("all")
        w = int(c.winfo_width() or 620)
        h = int(c.winfo_height() or 420)
        margin = 50
        c.create_text(10, 10, anchor="w", text="P1 vs target angle (horizontal, vertical)")

        points = preview_points or self._build_angle_points()
        if not points:
            return
        hs = [p[1] for p in points]
        vs = [p[2] for p in points]
        hmin, hmax = min(hs), max(hs)
        vmin, vmax = min(vs), max(vs)
        if hmin == hmax:
            hmin -= 1
            hmax += 1
        if vmin == vmax:
            vmin -= 1
            vmax += 1

        def xy(ah, av):
            x = margin + (ah - hmin) / (hmax - hmin) * (w - 2 * margin)
            y = h - margin - (av - vmin) / (vmax - vmin) * (h - 2 * margin)
            return x, y

        # axes
        c.create_rectangle(margin, margin, w - margin, h - margin, outline="#bbb")
        c.create_text(w // 2, h - 15, text="horizontal angle [µrad]")
        c.create_text(15, h // 2, text="vertical", angle=90)

        # preview points
        for idx, ah, av in points:
            x, y = xy(ah, av)
            c.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#ddd", outline="")

        measurements = measurements or []
        vals = [safe_float(m["p1"]) for m in measurements if safe_float(m["p1"]) == safe_float(m["p1"])]
        lo = min(vals) if vals else 0
        hi = max(vals) if vals else 1
        if hi == lo:
            hi = lo + 1

        for m in measurements:
            ah = safe_float(m["angle_h_urad"])
            av = safe_float(m["angle_v_urad"])
            p1 = safe_float(m["p1"])
            if not (ah == ah and av == av and p1 == p1):
                continue
            x, y = xy(ah, av)
            frac = (p1 - lo) / (hi - lo)
            # no fancy colormap: radius encodes signal, color fixed by score bucket
            r = 3 + 8 * frac
            fill = "#ef4444" if frac > 0.7 else "#f59e0b" if frac > 0.4 else "#3b82f6"
            c.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline="")

        if measurements:
            best = max(measurements, key=lambda m: safe_float(m["p1"], -1e99))
            c.create_text(
                margin + 10,
                margin + 15,
                anchor="w",
                text=f"best: H={safe_float(best['angle_h_urad']):.2f}, V={safe_float(best['angle_v_urad']):.2f}, P1={safe_float(best['p1']):.4g}",
                fill="#111",
            )

    # ------------------------------------------------------------------ config/close

    def _save_config_json(self):
        config = {
            "created": iso_now(),
            "safe_mode": self.safe_mode,
            "write_mode": self.write_mode,
            "motor_pvs": MOTOR_PVS,
            "geometry": asdict(self.geometry.cfg),
            "reference_steps": self.reference_steps,
            "scan": {
                "center_h_urad": self.center_h_var.get(),
                "center_v_urad": self.center_v_var.get(),
                "span_h_urad": self.span_h_var.get(),
                "span_v_urad": self.span_v_var.get(),
                "points_h": self.points_h_var.get(),
                "points_v": self.points_v_var.get(),
                "offset_h_mm": self.offset_h_var.get(),
                "offset_v_mm": self.offset_v_var.get(),
                "dwell_s": self.dwell_var.get(),
                "samples": self.samples_var.get(),
                "pattern": self.scan_pattern_var.get(),
                "p1_pv": self.p1_pv_name_var.get(),
            },
        }
        self.config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
        self._log(f"CONFIG_SAVED {self.config_path}")

    def close(self):
        if self.scan_thread and self.scan_thread.is_alive():
            if not messagebox.askyesno("Scan running", "A scan is running. Stop and close?"):
                return
            self.stop_scan_event.set()
            time.sleep(0.2)
        for motor in self.motors.values():
            motor.clear_callbacks()
        self._log("CLOSED")
        self.root.destroy()


# =============================================================================
# Main
# =============================================================================

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SSMB laser mirror angle scan GUI")
    p.add_argument("--safe-mode", action="store_true", help="simulate PVs, no EPICS required")
    p.add_argument("--write-mode", action="store_true", help="enable real EPICS PV.put() motor writes")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = tk.Tk()
    app = LaserAngleScanApp(root, safe_mode=args.safe_mode, write_mode=args.write_mode)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
