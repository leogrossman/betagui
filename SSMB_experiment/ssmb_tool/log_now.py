from __future__ import annotations

import argparse
import csv
import json
import math
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

E_REST_MEV = 0.51099895
MLS_HARMONIC = 80
DEFAULT_L4_DISPERSION_M = {
    "bpmz3l4rp_x": -0.6064241411164305,
    "bpmz4l4rp_x": -0.9744634305495894,
    "bpmz5l4rp_x": -0.9744634305157819,
    "bpmz6l4rp_x": -0.5908095004017995,
}
DEFAULT_QPD_L4_ETA_X_M = -0.9744634305320904
DEFAULT_QPD_L4_BETA_X_M = 7.979840309839388
BPM_WARNING_MM = 3.0
BPM_NONLINEAR_MM = 4.0


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


def _gamma_from_energy_mev(energy_mev):
    value = _safe_float(energy_mev, None)
    if value is None:
        return None
    return value / E_REST_MEV


def _legacy_alpha_unit_corrected(rf_hz, tune_s_hz, cavity_voltage_kv, beam_energy_mev):
    if None in (rf_hz, tune_s_hz, cavity_voltage_kv, beam_energy_mev):
        return None
    ucav_v = cavity_voltage_kv * 1e3
    energy_ev = beam_energy_mev * 1e6
    if ucav_v == 0.0 or rf_hz == 0.0:
        return None
    return tune_s_hz**2 / rf_hz**2 * 2.0 * math.pi * MLS_HARMONIC * energy_ev / ucav_v


def _first_order_delta_from_bpms(channels, reference_orbit_mm, dispersion_by_bpm_m):
    numerator = 0.0
    denominator = 0.0
    used = []
    for label, dispersion_m in dispersion_by_bpm_m.items():
        value_mm = _safe_float(channels.get(label, {}).get("value"), None)
        ref_mm = _safe_float(reference_orbit_mm.get(label), None)
        if value_mm is None or ref_mm is None or dispersion_m == 0.0:
            continue
        offset_m = (value_mm - ref_mm) * 1e-3
        numerator += dispersion_m * offset_m
        denominator += dispersion_m * dispersion_m
        used.append(label)
    if denominator <= 0.0:
        return None, []
    return numerator / denominator, used


def _sigma_delta_from_qpd(channels, epsilon_x_m=None, eta_x_m=DEFAULT_QPD_L4_ETA_X_M, beta_x_m=DEFAULT_QPD_L4_BETA_X_M):
    sigma_x_mm = _safe_float(channels.get("qpd_l4_sigma_x", {}).get("value"), None)
    if sigma_x_mm is None or eta_x_m == 0.0:
        return None
    sigma_x_m = sigma_x_mm * 1e-3
    betatron_term = 0.0
    if epsilon_x_m is not None:
        betatron_term = max(beta_x_m * float(epsilon_x_m), 0.0)
    residual = sigma_x_m * sigma_x_m - betatron_term
    if residual <= 0.0:
        return None
    return math.sqrt(residual) / abs(eta_x_m)


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


