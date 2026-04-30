#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from SSMB_experiment.monitor_window_sandbox import _synthetic_sample  # noqa: E402
from SSMB_experiment.ssmb_tool.live_monitor import summarize_live_monitor  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile pure live-monitor summary/render prep without EPICS.")
    parser.add_argument("--samples", type=int, default=1200, help="Number of synthetic samples.")
    parser.add_argument("--interval", type=float, default=0.5, help="Synthetic monitor interval in seconds.")
    parser.add_argument("--repeat", type=int, default=10, help="How many times to rebuild the summary.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    samples = []
    start = time.time()
    for idx in range(args.samples):
        samples.append(_synthetic_sample(idx, idx * args.interval))
    build_started = time.perf_counter()
    last_summary = None
    for _ in range(max(1, args.repeat)):
        last_summary = summarize_live_monitor(
            samples,
            include_oscillation=False,
            include_extended=False,
        )
    elapsed = time.perf_counter() - build_started
    print("samples=%d interval=%.3fs repeat=%d" % (args.samples, args.interval, args.repeat))
    print("summary_build_total_s=%.6f" % elapsed)
    print("summary_build_avg_s=%.6f" % (elapsed / max(1, args.repeat)))
    trend_count = len((last_summary or {}).get("trend_data", {}) or {})
    print("trend_series=%d" % trend_count)
    print("wall_clock_elapsed_s=%.6f" % (time.time() - start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
