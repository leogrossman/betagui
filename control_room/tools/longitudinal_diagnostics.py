#!/usr/bin/env python3
"""Passive time-series probe for longitudinal and SSMB-related diagnostics.

This tool is meant for short, explicit capture sessions on the control-room
machine. It never writes PVs. By default it samples a small set of scalar
readbacks at a conservative rate and saves:

- raw time-series CSV
- summary JSON
- optional PNG plots if matplotlib is available

The FFT is applied to the sampled monitor outputs themselves. That can reveal
monitor-side modulation or aliasing in the readback, but it is not a substitute
for true raw waveform acquisition.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    from epics import PV

    EPICS_AVAILABLE = True
except Exception:  # pragma: no cover - depends on host packages
    PV = None
    EPICS_AVAILABLE = False

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except Exception:  # pragma: no cover - depends on host packages
    plt = None
    MATPLOTLIB_AVAILABLE = False


REVOLUTION_FREQUENCY_KHZ = 299792458.0 / 48.0 / 1000.0
DEFAULT_CHANNELS = {
    "rf_pv": "MCLKHGP:setFrq",
    "tune_x_raw": "TUNEZRP:measX",
    "tune_y_raw": "TUNEZRP:measY",
    "tune_s_raw": "cumz4x003gp:tuneSyn",
    "cavity_voltage_kv": "PAHRP:setVoltCav",
    "beam_current": "CUM1ZK3RP:measCur",
    "white_noise": "WFGENC1CP:rdVolt",
}
DEFAULT_OUTPUT_ROOT = Path("control_room_outputs") / "longitudinal_diagnostics"


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tune_s_khz_from_raw(raw_value: Optional[float]) -> Optional[float]:
    if raw_value is None:
        return None
    return float(raw_value) / 1000.0


def _unitless_tune_from_khz(freq_khz: Optional[float]) -> Optional[float]:
    if freq_khz is None:
        return None
    return float(freq_khz) / REVOLUTION_FREQUENCY_KHZ


def parse_extra_pvs(items: Iterable[str]) -> Dict[str, str]:
    mapping = {}
    for item in items:
        if "=" not in item:
            raise ValueError("Extra PVs must use label=PVNAME syntax.")
        label, pv_name = item.split("=", 1)
        label = label.strip()
        pv_name = pv_name.strip()
        if not label or not pv_name:
            raise ValueError("Extra PVs must use label=PVNAME syntax.")
        mapping[label] = pv_name
    return mapping


def session_dir(output_root: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = output_root / ("longitudinal_%s_pid%s" % (stamp, os.getpid()))
    path.mkdir(parents=True, exist_ok=False)
    return path


class PVSampler:
    def __init__(self, channel_map: Dict[str, str], timeout: float):
        if not EPICS_AVAILABLE:
            raise RuntimeError("pyepics is unavailable.")
        self.timeout = timeout
        self.channels = dict(channel_map)
        self._pvs = {label: PV(pv_name, connection_timeout=timeout, auto_monitor=False) for label, pv_name in channel_map.items()}

    def sample(self) -> Dict[str, Optional[float]]:
        values = {}
        for label, pv in self._pvs.items():
            values[label] = _safe_float(pv.get(timeout=self.timeout), None)
        return values


def dominant_modulation_frequency(values: Sequence[Optional[float]], sample_hz: float) -> Optional[float]:
    usable = np.array([float(value) for value in values if value is not None], dtype=float)
    if usable.size < 8 or sample_hz <= 0.0:
        return None
    centered = usable - np.mean(usable)
    if np.allclose(centered, 0.0):
        return 0.0
    spectrum = np.fft.rfft(centered)
    frequencies = np.fft.rfftfreq(centered.size, d=1.0 / sample_hz)
    if frequencies.size < 2:
        return None
    amplitudes = np.abs(spectrum)
    amplitudes[0] = 0.0
    peak_index = int(np.argmax(amplitudes))
    return float(frequencies[peak_index])


def correlation(values_a: Sequence[Optional[float]], values_b: Sequence[Optional[float]]) -> Optional[float]:
    pairs = [(float(a), float(b)) for a, b in zip(values_a, values_b) if a is not None and b is not None]
    if len(pairs) < 4:
        return None
    xs = np.array([pair[0] for pair in pairs], dtype=float)
    ys = np.array([pair[1] for pair in pairs], dtype=float)
    if np.std(xs) == 0.0 or np.std(ys) == 0.0:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


def series_stats(values: Sequence[Optional[float]]) -> Dict[str, Optional[float]]:
    usable = np.array([float(value) for value in values if value is not None], dtype=float)
    if usable.size == 0:
        return {"count": 0, "mean": None, "std": None, "min": None, "max": None}
    return {
        "count": int(usable.size),
        "mean": float(np.mean(usable)),
        "std": float(np.std(usable)),
        "min": float(np.min(usable)),
        "max": float(np.max(usable)),
    }


def analyze_samples(rows: List[Dict[str, Optional[float]]], sample_hz: float) -> Dict[str, object]:
    columns: Dict[str, List[Optional[float]]] = {}
    for row in rows:
        for key, value in row.items():
            columns.setdefault(key, []).append(value)

    summary = {"sample_count": len(rows), "sample_hz": sample_hz, "channels": {}}
    for key, values in columns.items():
        channel_summary = series_stats(values)
        if key in ("tune_s_raw", "tune_s_khz", "tune_x_raw", "tune_y_raw", "rf_pv"):
            channel_summary["dominant_modulation_hz"] = dominant_modulation_frequency(values, sample_hz)
        summary["channels"][key] = channel_summary

    summary["correlations"] = {
        "tune_s_raw_vs_rf_pv": correlation(columns.get("tune_s_raw", []), columns.get("rf_pv", [])),
        "tune_s_raw_vs_tune_x_raw": correlation(columns.get("tune_s_raw", []), columns.get("tune_x_raw", [])),
        "tune_s_raw_vs_tune_y_raw": correlation(columns.get("tune_s_raw", []), columns.get("tune_y_raw", [])),
    }
    return summary


def run_capture(
    sampler: PVSampler,
    duration_seconds: float,
    sample_hz: float,
) -> List[Dict[str, Optional[float]]]:
    period = 1.0 / sample_hz
    deadline = time.monotonic() + duration_seconds
    start = time.monotonic()
    rows = []
    sample_index = 0
    while True:
        now = time.monotonic()
        if now > deadline:
            break
        raw = sampler.sample()
        row = {
            "t_rel_s": now - start,
            "sample_index": float(sample_index),
        }
        row.update(raw)
        row["tune_s_khz"] = _tune_s_khz_from_raw(raw.get("tune_s_raw"))
        row["tune_x"] = _unitless_tune_from_khz(raw.get("tune_x_raw"))
        row["tune_y"] = _unitless_tune_from_khz(raw.get("tune_y_raw"))
        row["tune_s"] = _unitless_tune_from_khz(row["tune_s_khz"])
        rows.append(row)
        sample_index += 1
        next_target = start + sample_index * period
        sleep_time = next_target - time.monotonic()
        if sleep_time > 0:
            time.sleep(sleep_time)
    return rows


def write_csv(path: Path, rows: List[Dict[str, Optional[float]]]) -> None:
    fieldnames = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_plots(out_dir: Path, rows: List[Dict[str, Optional[float]]], sample_hz: float) -> List[str]:
    if not MATPLOTLIB_AVAILABLE or not rows:
        return []

    xs = [row["t_rel_s"] for row in rows]
    saved = []

    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for axis, key, label in (
        (axes[0], "tune_s_raw", "tuneSyn raw"),
        (axes[1], "rf_pv", "RF PV"),
        (axes[2], "tune_x_raw", "Tune X raw"),
    ):
        ys = [row.get(key) for row in rows]
        filtered = [(x, y) for x, y in zip(xs, ys) if y is not None]
        if filtered:
            axis.plot([item[0] for item in filtered], [item[1] for item in filtered], linewidth=1.4)
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
    axes[-1].set_xlabel("Time [s]")
    figure.tight_layout()
    time_plot = out_dir / "time_series.png"
    figure.savefig(time_plot, dpi=120)
    plt.close(figure)
    saved.append(str(time_plot))

    values = [row.get("tune_s_raw") for row in rows]
    usable = np.array([float(value) for value in values if value is not None], dtype=float)
    if usable.size >= 8:
        centered = usable - np.mean(usable)
        frequencies = np.fft.rfftfreq(usable.size, d=1.0 / sample_hz)
        amplitudes = np.abs(np.fft.rfft(centered))
        spectrum = plt.figure(figsize=(10, 4))
        axis = spectrum.add_subplot(111)
        axis.plot(frequencies, amplitudes, linewidth=1.4)
        axis.set_xlabel("Modulation frequency [Hz]")
        axis.set_ylabel("Amplitude")
        axis.set_title("FFT of sampled tuneSyn monitor output")
        axis.grid(True, alpha=0.3)
        spectrum.tight_layout()
        spectrum_path = out_dir / "tune_s_fft.png"
        spectrum.savefig(spectrum_path, dpi=120)
        plt.close(spectrum)
        saved.append(str(spectrum_path))
    return saved


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0, help="Capture duration in seconds. Default: 60")
    parser.add_argument("--sample-hz", type=float, default=2.0, help="Sample rate in Hz. Default: 2")
    parser.add_argument("--timeout", type=float, default=0.5, help="PV read timeout in seconds. Default: 0.5")
    parser.add_argument("--output-dir", help="Output root. Default: ./control_room_outputs/longitudinal_diagnostics/")
    parser.add_argument(
        "--pv",
        action="append",
        default=[],
        metavar="LABEL=PVNAME",
        help="Add an extra read-only PV channel to capture.",
    )
    parser.add_argument("--no-plots", action="store_true", help="Skip PNG plot output.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.sample_hz <= 0.0:
        parser.error("--sample-hz must be positive.")
    if args.sample_hz > 10.0:
        parser.error("--sample-hz above 10 Hz is intentionally blocked for this passive tool.")
    if args.duration <= 0.0:
        parser.error("--duration must be positive.")

    channel_map = dict(DEFAULT_CHANNELS)
    channel_map.update(parse_extra_pvs(args.pv))

    out_root = Path(args.output_dir).expanduser().resolve() if args.output_dir else (Path.cwd() / DEFAULT_OUTPUT_ROOT)
    out_dir = session_dir(out_root)

    sampler = PVSampler(channel_map, timeout=args.timeout)
    rows = run_capture(sampler, duration_seconds=args.duration, sample_hz=args.sample_hz)
    summary = analyze_samples(rows, sample_hz=args.sample_hz)
    summary["channel_map"] = channel_map
    summary["duration_seconds"] = args.duration
    summary["timeout_seconds"] = args.timeout

    csv_path = out_dir / "samples.csv"
    write_csv(csv_path, rows)

    summary_path = out_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")

    saved_plots = []
    if not args.no_plots:
        saved_plots = save_plots(out_dir, rows, sample_hz=args.sample_hz)

    print("Longitudinal diagnostics saved to:", out_dir)
    print("Samples:", len(rows))
    print("CSV:    ", csv_path)
    print("Summary:", summary_path)
    if saved_plots:
        print("Plots:")
        for plot_path in saved_plots:
            print(" -", plot_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
