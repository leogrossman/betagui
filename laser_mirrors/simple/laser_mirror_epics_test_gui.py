#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

DEFAULT_MOTORS = {
    "m1_vertical": "MNF1C1L2RP",
    "m1_horizontal": "MNF1C2L2RP",
    "m2_vertical": "MNF2C1L2RP",
    "m2_horizontal": "MNF2C2L2RP",
}

FIELDS = ["VAL", "RBV", "DMOV", "MOVN", "STOP", "DESC", "EGU", "STAT", "SEVR", "RTYP", "PREC"]
POLL_MS = 500


def now():
    return dt.datetime.now().isoformat(timespec="milliseconds")


def safe_float(x, default=math.nan):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


class SimPV:
    def __init__(self, name, initial=0):
        self.name = name
        self.value = initial
        self.callbacks = []
        self.connected = True

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

    def add_callback(self, callback):
        self.callbacks.append(callback)

    def clear_callbacks(self):
        self.callbacks.clear()


class PVFactory:
    def __init__(self, safe_mode):
        self.safe_mode = safe_mode
        self.cache = {}
        self.PV = None
        if not safe_mode:
            from epics import PV  # type: ignore
            self.PV = PV

    def pv(self, name, initial=0):
        if name in self.cache:
            return self.cache[name]
        if self.safe_mode:
            p = SimPV(name, initial)
        else:
            p = self.PV(name, connection_timeout=1.0)
        self.cache[name] = p
        return p


@dataclass
class Snapshot:
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


