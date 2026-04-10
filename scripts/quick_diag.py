#!/usr/bin/env python3
"""Quick read-only environment and EPICS diagnostic helper."""

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_SOURCE = PROJECT_ROOT / "original" / "betagui.py"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: Sequence[str]) -> str:
    result = subprocess.run(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def extract_pvs(limit: Optional[int] = None) -> List[str]:
    text = LEGACY_SOURCE.read_text(encoding="utf-8", errors="replace")
    seen = []
    for pv in re.findall(r"epics\.PV\('([^']+)'\)", text):
        if pv not in seen:
            seen.append(pv)
    if limit is not None:
        return seen[:limit]
    return seen


def print_section(title: str):
    print("\n== %s ==" % title)


def print_environment():
    print_section("Environment")
    print("Platform:", platform.platform())
    print("Python:", sys.version.split()[0])
    print("Executable:", sys.executable)
    print("Project root:", PROJECT_ROOT)
    print("Legacy source:", LEGACY_SOURCE)


def print_commands():
    print_section("Commands")
    for name in ("python3", "pyenv", "cainfo", "caget", "camonitor", "caput", "apptainer"):
        print("%-10s %s" % (name + ":", "yes" if command_exists(name) else "no"))


def print_optional_imports():
    print_section("Python imports")
    for module_name in ("numpy", "scipy", "matplotlib", "epics", "tkinter"):
        try:
            __import__(module_name)
            status = "ok"
        except Exception as exc:
            status = "missing (%s)" % exc
        print("%-12s %s" % (module_name + ":", status))


def check_pvs(pv_names: Iterable[str], use_caget: bool):
    tool = "caget" if use_caget else "cainfo"
    if not command_exists(tool):
        print_section("PV checks")
        print("%s is not available." % tool)
        return
    print_section("PV checks")
    for pv_name in pv_names:
        output = run_command([tool, pv_name]).splitlines()
        first_line = output[0] if output else ""
        print("[%s] %s" % (tool, pv_name))
        if first_line:
            print("  " + first_line)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-pv", action="append", default=[], help="Specific PV to probe. Can be used more than once.")
    parser.add_argument("--check-legacy-pvs", action="store_true", help="Probe a small sample of PVs from original/betagui.py.")
    parser.add_argument("--use-caget", action="store_true", help="Use caget instead of cainfo.")
    parser.add_argument("--limit", type=int, default=5, help="How many legacy PVs to probe when --check-legacy-pvs is used.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print_environment()
    print_commands()
    print_optional_imports()

    pv_names: List[str] = list(args.check_pv)
    if args.check_legacy_pvs:
        pv_names.extend(extract_pvs(limit=args.limit))
    if pv_names:
        check_pvs(pv_names, use_caget=args.use_caget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
