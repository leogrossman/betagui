from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .analyze_session import alpha0_from_eta, fit_slip_factor
from .config import LoggerConfig, parse_labeled_pvs
from .epics_io import EpicsAdapter
from .log_now import build_metadata, build_specs, capture_sample, estimate_sample_bytes, write_session_outputs
from .session import SessionLogger, disk_usage_summary


RF_PV_NAME = "MCLKHGP:setFrq"
RF_PV_UNITS_PER_HZ = 1.0 / 1000.0
PRIMARY_L4_BPM_LABELS = ("bpmz3l4rp_x", "bpmz4l4rp_x", "bpmz5l4rp_x", "bpmz6l4rp_x")


def sanitize_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("_")


@dataclass(frozen=True)
class RFSweepPlan:
    center_rf_pv: float
    delta_min_hz: float
    delta_max_hz: float
    n_points: int
    settle_seconds: float = 1.0
    samples_per_point: int = 1
    sample_spacing_seconds: float = 0.0
    restore_initial_rf: bool = True

    def rf_points_pv(self) -> np.ndarray:
        delta_points_hz = np.linspace(float(self.delta_min_hz), float(self.delta_max_hz), int(self.n_points))
        return np.asarray(self.center_rf_pv + delta_points_hz * RF_PV_UNITS_PER_HZ, dtype=float)

    def delta_points_hz(self) -> np.ndarray:
        return np.linspace(float(self.delta_min_hz), float(self.delta_max_hz), int(self.n_points))


@dataclass(frozen=True)
class SweepRuntimeConfig:
    logger_config: LoggerConfig
    plan: RFSweepPlan
    write_enabled: bool = False

    def validate(self) -> None:
        self.logger_config.validate()
        if not self.write_enabled:
            raise ValueError("RF sweep execution is disabled unless write_enabled is explicitly True.")
        if self.plan.n_points < 2:
            raise ValueError("RF sweep needs at least two points.")
        if self.plan.samples_per_point < 1:
            raise ValueError("samples_per_point must be at least 1.")
        if self.plan.settle_seconds < 0.0 or self.plan.sample_spacing_seconds < 0.0:
            raise ValueError("Timing parameters must be non-negative.")


def preview_lines(plan: RFSweepPlan, initial_rf_pv: Optional[float] = None) -> List[str]:
    rf_points = plan.rf_points_pv()
    delta_points = plan.delta_points_hz()
    lines = [
        "RF PV name: %s" % RF_PV_NAME,
        "Assumed conversion: 1 RF PV unit = 1000 Hz",
        "Current RF PV value: %s" % ("%.6f" % initial_rf_pv if initial_rf_pv is not None else "UNKNOWN"),
        "Sweep center RF PV value: %.6f" % plan.center_rf_pv,
        "Delta range [Hz]: %.3f .. %.3f" % (plan.delta_min_hz, plan.delta_max_hz),
        "Point count: %d" % plan.n_points,
        "Settle time per point: %.3f s" % plan.settle_seconds,
        "Samples per point: %d" % plan.samples_per_point,
        "Sample spacing: %.3f s" % plan.sample_spacing_seconds,
        "",
        "Planned RF writes:",
    ]
    for index, (rf_pv, delta_hz) in enumerate(zip(rf_points, delta_points), start=1):
        lines.append("%2d. put %s -> %.6f    (delta %.3f Hz)" % (index, RF_PV_NAME, rf_pv, delta_hz))
    if plan.restore_initial_rf:
        lines.append("restore %s -> initial RF after the sweep" % RF_PV_NAME)
    return lines


def build_plan_from_hz(center_rf_pv: float, delta_min_hz: float, delta_max_hz: float, n_points: int, settle_seconds: float, samples_per_point: int, sample_spacing_seconds: float) -> RFSweepPlan:
    return RFSweepPlan(
        center_rf_pv=float(center_rf_pv),
        delta_min_hz=float(delta_min_hz),
        delta_max_hz=float(delta_max_hz),
        n_points=int(n_points),
        settle_seconds=float(settle_seconds),
        samples_per_point=int(samples_per_point),
        sample_spacing_seconds=float(sample_spacing_seconds),
    )


def _make_derived_context(baseline_sample: Dict[str, object]) -> Dict[str, object]:
    channels = baseline_sample.get("channels", {})
    return {
        "rf_reference_khz": baseline_sample.get("derived", {}).get("rf_readback"),
        "l4_bpm_reference_mm": {label: channels.get(label, {}).get("value") for label in PRIMARY_L4_BPM_LABELS},
    }


