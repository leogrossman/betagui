from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except Exception:  # pragma: no cover - depends on host packages
    plt = None
    MATPLOTLIB_AVAILABLE = False


E_REST_MEV = 0.51099895


def load_samples(session_dir: Path) -> List[Dict[str, object]]:
    path = session_dir / "samples.jsonl"
    samples = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def reconstruct_delta_first_order(
    orbit_by_bpm: Dict[str, float],
    reference_orbit_by_bpm: Dict[str, float],
    dispersion_by_bpm: Dict[str, float],
    weights_by_bpm: Optional[Dict[str, float]] = None,
) -> float:
    numerator = 0.0
    denominator = 0.0
    for bpm_label, dispersion in dispersion_by_bpm.items():
        if bpm_label not in orbit_by_bpm or bpm_label not in reference_orbit_by_bpm:
            continue
        weight = 1.0 if weights_by_bpm is None else float(weights_by_bpm.get(bpm_label, 1.0))
        offset = float(orbit_by_bpm[bpm_label]) - float(reference_orbit_by_bpm[bpm_label])
        numerator += weight * float(dispersion) * offset
        denominator += weight * float(dispersion) * float(dispersion)
    if denominator == 0.0:
        raise ValueError("No usable BPM dispersion entries were provided.")
    return numerator / denominator


def fit_slip_factor(delta_s: Sequence[float], rf_values: Sequence[float]) -> Dict[str, float]:
    delta_array = np.asarray(delta_s, dtype=float)
    rf_array = np.asarray(rf_values, dtype=float)
    if delta_array.size != rf_array.size or delta_array.size < 2:
        raise ValueError("Need at least two matched delta/rf samples.")
    rf_ref = rf_array[0]
    y = (rf_array - rf_ref) / rf_ref
    x = delta_array
    design = np.column_stack((x, np.ones_like(x)))
    coeffs, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    slope = float(coeffs[0])
    intercept = float(coeffs[1])
    return {"eta": -slope, "rf_reference": float(rf_ref), "intercept": intercept}


def alpha0_from_eta(eta: float, beam_energy_mev: float) -> float:
    gamma = float(beam_energy_mev) / E_REST_MEV
    return float(eta) + 1.0 / (gamma * gamma)


def nonlinear_alpha_placeholder(delta_s: Sequence[float], rf_values: Sequence[float]) -> Dict[str, object]:
    return {
        "implemented": False,
        "message": "Higher-order alpha reconstruction is not implemented yet; use this session data for later nonlinear fitting.",
        "sample_count": len(delta_s),
    }


def _extract_scalar_series(samples: Sequence[Dict[str, object]], label: str, derived: bool = False) -> List[Optional[float]]:
    values: List[Optional[float]] = []
    for sample in samples:
        if derived:
            value = sample.get("derived", {}).get(label)
        else:
            value = sample.get("channels", {}).get(label, {}).get("value")
        try:
            values.append(float(value) if value is not None else None)
        except (TypeError, ValueError):
            values.append(None)
    return values


def analyze_session(
    session_dir: Path,
    dispersion_by_bpm: Optional[Dict[str, float]] = None,
    weights_by_bpm: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    samples = load_samples(session_dir)
    if not samples:
        raise ValueError("No samples found in %s" % session_dir)

    analysis: Dict[str, object] = {
        "session_dir": str(session_dir),
        "sample_count": len(samples),
        "rf_series": _extract_scalar_series(samples, "rf_readback"),
        "tune_x_series": _extract_scalar_series(samples, "tune_x_raw"),
        "tune_y_series": _extract_scalar_series(samples, "tune_y_raw"),
        "tune_s_series": _extract_scalar_series(samples, "tune_s_raw"),
        "tune_s_khz_series": _extract_scalar_series(samples, "tune_s_khz", derived=True),
    }

    if dispersion_by_bpm:
        reference = {}
        first_channels = samples[0].get("channels", {})
        for bpm_label in dispersion_by_bpm:
            payload = first_channels.get(bpm_label, {})
            reference[bpm_label] = payload.get("value")
        delta_values = []
        rf_values = []
        for sample in samples:
            orbit = {}
            for bpm_label in dispersion_by_bpm:
                value = sample.get("channels", {}).get(bpm_label, {}).get("value")
                if value is not None:
                    orbit[bpm_label] = value
            try:
                delta_values.append(
                    reconstruct_delta_first_order(
                        orbit_by_bpm=orbit,
                        reference_orbit_by_bpm=reference,
                        dispersion_by_bpm=dispersion_by_bpm,
                        weights_by_bpm=weights_by_bpm,
                    )
                )
                rf_values.append(float(sample.get("channels", {}).get("rf_readback", {}).get("value")))
            except Exception:
                continue
        analysis["delta_s_series"] = delta_values
        if len(delta_values) >= 2 and len(delta_values) == len(rf_values):
            slip = fit_slip_factor(delta_values, rf_values)
            analysis["slip_factor_fit"] = slip
            first_energy = _extract_scalar_series(samples, "beam_energy_mev")[0]
            if first_energy is not None:
                analysis["alpha0_from_eta"] = alpha0_from_eta(slip["eta"], first_energy)
            analysis["nonlinear_alpha_fit"] = nonlinear_alpha_placeholder(delta_values, rf_values)
    return analysis


def write_analysis_report(session_dir: Path, analysis: Dict[str, object]) -> Dict[str, Path]:
    out_dir = session_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paths = {"json": json_path}
    if MATPLOTLIB_AVAILABLE:
        rf_series = [value for value in analysis.get("rf_series", []) if value is not None]
        tune_s_series = [value for value in analysis.get("tune_s_khz_series", []) if value is not None]
        figure, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=False)
        axes[0].plot(range(len(rf_series)), rf_series, linewidth=1.5)
        axes[0].set_title("RF readback")
        axes[0].set_ylabel("PV units")
        axes[0].grid(True, alpha=0.3)
        axes[1].plot(range(len(tune_s_series)), tune_s_series, linewidth=1.5)
        axes[1].set_title("Synchrotron monitor")
        axes[1].set_ylabel("kHz")
        axes[1].grid(True, alpha=0.3)
        axes[1].set_xlabel("Sample index")
        figure.tight_layout()
        plot_path = out_dir / "basic_timeseries.png"
        figure.savefig(plot_path, dpi=140)
        plt.close(figure)
        paths["plot"] = plot_path
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "Analyze a Stage 0 SSMB logging session.")
    parser.add_argument("session_dir", help="Path to a Stage 0 session directory.")
    parser.add_argument("--dispersion-json", help="JSON mapping of BPM label to Dx for first-order delta reconstruction.")
    parser.add_argument("--weights-json", help="Optional JSON mapping of BPM label to fit weight.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    dispersion = json.loads(Path(args.dispersion_json).read_text()) if args.dispersion_json else None
    weights = json.loads(Path(args.weights_json).read_text()) if args.weights_json else None
    analysis = analyze_session(Path(args.session_dir), dispersion_by_bpm=dispersion, weights_by_bpm=weights)
    paths = write_analysis_report(Path(args.session_dir), analysis)
    print("Analysis written to:")
    for key, path in paths.items():
        print(" - %s: %s" % (key, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