class Motor:
    def __init__(self, key, base, factory):
        self.key = key
        self.base = base
        self.factory = factory
        self.pvs = {}
        for f in FIELDS:
            self.pvs[f] = factory.pv(base + "." + f, self._initial(f))

    def _initial(self, f):
        if f == "DESC":
            return self.key
        if f == "EGU":
            return "steps"
        if f == "RTYP":
            return "motor"
        if f == "DMOV":
            return 1
        if f in ("MOVN", "STOP"):
            return 0
        if f in ("STAT", "SEVR"):
            return "NO_ALARM"
        return 0

    def get(self, field, timeout=0.35):
        return self.pvs[field].get(timeout=timeout)

    def snapshot(self):
        return Snapshot(
            key=self.key,
            base=self.base,
            desc=str(self.get("DESC")),
            egu=str(self.get("EGU")),
            val=safe_float(self.get("VAL")),
            rbv=safe_float(self.get("RBV")),
            dmov=int(safe_float(self.get("DMOV"), 0)),
            movn=int(safe_float(self.get("MOVN"), 0)),
            stat=str(self.get("STAT")),
            sevr=str(self.get("SEVR")),
            rtyp=str(self.get("RTYP")),
        )

    def move(self, value):
        self.pvs["VAL"].put(value, wait=False)
        if self.factory.safe_mode:
            self.pvs["MOVN"].put(1)
            self.pvs["DMOV"].put(0)
            self.pvs["RBV"].put(value)
            self.pvs["VAL"].put(value)
            self.pvs["MOVN"].put(0)
            self.pvs["DMOV"].put(1)

    def wait_done(self, timeout=15.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if int(float(self.get("DMOV", timeout=0.2))) == 1:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def stop(self):
        self.pvs["STOP"].put(1, wait=False)

    def monitor(self, callback):
        for f in ["VAL", "RBV", "DMOV", "MOVN", "STAT", "SEVR"]:
            name = self.base + "." + f

            def cb(pvname=None, value=None, timestamp=None, field=f, full=name, **kwargs):
                callback(self.key, full, value)

            try:
                self.pvs[f].add_callback(cb)
            except Exception as e:
                callback(self.key, name, "<callback error: %s>" % e)

    def clear(self):
        for p in self.pvs.values():
            try:
                p.clear_callbacks()
            except Exception:
                pass


class App:
    def __init__(self, root, safe_mode=False, write_mode=False):
        self.root = root
        self.safe_mode = safe_mode
        self.write_mode = write_mode
        self.root.title("SSMB mirror EPICS read/test GUI")

        self.log_dir = Path.cwd() / "mirror_epics_logs"
        self.log_dir.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / ("mirror_epics_gui_%s.log" % stamp)
        self.csv_path = self.log_dir / ("mirror_epics_scan_%s.csv" % stamp)

        self.events = queue.Queue()
        self.factory = PVFactory(safe_mode)
        self.motors = {k: Motor(k, b, self.factory) for k, b in DEFAULT_MOTORS.items()}
        self.stop_scan = threading.Event()
        self.scan_thread = None

        self._build_ui()
        for m in self.motors.values():
            m.monitor(self._monitor_cb)

        self.log("START safe_mode=%s write_mode=%s" % (self.safe_mode, self.write_mode))
        self.log("log=%s" % self.log_path)
        self._poll()
        self._drain()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(
            top,
            text=("SAFE SIM" if self.safe_mode else "REAL EPICS") + " | " + ("WRITE ENABLED" if self.write_mode else "READ ONLY"),
            font=("TkDefaultFont", 11, "bold"),
        ).pack(side="left")
        ttk.Label(top, text=str(self.log_path)).pack(side="right")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.read_tab = ttk.Frame(nb, padding=8)
        self.test_tab = ttk.Frame(nb, padding=8)
        self.scan_tab = ttk.Frame(nb, padding=8)
        self.log_tab = ttk.Frame(nb, padding=8)
        nb.add(self.read_tab, text="Read / Monitor")
        nb.add(self.test_tab, text="Put test")
        nb.add(self.scan_tab, text="Step scan")
        nb.add(self.log_tab, text="Log")

        self._build_read()
        self._build_test()
        self._build_scan()
        self._build_log()

    def _build_read(self):
        cols = ["key", "base", "desc", "egu", "val", "rbv", "dmov", "movn", "stat", "sevr", "rtyp"]
        self.tree = ttk.Treeview(self.read_tab, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=125 if c not in ("desc", "base") else 170)
        self.tree.pack(fill="both", expand=True)
        for k, m in self.motors.items():
            self.tree.insert("", "end", iid=k, values=[k, m.base, "", "", "", "", "", "", "", "", ""])

        row = ttk.Frame(self.read_tab)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Read once", command=lambda: self.read_once(True)).pack(side="left")
        ttk.Button(row, text="STOP all", command=self.stop_all).pack(side="left", padx=6)

    def _build_test(self):
        box = ttk.LabelFrame(self.test_tab, text="Small relative put test", padding=10)
        box.pack(fill="x")
        self.test_motor = tk.StringVar(value="m2_horizontal")
        self.test_delta = tk.DoubleVar(value=1.0)

        ttk.Label(box, text="Motor").grid(row=0, column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.test_motor, values=list(self.motors.keys()), state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Delta [steps]").grid(row=1, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.test_delta, width=12).grid(row=1, column=1, sticky="w")

        ttk.Button(box, text="Read selected", command=self.read_selected).grid(row=2, column=0, pady=8)
        ttk.Button(box, text="PUT +delta", command=lambda: self.put_delta(+1)).grid(row=2, column=1, pady=8)
        ttk.Button(box, text="PUT -delta", command=lambda: self.put_delta(-1)).grid(row=2, column=2, pady=8)

        ttk.Label(
            self.test_tab,
            text="Writes only work with --write-mode. Use tiny deltas first, e.g. 1 step.",
            foreground="#555",
        ).pack(anchor="w", pady=10)

    def _build_scan(self):
        box = ttk.LabelFrame(self.scan_tab, text="Simple step scan", padding=10)
        box.pack(fill="x")

        self.center_h = tk.DoubleVar(value=0.0)
        self.center_v = tk.DoubleVar(value=0.0)
        self.span_h = tk.DoubleVar(value=20.0)
        self.span_v = tk.DoubleVar(value=20.0)
        self.points_h = tk.IntVar(value=5)
        self.points_v = tk.IntVar(value=5)
        self.dwell = tk.DoubleVar(value=1.0)
        self.scan_mode = tk.StringVar(value="mirror2_only")
        self.p1_pv = tk.StringVar(value="")

        rows = [
            ("Center horizontal [steps]", self.center_h),
            ("Center vertical [steps]", self.center_v),
            ("Span horizontal [steps]", self.span_h),
            ("Span vertical [steps]", self.span_v),
            ("Points horizontal", self.points_h),
            ("Points vertical", self.points_v),
            ("Dwell [s]", self.dwell),
            ("Optional P1 PV", self.p1_pv),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(box, textvariable=var, width=25).grid(row=i, column=1, sticky="w")

        ttk.Label(box, text="Mode").grid(row=len(rows), column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.scan_mode, values=["mirror2_only", "mirror1_only", "both_same_delta"], state="readonly").grid(row=len(rows), column=1, sticky="w")

        row = ttk.Frame(self.scan_tab)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Start scan", command=self.start_scan).pack(side="left")
        ttk.Button(row, text="Stop scan", command=lambda: self.stop_scan.set()).pack(side="left", padx=6)

        self.scan_status = tk.StringVar(value="Idle.")
        ttk.Label(self.scan_tab, textvariable=self.scan_status, foreground="#0f766e").pack(anchor="w")
        ttk.Label(
            self.scan_tab,
            text="This is intentionally step-based for control-room testing. Final physics code can map offset/angle to these four motor setpoints.",
            foreground="#555",
            wraplength=700,
        ).pack(anchor="w", pady=8)

    def _build_log(self):
        self.log_text = tk.Text(self.log_tab, width=120, height=32)
        self.log_text.pack(fill="both", expand=True)

    def log(self, msg):
        line = "%s %s" % (now(), msg)
        try:
            with self.log_path.open("a") as f:
                f.write(line + "\n")
        except Exception:
            pass
        try:
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
        except Exception:
            pass

    def _monitor_cb(self, key, pvname, value):
        self.events.put("MONITOR %s %s = %s" % (key, pvname, value))

    def _drain(self):
        try:
            while True:
                self.log(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(200, self._drain)

    def _poll(self):
        self.read_once(False)
        self.root.after(POLL_MS, self._poll)

    def read_once(self, logit=True):
        for k, m in self.motors.items():
            try:
                s = m.snapshot()
                vals = [s.key, s.base, s.desc, s.egu, self.fmt(s.val), self.fmt(s.rbv), s.dmov, s.movn, s.stat, s.sevr, s.rtyp]
                self.tree.item(k, values=vals)
                if logit:
                    self.log("READ %s" % (s,))
            except Exception as e:
                if logit:
                    self.log("READ_ERROR %s %s" % (k, e))

    def fmt(self, x):
        try:
            return "%.3f" % float(x)
        except Exception:
            return str(x)

    def require_write(self):
        if self.write_mode:
            return True
        messagebox.showwarning("Read-only", "Restart with --write-mode to enable PV.put().")
        self.log("BLOCKED_WRITE read-only mode")
        return False

    def read_selected(self):
        k = self.test_motor.get()
        self.log("SELECTED %s" % (self.motors[k].snapshot(),))

    def put_delta(self, sign):
        if not self.require_write():
            return
        k = self.test_motor.get()
        m = self.motors[k]
        s = m.snapshot()
        target = s.val + sign * float(self.test_delta.get())
        if not messagebox.askyesno("Confirm PUT", "Move %s\n%s.VAL\n%.3f -> %.3f steps?" % (k, m.base, s.val, target)):
            return
        self.log("PUT_TEST %s target=%.3f" % (k, target))
        m.move(target)
        ok = m.wait_done(15.0)
        self.log("PUT_TEST_DONE %s ok=%s rbv=%s" % (k, ok, self.fmt(m.snapshot().rbv)))

    def stop_all(self):
        if not self.require_write():
            return
        if not messagebox.askyesno("Confirm STOP", "Write STOP=1 to all four motors?"):
            return
        for k, m in self.motors.items():
            try:
                m.stop()
                self.log("STOP %s" % k)
            except Exception as e:
                self.log("STOP_ERROR %s %s" % (k, e))

    def linspace(self, center, span, n):
        n = max(1, int(n))
        if n == 1:
            return [float(center)]
        lo = center - span / 2.0
        hi = center + span / 2.0
        return [lo + i * (hi - lo) / (n - 1) for i in range(n)]

    def start_scan(self):
        if not self.require_write():
            return
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("Scan running", "Scan already running.")
            return
        if not messagebox.askyesno("Confirm scan", "Start real EPICS write scan?"):
            return
        self.stop_scan.clear()
        self.scan_thread = threading.Thread(target=self.scan_worker, daemon=True)
        self.scan_thread.start()

    def scan_worker(self):
        try:
            hs = self.linspace(self.center_h.get(), self.span_h.get(), self.points_h.get())
            vs = self.linspace(self.center_v.get(), self.span_v.get(), self.points_v.get())
            mode = self.scan_mode.get()
            dwell = max(0.0, float(self.dwell.get()))
            initial = {k: m.snapshot().val for k, m in self.motors.items()}
            p1 = self.factory.pv(self.p1_pv.get().strip()) if self.p1_pv.get().strip() else None
            self.log("SCAN_START mode=%s initial=%s csv=%s" % (mode, initial, self.csv_path))

            with self.csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "timestamp", "index", "mode", "h", "v",
                    "m1_horizontal_val", "m1_vertical_val", "m2_horizontal_val", "m2_vertical_val",
                    "m1_horizontal_rbv", "m1_vertical_rbv", "m2_horizontal_rbv", "m2_vertical_rbv",
                    "p1",
                ])
                writer.writeheader()

                idx = 0
                for row, v in enumerate(vs):
                    h_iter = list(hs)
                    if row % 2:
                        h_iter.reverse()
                    for h in h_iter:
                        if self.stop_scan.is_set():
                            self.log("SCAN_STOPPED")
                            self.root.after(0, lambda: self.scan_status.set("Stopped."))
                            return

                        targets = dict(initial)
                        if mode == "mirror2_only":
                            targets["m2_horizontal"] = h
                            targets["m2_vertical"] = v
                        elif mode == "mirror1_only":
                            targets["m1_horizontal"] = h
                            targets["m1_vertical"] = v
                        else:
                            targets["m1_horizontal"] = initial["m1_horizontal"] + h
                            targets["m2_horizontal"] = initial["m2_horizontal"] + h
                            targets["m1_vertical"] = initial["m1_vertical"] + v
                            targets["m2_vertical"] = initial["m2_vertical"] + v

                        self.root.after(0, lambda idx=idx, h=h, v=v: self.scan_status.set("Moving point %d h=%.3f v=%.3f" % (idx, h, v)))
                        self.log("SCAN_POINT %d targets=%s" % (idx, targets))

                        for k, target in targets.items():
                            self.motors[k].move(float(target))
                        ok = all(self.motors[k].wait_done(20.0) for k in targets)
                        if not ok:
                            self.log("SCAN_WARN point=%d timeout waiting DMOV" % idx)

                        time.sleep(dwell)
                        snaps = {k: m.snapshot() for k, m in self.motors.items()}
                        p1_val = ""
                        if p1 is not None:
                            try:
                                p1_val = p1.get(timeout=1.0)
                            except Exception as e:
                                p1_val = "<ERR %s>" % e

                        writer.writerow({
                            "timestamp": now(),
                            "index": idx,
                            "mode": mode,
                            "h": h,
                            "v": v,
                            "m1_horizontal_val": snaps["m1_horizontal"].val,
                            "m1_vertical_val": snaps["m1_vertical"].val,
                            "m2_horizontal_val": snaps["m2_horizontal"].val,
                            "m2_vertical_val": snaps["m2_vertical"].val,
                            "m1_horizontal_rbv": snaps["m1_horizontal"].rbv,
                            "m1_vertical_rbv": snaps["m1_vertical"].rbv,
                            "m2_horizontal_rbv": snaps["m2_horizontal"].rbv,
                            "m2_vertical_rbv": snaps["m2_vertical"].rbv,
                            "p1": p1_val,
                        })
                        f.flush()
                        self.log("SCAN_MEAS %d p1=%s" % (idx, p1_val))
                        idx += 1

            self.log("SCAN_FINISHED")
            self.root.after(0, lambda: self.scan_status.set("Finished. CSV: %s" % self.csv_path))
        except Exception as e:
            self.log("SCAN_ERROR %s" % e)
            self.root.after(0, lambda: self.scan_status.set("Error: %s" % e))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--safe-mode", action="store_true", help="simulate PVs; no EPICS")
    parser.add_argument("--write-mode", action="store_true", help="enable caput/PV.put actions")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = App(root, safe_mode=args.safe_mode, write_mode=args.write_mode)

    def close():
        if app.scan_thread and app.scan_thread.is_alive():
            app.stop_scan.set()
            time.sleep(0.2)
        for m in app.motors.values():
            m.clear()
        app.log("CLOSED")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    main()