def _sweep_sample_summary(sample: Dict[str, object], all_samples: Sequence[Dict[str, object]]) -> str:
    derived = sample.get("derived", {})
    phase = sample.get("phase", "?")
    rf = derived.get("rf_readback")
    delta = derived.get("delta_l4_bpm_first_order")
    bpm_energy = derived.get("beam_energy_from_bpm_mev")
    alpha_old = derived.get("legacy_alpha0_corrected")
    nonlinear = derived.get("bpm_x_nonlinear_labels") or []

    good_pairs = []
    for item in all_samples:
        if item.get("phase") != "sweep":
            continue
        d = item.get("derived", {}).get("delta_l4_bpm_first_order")
        rf_value = item.get("derived", {}).get("rf_readback")
        if d is None or rf_value is None:
            continue
        good_pairs.append((float(d), float(rf_value)))
    eta = None
    alpha_bpm = None
    if len(good_pairs) >= 3:
        fit = fit_slip_factor([item[0] for item in good_pairs], [item[1] for item in good_pairs])
        eta = fit.get("eta")
        beam_energy_mev = derived.get("beam_energy_from_bpm_mev") or sample.get("channels", {}).get("beam_energy_mev", {}).get("value")
        if beam_energy_mev is not None and eta is not None:
            alpha_bpm = alpha0_from_eta(eta, float(beam_energy_mev))

    parts = [
        "sample %s" % sample.get("sample_index"),
        "phase=%s" % phase,
        "RF=%.6f kHz" % rf if rf is not None else "RF=n/a",
        "δs=%.6e" % delta if delta is not None else "δs=n/a",
        "E_BPM=%.3f MeV" % bpm_energy if bpm_energy is not None else "E_BPM=n/a",
        "α0_old=%.6e" % alpha_old if alpha_old is not None else "α0_old=n/a",
        "η=%.6e" % eta if eta is not None else "η=n/a",
        "α0_BPM=%.6e" % alpha_bpm if alpha_bpm is not None else "α0_BPM=n/a",
    ]
    if nonlinear:
        parts.append("nonlinear_bpms=%s" % ",".join(nonlinear))
    return " | ".join(parts)


def estimate_sweep_session_bytes(specs, plan: RFSweepPlan) -> int:
    sample_count = 2 + int(plan.n_points) * int(plan.samples_per_point)
    return sample_count * estimate_sample_bytes(specs)


