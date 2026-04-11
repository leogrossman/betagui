from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

from .config import LoggerConfig, parse_labeled_pvs
from .epics_io import EpicsUnavailableError, ReadOnlyEpicsAdapter
from .inventory import ChannelSpec, build_default_inventory, inventory_summary
from .lattice import LatticeContext
from .session import SessionLogger, json_ready


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tune_s_khz(raw_value):
    raw = _safe_float(raw_value, None)
    if raw is None:
        return None
    return raw / 1000.0


def _unitless_tune_from_khz(freq_khz):
    value = _safe_float(freq_khz, None)
    if value is None:
        return None
    return value / (299792458.0 / 48.0 / 1000.0)


def _git_commit() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _flatten_for_csv(sample: Dict[str, object]) -> Dict[str, object]:
    row = {
        "timestamp_epoch_s": sample["timestamp_epoch_s"],
        "sample_index": sample["sample_index"],
    }
    for label, payload in sample["channels"].items():
        value = payload["value"]
        if isinstance(value, (list, tuple)):
            array = np.asarray(value, dtype=float) if value else np.asarray([], dtype=float)
            row[label + "_len"] = int(array.size)
            row[label + "_mean"] = float(np.mean(array)) if array.size else None
            row[label + "_std"] = float(np.std(array)) if array.size else None
            continue
        row[label] = value
    return row


def _write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("_")


def _sample_channel(adapter: ReadOnlyEpicsAdapter, spec: ChannelSpec) -> Dict[str, object]:
    if not spec.pv:
        return {"pv": None, "value": None, "missing": True, "reason": "unconfigured_optional"}
    value = adapter.get(spec.pv, None)
    missing = value is None
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except Exception:
            pass
    return {"pv": spec.pv, "value": value, "missing": missing}


def _derived_metrics(sample: Dict[str, object]) -> Dict[str, object]:
    channels = sample["channels"]
    rf_readback = _safe_float(channels.get("rf_readback", {}).get("value"), None)
    tune_x_raw = _safe_float(channels.get("tune_x_raw", {}).get("value"), None)
    tune_y_raw = _safe_float(channels.get("tune_y_raw", {}).get("value"), None)
    tune_s_raw = channels.get("tune_s_raw", {}).get("value")
    tune_s_khz = _tune_s_khz(tune_s_raw)
    return {
        "rf_readback": rf_readback,
        "tune_x_unitless": _unitless_tune_from_khz(tune_x_raw),
        "tune_y_unitless": _unitless_tune_from_khz(tune_y_raw),
        "tune_s_khz": tune_s_khz,
        "tune_s_unitless": _unitless_tune_from_khz(tune_s_khz),
    }


def build_specs(config: LoggerConfig):
    config.validate()
    lattice = LatticeContext.load(config.lattice_export)
    specs = build_default_inventory(
        lattice=lattice,
        extra_pvs=config.extra_pvs,
        extra_optional_pvs=config.extra_optional_pvs,
    )
    if not config.include_bpm_buffer:
        specs = [spec for spec in specs if spec.label != "bpm_buffer_raw"]
    if not config.include_candidate_bpm_scalars:
        specs = [spec for spec in specs if "u125_region" not in spec.tags and "l4" not in spec.tags]
    if not config.include_ring_bpm_scalars:
        specs = [spec for spec in specs if "ring" not in spec.tags]
    if not config.include_quadrupoles:
        specs = [spec for spec in specs if "quadrupole" not in spec.tags]
    if not config.include_sextupoles:
        specs = [spec for spec in specs if "sextupole" not in spec.tags]
    if not config.include_octupoles:
        specs = [spec for spec in specs if "octupole" not in spec.tags]
    return lattice, specs


