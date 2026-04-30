#!/usr/bin/env python3
from __future__ import annotations

"""Offline digital twin for the SSMB laser-mirror steering setup.

This script is intentionally laptop-friendly:

- no EPICS required
- no control-room network required
- uses the same geometry and scan planning code as the real GUI

It can either:

1. generate an offline CSV/JSON scan package, or
2. open a small Tk visualization that animates the PoP II steering layout and
   the resulting synthetic signal map.
"""

import argparse
import csv
import json
from pathlib import Path

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.hardware import PVFactory, build_signal_backend
from laser_mirrors_app.layout import default_optics_layout
from laser_mirrors_app.scan import ScanContext, ScanRunner, build_angle_scan_points
from laser_mirrors_app.hardware import MirrorController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline SSMB laser optics digital twin")
    parser.add_argument("--config", default="laser_mirrors_config.json")
    parser.add_argument("--mode", default="both_2d", choices=["both_2d", "horizontal_only", "vertical_only"])
    parser.add_argument("--span-x", type=float, default=50.0)
    parser.add_argument("--span-y", type=float, default=50.0)
    parser.add_argument("--points-x", type=int, default=7)
    parser.add_argument("--points-y", type=int, default=7)
    parser.add_argument("--animate", action="store_true", help="Open a Tk animation instead of only writing files")
    parser.add_argument("--output-root", default="laser_mirror_digital_twin_runs")
    return parser


def run_offline_scan(config: AppConfig, output_root: Path) -> tuple[list[dict[str, float]], Path]:
    geometry = LaserMirrorGeometry(config.geometry)
    factory = PVFactory(True)
    controller = MirrorController(config.controller, factory)
    signal = build_signal_backend(True, "p1_h1_avg", None, factory)
    runner = ScanRunner(config, geometry, controller, signal, lambda _msg: None, output_root)
    rows: list[dict[str, float]] = []
    context = ScanContext(reference_steps=controller.capture_reference(), signal_label="Simulated P1", signal_pv="simulated")
    runner.start("angle", context, on_measurement=lambda row: rows.append(row.__dict__.copy()), on_finish=lambda path, best: None)
    runner.join(timeout=15.0)
    assert runner.session_dir is not None
    return rows, runner.session_dir


class TwinViewer:
    def __init__(self, rows: list[dict[str, float]], config: AppConfig):
        import tkinter as tk

        self.tk = tk
        self.rows = rows
        self.geometry = LaserMirrorGeometry(config.geometry)
        self.layout = default_optics_layout()
        self.index = 0
        self.root = tk.Tk()
        self.root.title("Laser optics digital twin")
        self.info = tk.StringVar(value="Starting animation...")
        tk.Label(self.root, textvariable=self.info, anchor="w").pack(fill="x")
        self.geometry_canvas = tk.Canvas(self.root, width=880, height=340, bg="white")
        self.geometry_canvas.pack(fill="both", expand=True)
        self.map_canvas = tk.Canvas(self.root, width=880, height=340, bg="white")
        self.map_canvas.pack(fill="both", expand=True)
        self.root.after(120, self._tick)

    def _draw_layout(self, row: dict[str, float]) -> None:
        canvas = self.geometry_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        top_y = h * 0.38
        bottom_y = h * 0.74
        xs = [item.x_mm for item in self.layout]
        x_min = min(xs)
        x_span = max(max(xs) - x_min, 1.0)

        def map_x(x_mm: float) -> float:
            return 24 + (x_mm - x_min) / x_span * (w - 48)

        for lane_y, color, angle, offset in (
            (top_y, "#2563eb", row["angle_x_urad"], row["offset_x_mm"]),
            (bottom_y, "#16a34a", row["angle_y_urad"], row["offset_y_mm"]),
        ):
            canvas.create_line(20, lane_y, w - 20, lane_y, fill="#cbd5e1", dash=(4, 4))
            poly = self.geometry.ray_polyline(angle, offset)
            y_abs = max(max(abs(value) for _, value in poly), 1.0)
            prev = None
            for x_mm, y_mm in poly:
                px = map_x(x_mm)
                py = lane_y - (y_mm / y_abs) * 44
                if prev is not None:
                    canvas.create_line(prev[0], prev[1], px, py, fill=color, width=2)
                prev = (px, py)
        for item in self.layout:
            px = map_x(item.x_mm)
            canvas.create_text(px, 18, text=item.label, font=("Helvetica", 8))
            canvas.create_rectangle(px - 4, top_y - 12, px + 4, top_y + 12, fill="#475569", outline="")
            canvas.create_rectangle(px - 4, bottom_y - 12, px + 4, bottom_y + 12, fill="#475569", outline="")

    def _draw_map(self) -> None:
        canvas = self.map_canvas
        canvas.delete("all")
        w = int(canvas["width"])
        h = int(canvas["height"])
        margin = 48
        canvas.create_rectangle(margin, margin, w - margin, h - margin, outline="#999999")
        if not self.rows:
            return
        xs = [row["angle_x_urad"] for row in self.rows]
        ys = [row["angle_y_urad"] for row in self.rows]
        values = [row["signal_average"] for row in self.rows]
        x_span = max(max(xs) - min(xs), 1e-6)
        y_span = max(max(ys) - min(ys), 1e-6)
        v_span = max(max(values) - min(values), 1e-9)
        for idx, row in enumerate(self.rows):
            px = margin + (row["angle_x_urad"] - min(xs)) / x_span * (w - 2 * margin)
            py = h - margin - (row["angle_y_urad"] - min(ys)) / y_span * (h - 2 * margin)
            norm = (row["signal_average"] - min(values)) / v_span
            color = f"#{int(255*norm):02x}{int(140*(1-norm)+60*norm):02x}{int(255*(1-norm)):02x}"
            radius = 5 if idx == self.index else 3
            canvas.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="")
        canvas.create_text(w // 2, 18, text="Synthetic P1 map", font=("Helvetica", 10, "bold"))

    def _tick(self) -> None:
        if not self.rows:
            return
        row = self.rows[min(self.index, len(self.rows) - 1)]
        self.info.set(
            f"Point {self.index + 1}/{len(self.rows)} | ax={row['angle_x_urad']:.2f} µrad | "
            f"ay={row['angle_y_urad']:.2f} µrad | signal={row['signal_average']:.6g}"
        )
        self._draw_layout(row)
        self._draw_map()
        self.index += 1
        if self.index < len(self.rows):
            self.root.after(180, self._tick)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    args = build_parser().parse_args()
    config = AppConfig.load(Path(args.config))
    config.controller.safe_mode = True
    config.controller.write_mode = False
    config.scan.mode = args.mode
    config.scan.span_angle_x_urad = args.span_x
    config.scan.span_angle_y_urad = args.span_y
    config.scan.points_x = args.points_x
    config.scan.points_y = args.points_y
    config.scan.dwell_s = 0.0
    config.scan.p1_samples_per_point = 1
    config.controller.inter_put_delay_s = 0.0
    config.controller.settle_s = 0.0
    config.controller.max_step_per_put = 1000.0
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    rows, session_dir = run_offline_scan(config, output_root)
    summary = {
        "row_count": len(rows),
        "session_dir": str(session_dir),
        "config": {
            "mode": config.scan.mode,
            "span_x_urad": config.scan.span_angle_x_urad,
            "span_y_urad": config.scan.span_angle_y_urad,
            "points_x": config.scan.points_x,
            "points_y": config.scan.points_y,
        },
    }
    (session_dir / "digital_twin_summary.json").write_text(json.dumps(summary, indent=2))
    if args.animate:
        TwinViewer(rows, config).run()
    else:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
