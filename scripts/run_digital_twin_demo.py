#!/usr/bin/env python3
"""Read-only helper for the MLS/EPICS digital twin workflow.

Default behavior is diagnostic only:
- prints the local and remote container references
- checks whether key host commands are available
- optionally probes PVs with cainfo/caget

Container start is opt-in via --start-container.
No PV writes are performed by this script.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTAINER = PROJECT_ROOT / "support" / "digital_twin" / "pyat-as-twin-softioc.sif"
DEFAULT_ORAS_IMAGE = (
    "oras://registry.hzdr.de/digital-twins-for-accelerators/containers/"
    "pyat-softioc-digital-twin:v0-1-3-mls.2469803"
)
LEGACY_SOURCE = PROJECT_ROOT / "original" / "betagui.py"


def extract_legacy_pvs(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    pvs = re.findall(r"epics\.PV\('([^']+)'\)", text)
    ordered = []
    seen = set()
    for pv in pvs:
        if pv not in seen:
            seen.add(pv)
            ordered.append(pv)
    return ordered


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(args: Sequence[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )


def print_header(title: str):
    print("\n== %s ==" % title)


def describe_environment(container_path: Path):
    print_header("Environment")
    print("Project root:", PROJECT_ROOT)
    print("Legacy source:", LEGACY_SOURCE)
    print("Local container:", container_path)
    print("Local container exists:", container_path.exists())
    print("Remote ORAS image:", DEFAULT_ORAS_IMAGE)


def describe_commands():
    print_header("Host commands")
    for command in ("apptainer", "cainfo", "caget", "camonitor", "caput"):
        print("%-10s %s" % (command + ":", "yes" if command_exists(command) else "no"))


def start_container(container_path: Path, background: bool):
    print_header("Container start")
    if not command_exists("apptainer"):
        print("apptainer is not available on this host.")
        return
    if not container_path.exists():
        print("Container file not found:", container_path)
        return
    command = ["apptainer", "run", str(container_path)]
    print("Command:", " ".join(command))
    if background:
        process = subprocess.Popen(command)
        print("Started in background with PID:", process.pid)
        print("Use your usual process tools to stop it when finished.")
        return
    print("Starting in foreground. Stop it with Ctrl-C when you are done.")
    subprocess.run(command, check=False)


def probe_pvs(pv_names: Iterable[str], use_caget: bool, delay_s: float):
    pv_names = list(pv_names)
    if not pv_names:
        print("No PVs requested.")
        return

    checker = "caget" if use_caget else "cainfo"
    if not command_exists(checker):
        print("%s is not available on this host." % checker)
        return

    print_header("PV probe")
    print("Tool:", checker)
    for pv_name in pv_names:
        result = run_command([checker, pv_name], timeout=5.0)
        ok = result.returncode == 0
        status = "ok" if ok else "fail"
        first_line = result.stdout.strip().splitlines()
        preview = first_line[0] if first_line else ""
        print("[%s] %s" % (status, pv_name))
        if preview:
            print("  " + preview)
        if delay_s > 0.0:
            time.sleep(delay_s)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--container",
        default=str(DEFAULT_CONTAINER),
        help="Path to the local Apptainer image.",
    )
    parser.add_argument(
        "--start-container",
        action="store_true",
        help="Start the local Apptainer image. This is opt-in.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="When used with --start-container, run the container in the background.",
    )
    parser.add_argument(
        "--check-legacy-pvs",
        action="store_true",
        help="Probe all PV names extracted from original/betagui.py using cainfo.",
    )
    parser.add_argument(
        "--pv",
        action="append",
        default=[],
        help="Probe one or more specific PVs. Can be passed multiple times.",
    )
    parser.add_argument(
        "--use-caget",
        action="store_true",
        help="Use caget instead of cainfo for PV probes.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between PV probes in seconds.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    container_path = Path(args.container).expanduser().resolve()

    describe_environment(container_path)
    describe_commands()

    print_header("Suggested manual workflow")
    print("1. Start the twin:")
    print("   apptainer run %s" % container_path)
    print("2. Check host EPICS access:")
    print("   cainfo TUNEZRP:measX")
    print("   caget  TUNEZRP:measX")
    print("3. Compare legacy PVs against the twin:")
    print("   %s --check-legacy-pvs" % Path(__file__).name)

    if args.start_container:
        start_container(container_path, background=args.background)

    probe_list: List[str] = []
    if args.check_legacy_pvs:
        probe_list.extend(extract_legacy_pvs(LEGACY_SOURCE))
    probe_list.extend(args.pv)
    if probe_list:
        probe_pvs(probe_list, use_caget=args.use_caget, delay_s=args.delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
