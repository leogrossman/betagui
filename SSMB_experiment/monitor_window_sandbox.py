#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import time

from SSMB_experiment.ssmb_tool.gui import SSMBGui, tk
from SSMB_experiment.ssmb_tool.live_monitor import format_channel_snapshot, format_monitor_summary, summarize_live_monitor


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic live-monitor sandbox for local GUI debugging.")
    parser.add_argument("--rate", type=float, default=2.0, help="Synthetic sample rate in Hz.")
    parser.add_argument("--history-span", type=float, default=600.0, help="Synthetic retained history span in seconds.")
    parser.add_argument("--open-monitor", action="store_true", help="Open the live monitor window on startup.")
    return parser


def _synthetic_sample(index: int, t_s: float) -> dict:
    slow_phase = 2.0 * math.pi * t_s / 300.0
    fast_phase = 2.0 * math.pi * t_s / 40.0
    rf_readback = 499688.387 + 2.5e-4 * math.sin(0.35 * fast_phase)
    delta_s = 1.5e-4 * math.sin(fast_phase)
    p1 = 0.06 + 0.01 * math.sin(fast_phase) + 0.003 * math.sin(2.0 * fast_phase + 0.4) + 0.0015 * math.sin(slow_phase)
    p3 = 0.02 + 0.004 * math.sin(fast_phase + 1.2)
    temp = 29.4 + 0.2 * math.sin(slow_phase)
    return {
        "timestamp_epoch_s": time.time(),
        "sample_index": index,
        "channels": {
            "beam_current": {"value": 4.2, "pv": "CUM1ZK3RP:measCur"},
            "rf_readback_499mhz": {"value": 685.685 + 0.004 * math.sin(fast_phase), "pv": "MCLKHGP:rdFrq499"},
            "p1_h1_ampl": {"value": p1 - 0.004, "pv": "SCOPE1ZULP:h1p1:rdAmpl"},
            "p1_h1_ampl_avg": {"value": p1, "pv": "SCOPE1ZULP:h1p1:rdAmplAv"},
            "p1_h1_ampl_dev": {"value": 0.0012 + 0.0002 * abs(math.sin(slow_phase)), "pv": "SCOPE1ZULP:h1p1:rdAmplDev"},
            "p3_h1_ampl": {"value": p3 - 0.001, "pv": "SCOPE1ZULP:h1p3:rdAmpl"},
            "p3_h1_ampl_avg": {"value": p3, "pv": "SCOPE1ZULP:h1p3:rdAmplAv"},
            "qpd_l4_center_x_avg_um": {"value": 470.0 + 20.0 * math.sin(fast_phase + 0.7), "pv": "QPD00ZL4RP:rdCenterXav"},
            "climate_kw13_return_temp_c": {"value": temp, "pv": "KLIMAC1CP:coolKW13:rdRetTemp"},
            "l4_bump_hcorr_k3_upstream": {"value": 0.012 * math.sin(slow_phase), "pv": "HS1P2K3RP:setCur"},
            "l4_bump_hcorr_l4_upstream": {"value": 0.006 * math.sin(slow_phase + 0.5), "pv": "HS3P1L4RP:setCur"},
            "l4_bump_hcorr_l4_downstream": {"value": 0.006 * math.sin(slow_phase + 0.7), "pv": "HS3P2L4RP:setCur"},
            "l4_bump_hcorr_k1_downstream": {"value": 0.011 * math.sin(slow_phase + 0.1), "pv": "HS1P1K1RP:setCur"},
            "l4_bump_feedback_enable": {"value": 1.0, "pv": "AKC10VP"},
            "l4_bump_orbit_bpm_k1": {"value": -0.6 + 0.1 * math.sin(slow_phase), "pv": "BPMZ1K1RP:rdX"},
            "l4_bump_orbit_bpm_l2": {"value": -0.5 + 0.1 * math.sin(slow_phase + 0.2), "pv": "BPMZ1L2RP:rdX"},
            "l4_bump_orbit_bpm_k3": {"value": -0.4 + 0.1 * math.sin(slow_phase + 0.4), "pv": "BPMZ1K3RP:rdX"},
            "l4_bump_orbit_bpm_l4": {"value": -0.3 + 0.1 * math.sin(slow_phase + 0.6), "pv": "BPMZ1L4RP:rdX"},
        },
        "derived": {
            "rf_readback": rf_readback,
            "rf_offset_hz": (rf_readback - 499688.387) * 1.0e3,
            "delta_l4_bpm_first_order": delta_s,
            "beam_energy_from_bpm_mev": 250.0 * (1.0 + delta_s),
            "qpd_l4_sigma_delta_first_order": 2.0e-4 + 1.0e-5 * math.sin(slow_phase),
            "qpd_l4_sigma_energy_mev": 0.05,
            "legacy_alpha0_corrected": 6.3e-4,
            "tune_y_unitless": 0.12 + 1.0e-4 * math.sin(fast_phase),
            "tune_s_unitless": 0.013 + 2.0e-4 * math.sin(fast_phase + 0.2),
            "tune_s_khz": 19.5,
            "qpd_l4_sigma_x_mm": 0.6 + 0.02 * math.sin(slow_phase),
            "qpd_l4_sigma_y_mm": 0.2 + 0.01 * math.sin(slow_phase + 0.4),
            "bpm_x_nonlinear_labels": [],
        },
    }


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if tk is None:
        raise SystemExit("tkinter unavailable")
    root = tk.Tk()
    app = SSMBGui(root, allow_writes=False, start_safe_mode=True)
    app.monitor_interval_var.set(str(max(0.1, args.rate and 1.0 / args.rate)))
    app.monitor_history_span_var.set(str(max(60.0, args.history_span)))
    if args.open_monitor:
        app._open_monitor_window()

    started = time.monotonic()

    def tick() -> None:
        if not root.winfo_exists():
            return
        t_s = time.monotonic() - started
        sample = _synthetic_sample(len(app.monitor_history), t_s)
        app.monitor_history.append(sample)
        max_samples = max(10, app._window_samples_for_seconds(args.history_span))
        if len(app.monitor_history) > max_samples:
            del app.monitor_history[:-max_samples]
        summary = summarize_live_monitor(
            app.monitor_history,
            extra_candidate_keys=app._extra_oscillation_candidates(),
            include_oscillation=bool(app.oscillation_window is not None and app.oscillation_window.winfo_exists()),
            include_extended=bool(app.oscillation_window is not None and app.oscillation_window.winfo_exists()),
        )
        app._update_live_monitor(
            {
                "summary_lines": format_monitor_summary(summary),
                "channel_lines": format_channel_snapshot(sample, {}),
                "sample": sample,
                "summary": summary,
            }
        )
        root.after(max(20, int(1000.0 / max(0.1, args.rate))), tick)

    root.after(100, tick)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
