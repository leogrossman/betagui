#!/usr/bin/env python3
"""Collect a broad read-only control-room inventory for later offline review.

This is meant to be run on the control-room machine after pulling the repo.
It writes commit-friendly artifacts under ``./control_room_outputs/inventory/``
so they can be pushed back to the repo and inspected elsewhere.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "control_room_outputs" / "inventory"
LEGACY_SOURCE = PROJECT_ROOT / "original" / "betagui.py"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: Sequence[str]) -> Dict[str, object]:
    result = subprocess.run(
        list(args),
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


def session_dir(output_root: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = output_root / ("inventory_%s_pid%s" % (stamp, os.getpid()))
    path.mkdir(parents=True, exist_ok=False)
    return path


def extract_legacy_pvs() -> List[str]:
    text = LEGACY_SOURCE.read_text(encoding="utf-8", errors="replace")
    found = []
    for pv in re.findall(r"epics\.PV\('([^']+)'\)", text):
        if pv not in found:
            found.append(pv)
    return found


def python_versions() -> Dict[str, object]:
    packages = {}
    for name in ("numpy", "scipy", "matplotlib", "epics", "tkinter"):
        try:
            module = __import__(name)
            version = getattr(module, "__version__", "built-in")
            packages[name] = {"ok": True, "version": version}
        except Exception as exc:
            packages[name] = {"ok": False, "error": str(exc)}
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": packages,
    }


def environment_snapshot() -> Dict[str, object]:
    keys = [
        "EPICS_CA_ADDR_LIST",
        "EPICS_CA_AUTO_ADDR_LIST",
        "EPICS_PVA_ADDR_LIST",
        "DISPLAY",
        "MPLBACKEND",
        "PYENV_VERSION",
    ]
    return {key: os.environ.get(key) for key in keys}


def collect_command_info() -> Dict[str, object]:
    commands = {}
    for name in ("python3", "pyenv", "cainfo", "caget", "camonitor", "caput", "pvlist", "apptainer"):
        commands[name] = {
            "exists": command_exists(name),
            "path": shutil.which(name),
        }
    return commands


def collect_pvlist() -> Dict[str, object]:
    if not command_exists("pvlist"):
        return {"available": False}
    result = run_command(["pvlist"])
    lines = [line for line in result["stdout"].splitlines() if line.strip()]
    return {
        "available": True,
        "returncode": result["returncode"],
        "count": len(lines),
        "sample": lines[:200],
    }


def probe_pvs(pv_names: Iterable[str], use_caget: bool, limit: Optional[int]) -> List[Dict[str, object]]:
    tool = "caget" if use_caget else "cainfo"
    if not command_exists(tool):
        return []
    probes = []
    items = list(pv_names)
    if limit is not None:
        items = items[:limit]
    for pv_name in items:
        probes.append(
            {
                "pv": pv_name,
                "tool": tool,
                "result": run_command([tool, pv_name]),
            }
        )
    return probes


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="Output directory. Default: ./control_room_outputs/inventory/")
    parser.add_argument("--probe-limit", type=int, default=50, help="How many legacy PVs to probe with cainfo/caget.")
    parser.add_argument("--use-caget", action="store_true", help="Use caget instead of cainfo for PV probes.")
    parser.add_argument(
        "--pv",
        action="append",
        default=[],
        metavar="PVNAME",
        help="Add one extra PV to probe and save in the inventory output.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    output_root = Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_ROOT
    out_dir = session_dir(output_root)

    legacy_pvs = extract_legacy_pvs()
    extra_pv_results = probe_pvs(args.pv, use_caget=args.use_caget, limit=None) if args.pv else []
    payload = {
        "timestamp": time.time(),
        "project_root": str(PROJECT_ROOT),
        "environment": environment_snapshot(),
        "python_versions": python_versions(),
        "commands": collect_command_info(),
        "pvlist": collect_pvlist(),
        "legacy_pv_count": len(legacy_pvs),
        "legacy_pv_probe_results": probe_pvs(legacy_pvs, use_caget=args.use_caget, limit=args.probe_limit),
        "extra_pv_probe_results": extra_pv_results,
    }

    payload_path = out_dir / "inventory.json"
    with payload_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")

    summary_path = out_dir / "inventory_summary.txt"
    with summary_path.open("w", encoding="utf-8") as stream:
        stream.write("Inventory directory: %s\n" % out_dir)
        stream.write("Python: %s\n" % payload["python_versions"]["python"].splitlines()[0])
        stream.write("pvlist available: %s\n" % payload["pvlist"]["available"])
        stream.write("Legacy PV count in source: %s\n" % payload["legacy_pv_count"])
        stream.write("Extra PV probes: %s\n" % len(extra_pv_results))

    print("Inventory saved to:", payload_path)
    print("Summary saved to: ", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
