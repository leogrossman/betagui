#!/usr/bin/env python3
"""Run noninteractive control-room checks step by step and save outputs.

This stays read-only. It does not perform machine writes.
It is meant to collect baseline information, safe preflight results, and
comparison outputs into ``./control_room_outputs/step_tests/`` so they can be
committed and reviewed later.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "control_room_outputs" / "step_tests"
MACHINE_CHECK = PROJECT_ROOT / "control_room" / "machine_check.py"
CLI = PROJECT_ROOT / "control_room" / "betagui_cli.py"
QUICK_DIAG = PROJECT_ROOT / "scripts" / "quick_diag.py"


def session_dir(output_root: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = output_root / ("%s_%s_pid%s" % (prefix, stamp, os.getpid()))
    path.mkdir(parents=True, exist_ok=False)
    return path


def run_capture(args: Sequence[str], cwd: Path) -> dict:
    result = subprocess.run(
        list(args),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return {
        "args": list(args),
        "returncode": result.returncode,
        "stdout": result.stdout,
    }


def save_json(path: Path, payload) -> None:
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def cmd_baseline(args) -> int:
    out_dir = session_dir(Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_ROOT, "baseline")
    diag = run_capture([sys.executable, str(QUICK_DIAG), "--check-legacy-pvs", "--limit", str(args.probe_limit)], PROJECT_ROOT)
    snapshot = run_capture([sys.executable, str(MACHINE_CHECK), "snapshot"], PROJECT_ROOT)
    payload = {
        "timestamp": time.time(),
        "diag": diag,
        "snapshot": snapshot,
    }
    save_json(out_dir / "baseline.json", payload)
    print("Baseline saved to:", out_dir / "baseline.json")
    return 0 if diag["returncode"] == 0 and snapshot["returncode"] == 0 else 1


def cmd_safe_cli(args) -> int:
    out_dir = session_dir(Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_ROOT, "safe_cli")
    payload = {
        "timestamp": time.time(),
        "safe_cli": run_capture([sys.executable, str(CLI), "--safe"], PROJECT_ROOT),
    }
    save_json(out_dir / "safe_cli.json", payload)
    print("Safe CLI output saved to:", out_dir / "safe_cli.json")
    return int(payload["safe_cli"]["returncode"])


def cmd_compare(args) -> int:
    out_dir = session_dir(Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_ROOT, "compare")
    payload = {
        "timestamp": time.time(),
        "compare": run_capture([sys.executable, str(MACHINE_CHECK), "compare", "--snapshot", args.snapshot], PROJECT_ROOT),
    }
    save_json(out_dir / "compare.json", payload)
    print("Compare output saved to:", out_dir / "compare.json")
    return int(payload["compare"]["returncode"])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="Output directory. Default: ./control_room_outputs/step_tests/")
    sub = parser.add_subparsers(dest="command", required=True)

    baseline = sub.add_parser("baseline", help="Run quick_diag and capture a baseline snapshot.")
    baseline.add_argument("--probe-limit", type=int, default=10, help="How many legacy PVs quick_diag should probe.")
    baseline.set_defaults(func=cmd_baseline)

    safe_cli = sub.add_parser("safe-cli", help="Run the safe CLI preflight and save its output.")
    safe_cli.set_defaults(func=cmd_safe_cli)

    compare = sub.add_parser("compare", help="Compare current machine values to a saved snapshot.")
    compare.add_argument("--snapshot", required=True, help="Path to a snapshot.json file.")
    compare.set_defaults(func=cmd_compare)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