def run_rf_sweep_session(runtime_config: SweepRuntimeConfig, adapter=None, progress_callback=None, sample_callback=None) -> Path:
    runtime_config.validate()
    config = runtime_config.logger_config
    lattice, specs = build_specs(config)
    prefix = "ssmb_rf_sweep"
    if config.session_label:
        prefix += "_" + sanitize_label(config.session_label)
    logger = SessionLogger.create(config.output_root, prefix)
    if progress_callback is None:
        def emit(message: str) -> None:
            logger.log(message)
    else:
        def emit(message: str) -> None:
            logger.log(message)
            progress_callback(message)

    if adapter is None:
        adapter = EpicsAdapter(timeout=config.timeout_seconds)

    initial_rf = adapter.get(RF_PV_NAME, None)
    if initial_rf is None:
        raise ValueError("RF PV %s is unavailable." % RF_PV_NAME)
    initial_rf = float(initial_rf)
    emit("Starting write-capable SSMB RF sweep.")
    emit("Initial RF PV value: %.6f" % initial_rf)

    samples: List[Dict[str, object]] = []
    start = time.monotonic()
    sample_index = 0
    plan = runtime_config.plan

    metadata = build_metadata(
        config,
        lattice,
        specs,
        "SSMB RF sweep logger",
        extra={
            "sweep_plan": {
                "center_rf_pv": plan.center_rf_pv,
                "delta_min_hz": plan.delta_min_hz,
                "delta_max_hz": plan.delta_max_hz,
                "n_points": plan.n_points,
                "settle_seconds": plan.settle_seconds,
                "samples_per_point": plan.samples_per_point,
                "sample_spacing_seconds": plan.sample_spacing_seconds,
                "restore_initial_rf": plan.restore_initial_rf,
                "rf_points_pv": plan.rf_points_pv().tolist(),
                "delta_points_hz": plan.delta_points_hz().tolist(),
            },
            "initial_rf_pv": initial_rf,
            "online_analysis": {
                "primary_l4_bpms": list(PRIMARY_L4_BPM_LABELS),
                "purpose": "Live delta_s reconstruction, slip-factor fit, and alpha0 comparison during RF sweep.",
            },
            "safe_mode": False,
            "allow_writes": True,
        },
    )
    estimated_bytes = estimate_sweep_session_bytes(specs, plan)
    disk = disk_usage_summary(config.output_root if config.output_root.exists() else config.output_root.parent)
    metadata["disk_usage_at_start"] = disk
    metadata["estimated_session_size_bytes"] = estimated_bytes
    metadata["write_strategy"] = "incremental_jsonl_with_final_csv"
    metadata["session_status"] = "running"
    logger.write_json("metadata.json", metadata)
    emit("Estimated sweep size: %.2f MB; free space: %.2f GB." % (estimated_bytes / (1024.0 * 1024.0), disk["free_bytes"] / (1024.0 * 1024.0 * 1024.0)))

    session_failed = False
    failure_message = None
    pending_exception: Optional[Exception] = None
    try:
        baseline = capture_sample(
            adapter,
            specs,
            sample_index=sample_index,
            t_rel_s=time.monotonic() - start,
            extra_fields={"phase": "baseline", "target_rf_pv": initial_rf},
        )
        samples.append(baseline)
        logger.append_jsonl("samples.jsonl", baseline)
        if sample_callback is not None:
            sample_callback(baseline)
        derived_context = _make_derived_context(baseline)
        sample_index += 1
        emit("Online analysis sensors: BPMZ3L4RP, BPMZ4L4RP, BPMZ5L4RP, BPMZ6L4RP for delta_s; QPD00ZL4RP for sigma_x/y; tune PVs for cross-checks.")
        emit(_sweep_sample_summary(baseline, samples))

        for point_index, (target_rf, delta_hz) in enumerate(zip(plan.rf_points_pv(), plan.delta_points_hz()), start=1):
            emit("RF sweep point %d/%d: put %s -> %.6f (delta %.3f Hz)" % (point_index, plan.n_points, RF_PV_NAME, target_rf, delta_hz))
            adapter.put(RF_PV_NAME, float(target_rf))
            if plan.settle_seconds > 0.0:
                time.sleep(plan.settle_seconds)
            for sample_slot in range(plan.samples_per_point):
                try:
                    sample = capture_sample(
                        adapter,
                        specs,
                        sample_index=sample_index,
                        t_rel_s=time.monotonic() - start,
                        extra_fields={
                            "phase": "sweep",
                            "sweep_index": point_index - 1,
                            "sample_slot": sample_slot,
                            "target_rf_pv": float(target_rf),
                            "target_delta_hz": float(delta_hz),
                        },
                        derived_context=derived_context,
                    )
                except Exception as exc:
                    emit("Sweep sample %d capture failed: %s" % (sample_index, exc))
                    sample = {
                        "timestamp_epoch_s": time.time(),
                        "t_rel_s": time.monotonic() - start,
                        "sample_index": sample_index,
                        "channels": {},
                        "derived": {},
                        "error": str(exc),
                        "phase": "capture_error",
                        "sweep_index": point_index - 1,
                        "sample_slot": sample_slot,
                        "target_rf_pv": float(target_rf),
                        "target_delta_hz": float(delta_hz),
                    }
                samples.append(sample)
                logger.append_jsonl("samples.jsonl", sample)
                if sample_callback is not None:
                    sample_callback(sample)
                emit(_sweep_sample_summary(samples[-1], samples))
                sample_index += 1
                if sample_slot + 1 < plan.samples_per_point and plan.sample_spacing_seconds > 0.0:
                    time.sleep(plan.sample_spacing_seconds)
    except Exception as exc:
        session_failed = True
        failure_message = str(exc)
        emit("RF sweep failed: %s" % exc)
        pending_exception = exc
    finally:
        if plan.restore_initial_rf:
            emit("Restoring RF PV to %.6f" % initial_rf)
            try:
                adapter.put(RF_PV_NAME, initial_rf)
            except Exception as exc:
                session_failed = True
                if failure_message is None:
                    failure_message = "RF restore failed: %s" % exc
                emit("RF restore failed: %s" % exc)
            if plan.settle_seconds > 0.0:
                time.sleep(plan.settle_seconds)
            try:
                restored = capture_sample(
                    adapter,
                    specs,
                    sample_index=sample_index,
                    t_rel_s=time.monotonic() - start,
                    extra_fields={"phase": "restored", "target_rf_pv": initial_rf},
                    derived_context=derived_context if "derived_context" in locals() else None,
                )
            except Exception as exc:
                emit("Restore sample capture failed: %s" % exc)
                restored = {
                    "timestamp_epoch_s": time.time(),
                    "t_rel_s": time.monotonic() - start,
                    "sample_index": sample_index,
                    "channels": {},
                    "derived": {},
                    "error": str(exc),
                    "phase": "restore_error",
                    "target_rf_pv": initial_rf,
                }
            samples.append(restored)
            logger.append_jsonl("samples.jsonl", restored)
            if sample_callback is not None:
                sample_callback(restored)
    metadata["session_status"] = "failed" if session_failed else "completed"
    if failure_message is not None:
        metadata["failure"] = failure_message
    metadata["partial_sample_count"] = len(samples)
    logger.write_json("metadata.json", metadata)
    session_dir = write_session_outputs(logger, metadata, samples)
    missing_counts = metadata.get("missing_pvs", {}) or {}
    if missing_counts:
        top_missing = sorted(missing_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        logger.log("Missing PV summary: %s" % ", ".join("%s=%d" % (label, count) for label, count in top_missing))
    if pending_exception is not None:
        raise pending_exception
    return session_dir


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write-capable SSMB RF sweep with full logging.")
    parser.add_argument("--center-rf-pv", type=float, required=True, help="Sweep center in RF PV units.")
    parser.add_argument("--delta-min-hz", type=float, required=True, help="Minimum RF offset in Hz.")
    parser.add_argument("--delta-max-hz", type=float, required=True, help="Maximum RF offset in Hz.")
    parser.add_argument("--points", type=int, default=5, help="Number of RF points. Default: 5")
    parser.add_argument("--settle", type=float, default=1.0, help="Settle time after each RF write in seconds.")
    parser.add_argument("--samples-per-point", type=int, default=1, help="Logged samples per RF point.")
    parser.add_argument("--sample-spacing", type=float, default=0.0, help="Spacing between samples at a fixed RF point.")
    parser.add_argument("--duration", type=float, default=60.0, help="Stage 0 style metadata field; not used to stop the sweep.")
    parser.add_argument("--sample-hz", type=float, default=1.0, help="Stage 0 metadata field kept for consistency.")
    parser.add_argument("--timeout", type=float, default=0.5, help="PV read timeout.")
    parser.add_argument("--output-dir", help="Output root.")
    parser.add_argument("--label", default="", help="Short session label.")
    parser.add_argument("--note", default="", help="Operator note stored in metadata.")
    parser.add_argument("--quadrupoles", action="store_true", help="Include quadrupole current/readback candidates from the lattice export.")
    parser.add_argument("--no-sextupoles", action="store_true", help="Skip sextupole current/readback candidates from the lattice export.")
    parser.add_argument("--no-octupoles", action="store_true", help="Skip octupole current/readback candidates from the lattice export.")
    parser.add_argument("--no-ring-bpm-scalars", action="store_true", help="Skip full-ring BPM scalar candidates from the lattice export.")
    parser.add_argument("--no-bpm-scalars", action="store_true", help="Skip candidate scalar BPM readbacks near U125/L4.")
    parser.add_argument("--no-bpm-buffer", action="store_true", help="Skip the BPM waveform/buffer PV.")
    parser.add_argument("--heavy", action="store_true", help="Convenience preset: enable ring BPMs, quadrupoles, sextupoles, and octupoles at the chosen sample rate.")
    parser.add_argument("--allow-writes", action="store_true", help="Required opt-in for any RF write.")
    parser.add_argument("--pv", action="append", default=[], metavar="LABEL=PVNAME")
    parser.add_argument("--optional-pv", action="append", default=[], metavar="LABEL=PVNAME")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    plan = build_plan_from_hz(
        center_rf_pv=args.center_rf_pv,
        delta_min_hz=args.delta_min_hz,
        delta_max_hz=args.delta_max_hz,
        n_points=args.points,
        settle_seconds=args.settle,
        samples_per_point=args.samples_per_point,
        sample_spacing_seconds=args.sample_spacing,
    )
    config = LoggerConfig(
        duration_seconds=args.duration,
        sample_hz=args.sample_hz,
        timeout_seconds=args.timeout,
        output_root=Path(args.output_dir).expanduser().resolve() if args.output_dir else Path.cwd() / ".ssmb_local" / "ssmb_stage0",
        safe_mode=not args.allow_writes,
        allow_writes=args.allow_writes,
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
    runtime_config = SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=args.allow_writes)
    session_dir = run_rf_sweep_session(runtime_config)
    print("SSMB RF sweep log saved to:", session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