def _derived_metrics(sample: Dict[str, object], derived_context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    channels = sample["channels"]
    derived_context = derived_context or {}
    rf_readback = _safe_float(channels.get("rf_readback", {}).get("value"), None)
    tune_x_raw = _safe_float(channels.get("tune_x_raw", {}).get("value"), None)
    tune_y_raw = _safe_float(channels.get("tune_y_raw", {}).get("value"), None)
    tune_s_raw = _safe_float(channels.get("tune_s_raw", {}).get("value"), None)
    beam_energy_mev = _safe_float(channels.get("beam_energy_mev", {}).get("value"), None)
    cavity_voltage_kv = _safe_float(channels.get("cavity_voltage_kv", {}).get("value"), None)
    tune_s_khz = _tune_s_khz(tune_s_raw)
    gamma = _gamma_from_energy_mev(beam_energy_mev)
    inv_gamma2 = None if gamma in (None, 0.0) else 1.0 / (gamma * gamma)
    rf_reference_khz = _safe_float(derived_context.get("rf_reference_khz"), None)
    rf_offset_khz = None if rf_reference_khz is None or rf_readback is None else rf_readback - rf_reference_khz
    rf_offset_hz = None if rf_offset_khz is None else rf_offset_khz * 1e3
    rf_offset_rel = None if rf_reference_khz in (None, 0.0) or rf_readback is None else (rf_readback - rf_reference_khz) / rf_reference_khz
    delta_bpm_l4, used_bpms = _first_order_delta_from_bpms(
        channels=channels,
        reference_orbit_mm=derived_context.get("l4_bpm_reference_mm", {}),
        dispersion_by_bpm_m=derived_context.get("l4_dispersion_m", DEFAULT_L4_DISPERSION_M),
    )
    beam_energy_from_bpm_mev = None if beam_energy_mev is None or delta_bpm_l4 is None else beam_energy_mev * (1.0 + delta_bpm_l4)
    qpd_sigma_delta = _sigma_delta_from_qpd(
        channels,
        epsilon_x_m=derived_context.get("qpd_epsilon_x_m"),
        eta_x_m=float(derived_context.get("qpd_l4_eta_x_m", DEFAULT_QPD_L4_ETA_X_M)),
        beta_x_m=float(derived_context.get("qpd_l4_beta_x_m", DEFAULT_QPD_L4_BETA_X_M)),
    )
    legacy_alpha_corrected = _legacy_alpha_unit_corrected(
        rf_hz=None if rf_readback is None else rf_readback * 1e3,
        tune_s_hz=tune_s_raw,
        cavity_voltage_kv=cavity_voltage_kv,
        beam_energy_mev=beam_energy_mev,
    )
    bpm_x_status = []
    max_abs_bpm_x_mm = None
    for label, payload in sorted(channels.items()):
        if not (label.startswith("bpm") and label.endswith("_x")):
            continue
        value_mm = _safe_float(payload.get("value"), None)
        if value_mm is None:
            continue
        abs_value = abs(value_mm)
        if max_abs_bpm_x_mm is None or abs_value > max_abs_bpm_x_mm:
            max_abs_bpm_x_mm = abs_value
        severity = "green"
        if abs_value >= BPM_NONLINEAR_MM:
            severity = "red"
        elif abs_value >= BPM_WARNING_MM:
            severity = "yellow"
        bpm_x_status.append(
            {
                "label": label,
                "value_mm": value_mm,
                "abs_value_mm": abs_value,
                "severity": severity,
                "nonlinear": abs_value >= BPM_NONLINEAR_MM,
            }
        )
    nonlinear_bpms = [item["label"] for item in bpm_x_status if item["nonlinear"]]
    return {
        "rf_readback": rf_readback,
        "rf_reference_khz": rf_reference_khz,
        "rf_offset_khz": rf_offset_khz,
        "rf_offset_hz": rf_offset_hz,
        "rf_offset_rel": rf_offset_rel,
        "tune_x_unitless": _unitless_tune_from_khz(tune_x_raw),
        "tune_y_unitless": _unitless_tune_from_khz(tune_y_raw),
        "tune_s_khz": tune_s_khz,
        "tune_s_unitless": _unitless_tune_from_khz(tune_s_khz),
        "gamma": gamma,
        "inv_gamma2": inv_gamma2,
        "legacy_alpha0_corrected": legacy_alpha_corrected,
        "delta_l4_bpm_first_order": delta_bpm_l4,
        "delta_l4_bpms_used": used_bpms,
        "beam_energy_from_bpm_mev": beam_energy_from_bpm_mev,
        "qpd_l4_sigma_delta_first_order": qpd_sigma_delta,
        "qpd_l4_sigma_energy_mev": None if qpd_sigma_delta is None or beam_energy_mev is None else beam_energy_mev * qpd_sigma_delta,
        "qpd_l4_sigma_x_mm": _safe_float(channels.get("qpd_l4_sigma_x", {}).get("value"), None),
        "qpd_l4_sigma_y_mm": _safe_float(channels.get("qpd_l4_sigma_y", {}).get("value"), None),
        "bpm_x_status": bpm_x_status,
        "bpm_x_nonlinear_labels": nonlinear_bpms,
        "bpm_x_warning_mm": BPM_WARNING_MM,
        "bpm_x_nonlinear_mm": BPM_NONLINEAR_MM,
        "max_abs_bpm_x_mm": max_abs_bpm_x_mm,
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


def capture_sample(
    adapter,
    specs: Sequence[ChannelSpec],
    sample_index: int,
    t_rel_s: float,
    extra_fields: Optional[Dict[str, object]] = None,
    derived_context: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    sample = {
        "timestamp_epoch_s": time.time(),
        "t_rel_s": t_rel_s,
        "sample_index": sample_index,
        "channels": {},
    }
    for spec in specs:
        sample["channels"][spec.label] = _sample_channel(adapter, spec)
    sample["derived"] = _derived_metrics(sample, derived_context=derived_context)
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


def estimate_sample_bytes(specs: Sequence[ChannelSpec]) -> int:
    total = 0
    for spec in specs:
        if spec.kind == "waveform":
            total += 64 * 1024
        else:
            total += 256
    return total


def estimate_passive_session_bytes(specs: Sequence[ChannelSpec], duration_seconds: float, sample_hz: float) -> int:
    sample_count = max(1, int(math.ceil(float(duration_seconds) * float(sample_hz))))
    return sample_count * estimate_sample_bytes(specs)


def run_stage0_logger(config: LoggerConfig, adapter=None, progress_callback=None, sample_callback=None, stop_event=None, session_prefix: str = "ssmb_stage0", extra_metadata: Optional[Dict[str, object]] = None) -> Path:
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

    estimated_bytes = estimate_passive_session_bytes(specs, config.duration_seconds, config.sample_hz)
    from .session import disk_usage_summary

    disk_root = config.output_root if config.output_root.exists() else config.output_root.parent
    disk = disk_usage_summary(disk_root)
    metadata = build_metadata(
        config,
        lattice,
        specs,
        "SSMB Stage 0 logger",
        extra={
            **(extra_metadata or {}),
            "disk_usage_at_start": disk,
            "estimated_session_size_bytes": estimated_bytes,
            "write_strategy": "incremental_jsonl_with_final_csv",
            "session_status": "running",
        },
    )
    logger.write_json("metadata.json", metadata)
    emit("Estimated session size: %.2f MB; free space: %.2f GB." % (estimated_bytes / (1024.0 * 1024.0), disk["free_bytes"] / (1024.0 * 1024.0 * 1024.0)))
    deadline = time.monotonic() + config.duration_seconds
    period = 1.0 / config.sample_hz
    sample_index = 0
    start = time.monotonic()
    samples: List[Dict[str, object]] = []

    try:
        while True:
            now = time.monotonic()
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                emit("Stop requested by operator; finalizing passive log.")
                break
            if now > deadline:
                break
            try:
                sample = capture_sample(adapter, specs, sample_index=sample_index, t_rel_s=now - start)
            except Exception as exc:
                emit("Sample %d capture failed: %s" % (sample_index, exc))
                sample = {
                    "timestamp_epoch_s": time.time(),
                    "t_rel_s": now - start,
                    "sample_index": sample_index,
                    "channels": {},
                    "derived": {},
                    "error": str(exc),
                    "phase": "capture_error",
                }
            samples.append(sample)
            logger.append_jsonl("samples.jsonl", sample)
            if sample_callback is not None:
                sample_callback(sample)
            nonlinear = sample.get("derived", {}).get("bpm_x_nonlinear_labels") or []
            if nonlinear:
                emit("Sample %d nonlinear BPM warning: %s" % (sample_index, ", ".join(nonlinear)))
            sample_index += 1
            next_target = start + sample_index * period
            sleep_s = next_target - time.monotonic()
            if sleep_s > 0.0:
                time.sleep(sleep_s)
    except Exception as exc:
        metadata["session_status"] = "failed"
        metadata["failure"] = str(exc)
        logger.write_json("metadata.json", metadata)
        raise
    else:
        metadata["session_status"] = "completed"
    finally:
        metadata["partial_sample_count"] = len(samples)
        logger.write_json("metadata.json", metadata)
        if samples:
            _write_csv(logger.session_dir / "samples.csv", [_flatten_for_csv(sample) for sample in samples])
            logger.log("Partial/final CSV written with %d samples." % len(samples))

    logger.log("Samples were written incrementally to samples.jsonl during capture.")
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