def inventory_overview_lines(specs: Sequence[ChannelSpec]) -> List[str]:
    lines = [
        "Logged channels: %d" % len(specs),
        "",
    ]
    for spec in specs:
        requirement = "required" if spec.required else "optional"
        pv_name = spec.pv or "UNCONFIGURED"
        tag_text = ", ".join(spec.tags) if spec.tags else "-"
        lines.append("%s | %s | %s | %s" % (spec.label, requirement, pv_name, tag_text))
    return lines


def build_metadata(config: LoggerConfig, lattice: LatticeContext, specs: Sequence[ChannelSpec], tool_name: str, extra: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    metadata = {
        "tool": tool_name,
        "version": 1,
        "safe_mode": config.safe_mode,
        "allow_writes": config.allow_writes,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version,
        "cwd": str(Path.cwd()),
        "argv": sys.argv,
        "repo_commit": _git_commit(),
        "lattice_export": str(config.lattice_export),
        "lattice_ring_name": lattice.ring_name,
        "lattice_energy_eV": lattice.energy_eV,
        "config": json_ready(asdict(config)),
        "inventory_summary": inventory_summary(specs),
        "channel_specs": [json_ready(asdict(spec)) for spec in specs],
        "missing_pvs": {},
    }
    if extra:
        metadata.update(extra)
    return metadata


def capture_sample(adapter, specs: Sequence[ChannelSpec], sample_index: int, t_rel_s: float, extra_fields: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    sample = {
        "timestamp_epoch_s": time.time(),
        "t_rel_s": t_rel_s,
        "sample_index": sample_index,
        "channels": {},
    }
    for spec in specs:
        sample["channels"][spec.label] = _sample_channel(adapter, spec)
    sample["derived"] = _derived_metrics(sample)
    if extra_fields:
        sample.update(extra_fields)
    return sample


def write_session_outputs(
    logger: SessionLogger,
    metadata: Dict[str, object],
    samples: Sequence[Dict[str, object]],
) -> Path:
    samples_jsonl = logger.session_dir / "samples.jsonl"
    csv_rows = [_flatten_for_csv(sample) for sample in samples]
    missing_counts: Dict[str, int] = {}
    with samples_jsonl.open("w", encoding="utf-8") as stream:
        for sample in samples:
            for label, payload in sample["channels"].items():
                if payload.get("missing"):
                    missing_counts[label] = missing_counts.get(label, 0) + 1
            stream.write(json.dumps(json_ready(sample), sort_keys=True) + "\n")
    metadata = dict(metadata)
    metadata["missing_pvs"] = missing_counts
    metadata["sample_count"] = len(samples)
    metadata["session_dir"] = str(logger.session_dir)
    logger.write_json("metadata.json", metadata)
    _write_csv(logger.session_dir / "samples.csv", csv_rows)
    logger.log("Wrote %d samples." % len(samples))
    logger.log("Outputs: metadata.json, samples.jsonl, samples.csv, session.log")
    return logger.session_dir


def run_stage0_logger(config: LoggerConfig, adapter=None, progress_callback=None, session_prefix: str = "ssmb_stage0", extra_metadata: Optional[Dict[str, object]] = None) -> Path:
    if config.allow_writes or not config.safe_mode:
        raise ValueError("Stage 0 logger is read-only only. Use the separate RF sweep tool for explicit writes.")
    lattice, specs = build_specs(config)
    prefix = session_prefix
    if config.session_label:
        prefix += "_" + _sanitize_label(config.session_label)
    logger = SessionLogger.create(config.output_root, prefix)
    if progress_callback is None:
        def emit(message: str) -> None:
            logger.log(message)
    else:
        def emit(message: str) -> None:
            logger.log(message)
            progress_callback(message)
    emit("Starting Stage 0 passive SSMB logging.")
    emit("Sample rate %.3f Hz for %.1f s." % (config.sample_hz, config.duration_seconds))

    if adapter is None:
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=config.timeout_seconds)
        except EpicsUnavailableError as exc:
            emit(str(exc))
            metadata = {
                "safe_mode": config.safe_mode,
                "allow_writes": config.allow_writes,
                "error": str(exc),
                "inventory": inventory_summary(specs),
            }
            logger.write_json("metadata.json", metadata)
            raise

    metadata = build_metadata(config, lattice, specs, "SSMB Stage 0 logger", extra=extra_metadata)
    deadline = time.monotonic() + config.duration_seconds
    period = 1.0 / config.sample_hz
    sample_index = 0
    start = time.monotonic()
    samples: List[Dict[str, object]] = []

    while True:
        now = time.monotonic()
        if now > deadline:
            break
        sample = capture_sample(adapter, specs, sample_index=sample_index, t_rel_s=now - start)
        samples.append(sample)
        sample_index += 1
        next_target = start + sample_index * period
        sleep_s = next_target - time.monotonic()
        if sleep_s > 0.0:
            time.sleep(sleep_s)

    return write_session_outputs(logger, metadata, samples)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "Passive SSMB Stage 0 logger.")
    parser.add_argument("--duration", type=float, default=60.0, help="Capture duration in seconds. Default: 60")
    parser.add_argument("--sample-hz", type=float, default=1.0, help="Sample rate in Hz. Default: 1")
    parser.add_argument("--timeout", type=float, default=0.5, help="PV read timeout in seconds. Default: 0.5")
    parser.add_argument("--output-dir", help="Output root. Default: ./.ssmb_local/ssmb_stage0/")
    parser.add_argument("--lattice-export", help="Path to lattice export JSON.")
    parser.add_argument("--no-bpm-buffer", action="store_true", help="Skip the raw BPM buffer waveform PV.")
    parser.add_argument("--no-bpm-scalars", action="store_true", help="Skip candidate scalar BPM readbacks from the lattice export.")
    parser.add_argument("--no-ring-bpm-scalars", action="store_true", help="Skip full-ring BPM scalar candidates from the lattice export.")
    parser.add_argument("--quadrupoles", action="store_true", help="Include quadrupole current/readback candidates from the lattice export.")
    parser.add_argument("--no-sextupoles", action="store_true", help="Skip sextupole current/readback candidates from the lattice export.")
    parser.add_argument("--no-octupoles", action="store_true", help="Skip octupole readback/setpoint logging.")
    parser.add_argument("--heavy", action="store_true", help="Convenience preset: enable ring BPMs, quadrupoles, sextupoles, and octupoles at the chosen sample rate.")
    parser.add_argument("--label", default="", help="Short session label such as bump_on or bump_off.")
    parser.add_argument("--note", default="", help="Operator note stored in metadata.")
    parser.add_argument("--pv", action="append", default=[], metavar="LABEL=PVNAME", help="Add one extra required read-only PV.")
    parser.add_argument("--optional-pv", action="append", default=[], metavar="LABEL=PVNAME", help="Fill in one optional experiment PV placeholder.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = LoggerConfig(
        duration_seconds=args.duration,
        sample_hz=args.sample_hz,
        timeout_seconds=args.timeout,
        output_root=Path(args.output_dir).expanduser().resolve() if args.output_dir else Path.cwd() / "control_room_outputs" / "ssmb_stage0",
        lattice_export=Path(args.lattice_export).expanduser().resolve() if args.lattice_export else LoggerConfig().lattice_export,
        include_bpm_buffer=not args.no_bpm_buffer,
        include_candidate_bpm_scalars=not args.no_bpm_scalars,
        include_ring_bpm_scalars=True if args.heavy else not args.no_ring_bpm_scalars,
        include_quadrupoles=True if args.heavy else args.quadrupoles,
        include_sextupoles=True if args.heavy else not args.no_sextupoles,
        include_octupoles=True if args.heavy else not args.no_octupoles,
        session_label=args.label,
        operator_note=args.note,
        extra_pvs=parse_labeled_pvs(args.pv),
        extra_optional_pvs=parse_labeled_pvs(args.optional_pv),
    )
    session_dir = run_stage0_logger(config)
    print("SSMB Stage 0 log saved to:", session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
