#!/usr/bin/env python3
"""Read-only machine check and explicit restore helper for control-room work.

Typical use on the machine:

1. Capture a baseline snapshot before any tests:
   python3 /path/to/betagui/control_room/machine_check.py snapshot

2. Run read-only checks:
   python3 /path/to/betagui/control_room/machine_check.py status
   python3 /path/to/betagui/control_room/betagui.py --safe

3. After live tests, compare current state to the saved snapshot:
   python3 /path/to/betagui/control_room/machine_check.py compare --snapshot SNAPSHOT_JSON

4. If needed, restore the saved writable state:
   python3 /path/to/betagui/control_room/machine_check.py restore --snapshot SNAPSHOT_JSON --apply
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_OUTPUT_ROOTNAME = "control_room_outputs"
DEFAULT_OUTPUT_DIRNAME = "machine_checks"
RF_TOLERANCE = 1e-3
CURRENT_TOLERANCE = 1e-6
GENERIC_TOLERANCE = 1e-9


class EpicsUnavailableError(RuntimeError):
    """Raised when pyepics is not available."""


def _import_epics():
    try:
        import epics  # type: ignore
    except ImportError as exc:
        raise EpicsUnavailableError("pyepics is required for machine_check.py.") from exc
    return epics


class EpicsAdapter:
    """Tiny PV cache for read/write operations."""

    def __init__(self, timeout: float = 1.0):
        self.timeout = timeout
        self._epics = _import_epics()
        self._cache: Dict[str, object] = {}

    def pv(self, name: str):
        pv = self._cache.get(name)
        if pv is None:
            pv = self._epics.PV(name, connection_timeout=self.timeout)
            self._cache[name] = pv
        return pv

    def get(self, name: str, default=None):
        value = self.pv(name).get(timeout=self.timeout, use_monitor=False)
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        return self.pv(name).put(value)

    def connected(self, name: str) -> Optional[bool]:
        return getattr(self.pv(name), "connected", None)


@dataclass(frozen=True)
class PVSpec:
    label: str
    pv: str
    writable: bool = False
    group: str = "status"


PV_SPECS: List[PVSpec] = [
    PVSpec("rf_setpoint", "MCLKHGP:setFrq", writable=True, group="restore"),
    PVSpec("tune_x", "TUNEZRP:measX"),
    PVSpec("tune_y", "TUNEZRP:measY"),
    PVSpec("tune_s", "TUNEZRP:measZ"),
    PVSpec("optics_mode", "MLSOPCCP:actOptRmpTblSet"),
    PVSpec("orbit_mode_write", "ORBITCCP:selRunMode", writable=True, group="restore"),
    PVSpec("orbit_mode_readback", "RMC00VP"),
    PVSpec("feedback_x", "IGPF:X:FBCTRL", writable=True, group="restore"),
    PVSpec("feedback_y", "IGPF:Y:FBCTRL", writable=True, group="restore"),
    PVSpec("feedback_s", "IGPF:Z:FBCTRL", writable=True, group="restore"),
    PVSpec("cavity_voltage", "PAHRP:setVoltCav"),
    PVSpec("beam_energy", "ERMPCGP:rdRmp"),
    PVSpec("beam_current", "CUM1ZK3RP:measCur"),
    PVSpec("beam_lifetime_10h", "CUM1ZK3RP:rdLt10"),
    PVSpec("beam_lifetime_100h", "CUM1ZK3RP:rdLt100"),
    PVSpec("calculated_lifetime", "OPCHECKCCP:calcCurrLife"),
    PVSpec("qpd1_sigma_x", "QPD01ZL2RP:rdSigmaX"),
    PVSpec("qpd1_sigma_y", "QPD01ZL2RP:rdSigmaY"),
    PVSpec("qpd0_sigma_x", "QPD00ZL4RP:rdSigmaX"),
    PVSpec("qpd0_sigma_y", "QPD00ZL4RP:rdSigmaY"),
    PVSpec("dose_rate", "SEKRRP:rdDose"),
    PVSpec("white_noise", "WFGENC1CP:rdVolt"),
    PVSpec("phase_modulation", "PAHRP:cmdExtPhasMod"),
    PVSpec("S1P1", "S1P1RP:setCur", writable=True, group="restore"),
    PVSpec("S1P2", "S1P2RP:setCur", writable=True, group="restore"),
    PVSpec("S2P1", "S2P1RP:setCur", writable=True, group="restore"),
    PVSpec("S2P2", "S2P2RP:setCur", writable=True, group="restore"),
    PVSpec("S2P2K", "S2P2KRP:setCur", writable=True, group="restore"),
    PVSpec("S2P2L", "S2P2LRP:setCur", writable=True, group="restore"),
    PVSpec("S3P1", "S3P1RP:setCur", writable=True, group="restore"),
    PVSpec("S3P2", "S3P2RP:setCur", writable=True, group="restore"),
]

SPEC_BY_LABEL = {spec.label: spec for spec in PV_SPECS}


def _output_root(path_arg: Optional[str]) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    return Path.cwd() / DEFAULT_OUTPUT_ROOTNAME / DEFAULT_OUTPUT_DIRNAME


def _session_dir(output_root: Path, prefix: str) -> Path:
    session_name = "%s_%s_pid%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"), os.getpid())
    session_dir = output_root / session_name
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def _coerce_json(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    return repr(value)


def _read_spec(adapter: EpicsAdapter, spec: PVSpec) -> Dict[str, object]:
    value = adapter.get(spec.pv, None)
    return {
        "label": spec.label,
        "pv": spec.pv,
        "connected": adapter.connected(spec.pv),
        "value": _coerce_json(value),
        "writable": spec.writable,
        "group": spec.group,
    }


def capture_snapshot(adapter: EpicsAdapter) -> Dict[str, object]:
    records = [_read_spec(adapter, spec) for spec in PV_SPECS]
    return {
        "timestamp": time.time(),
        "hostname": socket.gethostname(),
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "records": records,
    }


def write_snapshot(session_dir: Path, snapshot: Dict[str, object]) -> Path:
    path = session_dir / "snapshot.json"
    with path.open("w", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def write_summary(session_dir: Path, snapshot: Dict[str, object]) -> Path:
    path = session_dir / "summary.txt"
    lines = []
    lines.append("Machine snapshot")
    lines.append("time: %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot["timestamp"])))
    lines.append("hostname: %s" % snapshot["hostname"])
    lines.append("")
    for record in snapshot["records"]:
        lines.append(
            "%-20s %-24s connected=%-5s value=%r"
            % (
                record["label"],
                record["pv"],
                record["connected"],
                record["value"],
            )
        )
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return path


def _value_tolerance(label: str) -> float:
    if label == "rf_setpoint":
        return RF_TOLERANCE
    if label.startswith("S"):
        return CURRENT_TOLERANCE
    return GENERIC_TOLERANCE


def _to_float_if_possible(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def diff_snapshot(saved_snapshot: Dict[str, object], current_snapshot: Dict[str, object]) -> List[Dict[str, object]]:
    current_by_label = {record["label"]: record for record in current_snapshot["records"]}
    diffs = []
    for saved in saved_snapshot["records"]:
        current = current_by_label.get(saved["label"])
        if current is None:
            diffs.append({"label": saved["label"], "status": "missing_now"})
            continue
        saved_value = saved["value"]
        current_value = current["value"]
        saved_float = _to_float_if_possible(saved_value)
        current_float = _to_float_if_possible(current_value)
        if saved_float is not None and current_float is not None:
            delta = current_float - saved_float
            if abs(delta) > _value_tolerance(saved["label"]):
                diffs.append(
                    {
                        "label": saved["label"],
                        "pv": saved["pv"],
                        "saved": saved_value,
                        "current": current_value,
                        "delta": delta,
                    }
                )
        elif saved_value != current_value:
            diffs.append(
                {
                    "label": saved["label"],
                    "pv": saved["pv"],
                    "saved": saved_value,
                    "current": current_value,
                    "delta": None,
                }
            )
    return diffs


def load_snapshot(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def restore_actions(snapshot: Dict[str, object], labels: Optional[Sequence[str]] = None) -> List[Tuple[str, str, object]]:
    allowed = set(labels or [])
    actions = []
    for record in snapshot["records"]:
        spec = SPEC_BY_LABEL.get(record["label"])
        if spec is None or not spec.writable:
            continue
        if allowed and record["label"] not in allowed:
            continue
        actions.append((record["label"], spec.pv, record["value"]))
    return actions


def print_snapshot(snapshot: Dict[str, object]):
    print("timestamp:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot["timestamp"])))
    print("hostname:", snapshot["hostname"])
    for record in snapshot["records"]:
        print(
            "%-20s connected=%-5s value=%r"
            % (record["label"], record["connected"], record["value"])
        )


def cmd_status(args) -> int:
    adapter = EpicsAdapter(timeout=args.timeout)
    snapshot = capture_snapshot(adapter)
    print_snapshot(snapshot)
    return 0


def cmd_snapshot(args) -> int:
    output_root = _output_root(args.output_dir)
    session_dir = _session_dir(output_root, "machine_snapshot")
    adapter = EpicsAdapter(timeout=args.timeout)
    snapshot = capture_snapshot(adapter)
    snapshot_path = write_snapshot(session_dir, snapshot)
    summary_path = write_summary(session_dir, snapshot)
    print("Snapshot saved to:", snapshot_path)
    print("Summary saved to: ", summary_path)
    print("")
    print("Use this to compare later:")
    print("python3 control_room/machine_check.py compare --snapshot %s" % snapshot_path)
    print("Use this to restore writable channels later:")
    print("python3 control_room/machine_check.py restore --snapshot %s --apply" % snapshot_path)
    return 0


def cmd_compare(args) -> int:
    adapter = EpicsAdapter(timeout=args.timeout)
    saved_snapshot = load_snapshot(Path(args.snapshot))
    current_snapshot = capture_snapshot(adapter)
    diffs = diff_snapshot(saved_snapshot, current_snapshot)
    if not diffs:
        print("No differences found outside configured tolerances.")
        return 0
    print("Differences:")
    for diff in diffs:
        print(diff)
    return 1


def cmd_restore(args) -> int:
    adapter = EpicsAdapter(timeout=args.timeout)
    snapshot = load_snapshot(Path(args.snapshot))
    actions = restore_actions(snapshot, labels=args.label)
    if not actions:
        print("No writable restore actions were found.")
        return 0
    print("Restore plan:")
    for label, pv, value in actions:
        print("  %-20s %-24s -> %r" % (label, pv, value))
    if not args.apply:
        print("")
        print("Dry run only. Re-run with --apply to perform the restore.")
        return 0
    for label, pv, value in actions:
        print("Writing %-20s %r" % (label, value))
        adapter.put(pv, value)
        time.sleep(args.delay)
    print("Restore writes completed. Compare current state to the snapshot next.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=1.0, help="EPICS PV get timeout in seconds.")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Read current machine values without writing.")
    status.set_defaults(func=cmd_status)

    snapshot = sub.add_parser("snapshot", help="Capture a baseline snapshot to a new folder.")
    snapshot.add_argument("--output-dir", help="Directory for snapshot folders. Default: ./betagui_machine_checks/")
    snapshot.set_defaults(func=cmd_snapshot)

    compare = sub.add_parser("compare", help="Compare current machine values against a saved snapshot.")
    compare.add_argument("--snapshot", required=True, help="Path to a saved snapshot.json.")
    compare.set_defaults(func=cmd_compare)

    restore = sub.add_parser("restore", help="Dry-run or apply a restore from a saved snapshot.")
    restore.add_argument("--snapshot", required=True, help="Path to a saved snapshot.json.")
    restore.add_argument("--label", action="append", help="Only restore selected labels. Can be used more than once.")
    restore.add_argument("--apply", action="store_true", help="Actually perform the writes. Default is dry-run.")
    restore.add_argument("--delay", type=float, default=0.1, help="Delay between restore writes in seconds.")
    restore.set_defaults(func=cmd_restore)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
