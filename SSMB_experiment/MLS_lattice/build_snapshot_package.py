from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_package(snapshot_path: Path) -> dict:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    sample = (snapshot.get("latest_monitor_sample") or {})
    channels = (sample.get("channels") or {})
    live_channel_labels = sorted(channels.keys())
    magnet_like = sorted(
        label
        for label, payload in channels.items()
        if any(token in str((payload or {}).get("pv", "")).lower() for token in ("setcur", "rdcur", "cur", "volt"))
    )
    return {
        "source_snapshot": str(snapshot_path),
        "lattice_model_label": snapshot.get("lattice_model_label"),
        "lattice_export": snapshot.get("lattice_export"),
        "timestamp_epoch_s": snapshot.get("timestamp_epoch_s"),
        "live_channel_count": len(live_channel_labels),
        "live_channel_labels": live_channel_labels,
        "magnet_like_channels": magnet_like,
        "snapshot_to_pyat_status": {
            "ready_for_full_regeneration": False,
            "reason": "Snapshot does not yet contain a complete live magnet-family state nor a direct PV-to-pyAT family-strength mapping.",
            "still_needed": [
                "Full quadrupole/sextupole/octupole/dipole current or strength readback set",
                "Verified mapping from PV families to pyAT lattice families",
                "A pyAT-capable environment on the analysis side",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a control-room snapshot package for later offline pyAT refinement.")
    parser.add_argument("snapshot", type=Path, help="Path to ssmb_machine_snapshot.json")
    parser.add_argument("--output", type=Path, default=None, help="Optional output JSON path")
    args = parser.parse_args()

    package = build_package(args.snapshot)
    output = args.output or args.snapshot.with_name(args.snapshot.stem + "_package.json")
    output.write_text(json.dumps(package, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
