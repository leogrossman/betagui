from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

from .analyze_session import _linear_fit, alpha0_from_eta, fit_slip_factor

SPEED_OF_LIGHT_M_PER_S = 299792458.0
MLS_CIRCUMFERENCE_M = 48.0
RF_SWEEP_ACTIVE_THRESHOLD_KHZ = 0.002
RF_SWEEP_ACTIVE_MIN_POINTS = 4
BUMP_CORRECTOR_ACTIVE_THRESHOLD_A = 0.002
ALPHA_CONTAMINATION_THRESHOLD = 5.0e-5
OSCILLATION_MIN_POINTS = 32
OSCILLATION_MIN_CYCLES_FOR_MEDIUM = 1.5
OSCILLATION_MIN_CYCLES_FOR_HIGH = 2.5
OSCILLATION_MAX_LAG_FRACTION = 0.25
TEMPERATURE_UNSTABLE_THRESHOLD_C = 0.5

TREND_DEFINITIONS: Dict[str, Dict[str, object]] = {
    "rf_offset_hz": {"label": "Δf_RF [Hz]", "color": "#1e88e5"},
    "rf_readback_499mhz_khz": {"label": "RF rdFrq499 [kHz]", "color": "#3949ab"},
    "cavity_voltage_kv": {"label": "U_cav [kV]", "color": "#c62828"},
    "delta_s": {"label": "δₛ", "color": "#43a047"},
    "beam_energy_mev": {"label": "E_BPM [MeV]", "color": "#00897b"},
    "sigma_delta": {"label": "σδ", "color": "#6d4c41"},
    "legacy_alpha0": {"label": "α₀ legacy", "color": "#ef6c00"},
    "bpm_alpha0": {"label": "α₀ BPM", "color": "#8e24aa"},
    "alpha_difference": {"label": "α₀ legacy - BPM", "color": "#c62828"},
    "tune_y": {"label": "Qᵧ", "color": "#3949ab"},
    "tune_s": {"label": "Qₛ", "color": "#5e35b1"},
    "p1_h1_ampl": {"label": "P1 live", "color": "#00acc1"},
    "p1_h1_ampl_avg": {"label": "P1 avg", "color": "#8e24aa"},
    "p1_h1_ampl_dev": {"label": "P1 std", "color": "#7b1fa2"},
    "p3_h1_ampl": {"label": "P3 live", "color": "#f4511e"},
    "p3_h1_ampl_avg": {"label": "P3 avg", "color": "#fb8c00"},
    "qpd_l4_center_x_avg_um": {"label": "QPD00 X center avg [um]", "color": "#6a1b9a"},
    "qpd_l2_center_x_avg_um": {"label": "QPD01 X center avg [um]", "color": "#8e24aa"},
    "qpd_l4_sigma_x_mm": {"label": "QPD00 σx [mm]", "color": "#7b1fa2"},
    "qpd_l4_sigma_y_mm": {"label": "QPD00 σy [mm]", "color": "#ab47bc"},
    "qpd_l2_sigma_x_mm": {"label": "QPD01 σx [mm]", "color": "#5e35b1"},
    "qpd_l2_sigma_y_mm": {"label": "QPD01 σy [mm]", "color": "#4527a0"},
    "climate_kw13_return_temp_c": {"label": "KW13 return temp [C]", "color": "#00838f"},
    "climate_sr_temp_c": {"label": "SR temp [C]", "color": "#00695c"},
    "climate_sr_temp1_c": {"label": "SR temp1 [C]", "color": "#2e7d32"},
    "beam_current": {"label": "Beam current [mA]", "color": "#2e7d32"},
    "bump_strength_a": {"label": "max |I_bump| [A]", "color": "#ad1457"},
    "bump_bpm_avg_mm": {"label": "⟨x_bump BPM⟩ [mm]", "color": "#00838f"},
    "bump_orbit_error_mm": {"label": "x_ref - ⟨x⟩ [mm]", "color": "#c2185b"},
    "bump_bpm_k1_mm": {"label": "BPMZ1K1 [mm]", "color": "#1565c0"},
    "bump_bpm_l2_mm": {"label": "BPMZ1L2 [mm]", "color": "#0d47a1"},
    "bump_bpm_k3_mm": {"label": "BPMZ1K3 [mm]", "color": "#1976d2"},
    "bump_bpm_l4_mm": {"label": "BPMZ1L4 [mm]", "color": "#42a5f5"},
}

OSCILLATION_CANDIDATE_KEYS = (
    "bump_orbit_error_mm",
    "bump_bpm_avg_mm",
    "bump_strength_a",
    "rf_offset_hz",
    "delta_s",
    "beam_energy_mev",
    "sigma_delta",
    "legacy_alpha0",
    "bpm_alpha0",
    "alpha_difference",
    "beam_current",
    "qpd_l4_center_x_avg_um",
    "qpd_l2_center_x_avg_um",
    "climate_kw13_return_temp_c",
    "climate_sr_temp_c",
    "climate_sr_temp1_c",
    "tune_y",
    "tune_s",
    "p3_h1_ampl_avg",
)


def _valid_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tune_period_seconds(tune_value) -> Optional[float]:
    tune = _valid_float(tune_value)
    if tune is None or tune <= 0.0:
        return None
    revolution_period = MLS_CIRCUMFERENCE_M / SPEED_OF_LIGHT_M_PER_S
    return revolution_period / tune


def _fmt_duration(value) -> str:
    seconds = _valid_float(value)
    if seconds is None:
        return "n/a"
    abs_s = abs(seconds)
    if abs_s >= 60.0:
        return "%.3f min" % (seconds / 60.0)
    if abs_s >= 1.0:
        return "%.3f s" % seconds
    if abs_s >= 1.0e-3:
        return "%.3f ms" % (seconds * 1.0e3)
    if abs_s >= 1.0e-6:
        return "%.3f µs" % (seconds * 1.0e6)
    return "%.3f ns" % (seconds * 1.0e9)


def _resonance_mismatch(observed_period_s: Optional[float], reference_period_s: Optional[float]) -> Optional[float]:
    observed = _valid_float(observed_period_s)
    reference = _valid_float(reference_period_s)
    if observed is None or reference is None or observed <= 0.0 or reference <= 0.0:
        return None
    return observed / reference


def _estimate_sample_dt_seconds(samples: Sequence[Dict[str, object]]) -> Optional[float]:
    timestamps = []
    for sample in samples:
        ts = _valid_float(sample.get("timestamp_epoch_s"))
        if ts is not None:
            timestamps.append(ts)
    if len(timestamps) >= 2:
        diffs = [b - a for a, b in zip(timestamps[:-1], timestamps[1:]) if b > a]
        if diffs:
            return float(np.median(np.asarray(diffs, dtype=float)))
    indices = []
    for sample in samples:
        idx = _valid_float(sample.get("sample_index"))
        if idx is not None:
            indices.append(idx)
    if len(indices) >= 2:
        return 1.0
    return None


def _extract_series(samples: Sequence[Dict[str, object]], key: str) -> List[Optional[float]]:
    series: List[Optional[float]] = []
    for sample in samples:
        derived = sample.get("derived", {})
        channels = sample.get("channels", {})
        if key in ("bump_strength_a", "bump_bpm_avg_mm", "bump_orbit_error_mm"):
            bump = _summarize_bump_state(channels)
            if key == "bump_strength_a":
                series.append(_valid_float(bump.get("max_abs_corrector_a")))
            elif key == "bump_bpm_avg_mm":
                series.append(_valid_float(bump.get("bpm_avg_mm")))
            else:
                series.append(_valid_float(bump.get("orbit_error_mm")))
        elif key in derived:
            series.append(_valid_float(derived.get(key)))
        elif key in channels:
            series.append(_valid_float(channels.get(key, {}).get("value")))
        else:
            series.append(None)
    return series


def _dominant_period(values: Sequence[Optional[float]], dt_s: Optional[float]) -> Dict[str, object]:
    dt = _valid_float(dt_s)
    if dt is None or dt <= 0.0:
        return {"available": False, "reason": "missing_dt"}
    valid = [(idx, float(value)) for idx, value in enumerate(values) if isinstance(value, (int, float))]
    if len(valid) < OSCILLATION_MIN_POINTS:
        return {"available": False, "reason": "not_enough_points", "sample_count": len(valid)}
    indices = np.asarray([idx for idx, _ in valid], dtype=float)
    y = np.asarray([value for _idx, value in valid], dtype=float)
    if np.nanstd(y) <= 0.0:
        return {"available": False, "reason": "flat_signal", "sample_count": len(valid)}
    if len(y) >= 3:
        coeffs = np.polyfit(indices, y, 1)
        y = y - np.polyval(coeffs, indices)
    else:
        y = y - np.mean(y)
    window = np.hanning(len(y)) if len(y) >= 8 else np.ones(len(y))
    y_windowed = y * window
    spectrum = np.abs(np.fft.rfft(y_windowed)) ** 2
    freqs = np.fft.rfftfreq(len(y_windowed), d=dt)
    total_span_s = len(y_windowed) * dt
    valid_mask = freqs > 0.0
    valid_mask &= freqs >= (1.0 / max(total_span_s * 0.9, dt))
    valid_mask &= freqs <= (1.0 / max(4.0 * dt, dt))
    if not np.any(valid_mask):
        return {"available": False, "reason": "no_valid_band", "sample_count": len(valid)}
    valid_indices = np.where(valid_mask)[0]
    peak_idx = valid_indices[int(np.argmax(spectrum[valid_indices]))]
    peak_power = float(spectrum[peak_idx])
    band_power = float(np.sum(spectrum[valid_indices]))
    frequency_hz = float(freqs[peak_idx])
    if frequency_hz <= 0.0:
        return {"available": False, "reason": "invalid_frequency", "sample_count": len(valid)}
    period_s = 1.0 / frequency_hz
    cycles_seen = total_span_s / period_s if period_s > 0.0 else 0.0
    confidence = peak_power / band_power if band_power > 0.0 else 0.0
    return {
        "available": True,
        "sample_count": len(valid),
        "period_s": period_s,
        "frequency_hz": frequency_hz,
        "frequency_mhz": frequency_hz * 1.0e3,
        "peak_power_fraction": confidence,
        "cycles_seen": cycles_seen,
        "span_s": total_span_s,
    }


def _align_valid_pairs(a_values: Sequence[Optional[float]], b_values: Sequence[Optional[float]]):
    pairs = [(float(a), float(b)) for a, b in zip(a_values, b_values) if isinstance(a, (int, float)) and isinstance(b, (int, float))]
    if len(pairs) < 4:
        return None, None
    a = np.asarray([item[0] for item in pairs], dtype=float)
    b = np.asarray([item[1] for item in pairs], dtype=float)
    return a, b


def _harmonic_similarity(period_a_s: Optional[float], period_b_s: Optional[float]) -> float:
    pa = _valid_float(period_a_s)
    pb = _valid_float(period_b_s)
    if pa is None or pb is None or pa <= 0.0 or pb <= 0.0:
        return 0.0
    ratio = pa / pb
    harmonic_ratios = (1.0, 2.0, 0.5, 3.0, 1.0 / 3.0)
    best = min(abs(math.log(ratio / target)) for target in harmonic_ratios)
    return max(0.0, 1.0 - best / math.log(2.0))


def _autocorr_period(values: Sequence[Optional[float]], dt_s: Optional[float]) -> Dict[str, object]:
    dt = _valid_float(dt_s)
    if dt is None or dt <= 0.0:
        return {"available": False, "reason": "missing_dt"}
    valid = np.asarray([float(value) for value in values if isinstance(value, (int, float))], dtype=float)
    if valid.size < OSCILLATION_MIN_POINTS:
        return {"available": False, "reason": "not_enough_points", "sample_count": int(valid.size)}
    if np.std(valid) <= 0.0:
        return {"available": False, "reason": "flat_signal", "sample_count": int(valid.size)}
    if valid.size >= 3:
        x = np.arange(valid.size, dtype=float)
        coeffs = np.polyfit(x, valid, 1)
        valid = valid - np.polyval(coeffs, x)
    else:
        valid = valid - np.mean(valid)
    ac = np.correlate(valid, valid, mode="full")[valid.size - 1 :]
    if ac.size < 3 or ac[0] <= 0.0:
        return {"available": False, "reason": "bad_autocorr", "sample_count": int(valid.size)}
    ac = ac / ac[0]
    min_lag = max(1, int(round(4.0 / dt)))
    max_lag = max(min_lag + 1, int(valid.size * 0.75))
    search = ac[min_lag:max_lag]
    if search.size < 3:
        return {"available": False, "reason": "search_window_small", "sample_count": int(valid.size)}
    peak_rel = None
    peak_val = None
    for idx in range(1, search.size - 1):
        if search[idx] > search[idx - 1] and search[idx] >= search[idx + 1]:
            if peak_val is None or search[idx] > peak_val:
                peak_val = float(search[idx])
                peak_rel = idx
    if peak_rel is None:
        peak_rel = int(np.argmax(search))
        peak_val = float(search[peak_rel])
    lag = min_lag + peak_rel
    return {
        "available": True,
        "period_s": lag * dt,
        "peak_autocorr": peak_val,
        "sample_count": int(valid.size),
    }


def analyze_p1_oscillation(samples: Sequence[Dict[str, object]], extra_candidate_keys: Optional[Sequence[str]] = None) -> Dict[str, object]:
    dt_s = _estimate_sample_dt_seconds(samples)
    p1_values = _extract_series(samples, "p1_h1_ampl_avg")
    p1_period = _dominant_period(p1_values, dt_s)
    p1_autocorr = _autocorr_period(p1_values, dt_s)
    candidate_keys = list(OSCILLATION_CANDIDATE_KEYS)
    for key in extra_candidate_keys or ():
        if key and key not in candidate_keys:
            candidate_keys.append(key)
    valid_p1_count = len([value for value in p1_values if isinstance(value, (int, float))])
    if valid_p1_count < 4:
        return {
            "available": False,
            "provisional": False,
            "reason": p1_period.get("reason", "insufficient_data"),
            "dt_s": dt_s,
            "sample_count": valid_p1_count,
            "candidate_count": 0,
            "checked_candidate_keys": candidate_keys,
            "candidates": [],
        }
    p1_array = np.asarray([value for value in p1_values if isinstance(value, (int, float))], dtype=float)
    p1_drift_fit = None
    if dt_s is not None and len(p1_array) >= 3:
        x = np.arange(len(p1_array), dtype=float) * dt_s
        p1_drift_fit = _linear_fit(x.tolist(), p1_array.tolist())
    candidates = []
    for key in candidate_keys:
        values = _extract_series(samples, key)
        a, b = _align_valid_pairs(p1_values, values)
        if a is None or b is None:
            continue
        if np.std(a) <= 0.0 or np.std(b) <= 0.0:
            continue
        corr = float(np.corrcoef(a, b)[0, 1])
        az = (a - np.mean(a)) / np.std(a)
        bz = (b - np.mean(b)) / np.std(b)
        max_lag = max(1, int(len(az) * OSCILLATION_MAX_LAG_FRACTION))
        corr_seq = np.correlate(az, bz, mode="full") / len(az)
        center = len(corr_seq) // 2
        start = max(0, center - max_lag)
        stop = min(len(corr_seq), center + max_lag + 1)
        local = corr_seq[start:stop]
        best_local_idx = int(np.argmax(np.abs(local)))
        best_corr = float(local[best_local_idx])
        best_lag_samples = (start + best_local_idx) - center
        candidate_period = _dominant_period(values, dt_s)
        candidate_autocorr = _autocorr_period(values, dt_s)
        fft_similarity = _harmonic_similarity(candidate_period.get("period_s"), p1_period.get("period_s"))
        ac_similarity = _harmonic_similarity(candidate_autocorr.get("period_s"), p1_autocorr.get("period_s"))
        period_similarity = max(fft_similarity, ac_similarity)
        has_period = bool(p1_period.get("available"))
        period_weight = 0.25 if has_period else 0.05
        corr_weight = 0.35 if has_period else 0.45
        xcorr_weight = 0.25 if has_period else 0.35
        auto_weight = 0.15
        score = corr_weight * abs(corr) + xcorr_weight * abs(best_corr) + period_weight * period_similarity + auto_weight * abs(_valid_float(candidate_autocorr.get("peak_autocorr")) or 0.0)
        candidates.append(
            {
                "key": key,
                "label": trend_definitions().get(key, {}).get("label", key),
                "pearson_r": corr,
                "xcorr_peak": best_corr,
                "lag_samples": best_lag_samples,
                "lag_s": None if dt_s is None else best_lag_samples * dt_s,
                "candidate_period_s": candidate_period.get("period_s") if candidate_period.get("available") else None,
                "candidate_autocorr_period_s": candidate_autocorr.get("period_s") if candidate_autocorr.get("available") else None,
                "harmonic_similarity": period_similarity,
                "score": score,
                "pair_count": len(a),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    cycles_seen = _valid_float(p1_period.get("cycles_seen")) or 0.0
    certainty = "very_low"
    provisional = not bool(p1_period.get("available"))
    if p1_period.get("available"):
        certainty = "low"
        if cycles_seen >= OSCILLATION_MIN_CYCLES_FOR_HIGH and (p1_period.get("peak_power_fraction") or 0.0) >= 0.35:
            certainty = "high"
        elif cycles_seen >= OSCILLATION_MIN_CYCLES_FOR_MEDIUM and (p1_period.get("peak_power_fraction") or 0.0) >= 0.2:
            certainty = "medium"
    elif valid_p1_count >= 8 and candidates:
        top_score = _valid_float((candidates[0] or {}).get("score")) or 0.0
        certainty = "low" if top_score >= 0.45 else "very_low"
    top = candidates[0] if candidates else None
    return {
        "available": bool(candidates) or bool(p1_period.get("available")),
        "provisional": provisional,
        "reason": None if (bool(candidates) or bool(p1_period.get("available"))) else p1_period.get("reason", "insufficient_data"),
        "dt_s": dt_s,
        "sample_count": max(valid_p1_count, p1_period.get("sample_count") or 0),
        "dominant_period_s": p1_period.get("period_s") if p1_period.get("available") else None,
        "autocorr_period_s": p1_autocorr.get("period_s") if p1_autocorr.get("available") else None,
        "dominant_frequency_hz": p1_period.get("frequency_hz") if p1_period.get("available") else None,
        "dominant_frequency_mhz": p1_period.get("frequency_mhz") if p1_period.get("available") else None,
        "peak_power_fraction": p1_period.get("peak_power_fraction") if p1_period.get("available") else None,
        "autocorr_peak": p1_autocorr.get("peak_autocorr") if p1_autocorr.get("available") else None,
        "cycles_seen": cycles_seen,
        "span_s": p1_period.get("span_s") if p1_period.get("available") else (None if dt_s is None else valid_p1_count * dt_s),
        "certainty": certainty,
        "top_candidate": top,
        "candidate_count": len(candidates),
        "candidates": candidates[:8],
        "p1_drift_slope_per_s": None if p1_drift_fit is None else p1_drift_fit.get("slope"),
        "checked_candidate_keys": candidate_keys,
    }


def estimate_monitor_history_bytes(samples: Sequence[Dict[str, object]]) -> int:
    total = 0
    for sample in samples:
        total += 512
        total += 160 * len(sample.get("channels", {}))
        total += 64 * len(sample.get("derived", {}))
    return total


def detect_rf_sweep_active(samples: Sequence[Dict[str, object]]) -> Dict[str, object]:
    rf_values = []
    for sample in samples:
        rf_value = _valid_float(sample.get("derived", {}).get("rf_readback"))
        if rf_value is not None:
            rf_values.append(rf_value)
    if len(rf_values) < RF_SWEEP_ACTIVE_MIN_POINTS:
        return {"active": False, "reason": "not_enough_points", "rf_span_khz": 0.0}
    rf_span = max(rf_values) - min(rf_values)
    return {
        "active": rf_span >= RF_SWEEP_ACTIVE_THRESHOLD_KHZ,
        "reason": "rf_span" if rf_span >= RF_SWEEP_ACTIVE_THRESHOLD_KHZ else "span_too_small",
        "rf_span_khz": rf_span,
    }


def summarize_live_monitor(
    samples: Sequence[Dict[str, object]],
    extra_candidate_keys: Optional[Sequence[str]] = None,
    include_oscillation: bool = True,
    include_extended: bool = True,
) -> Dict[str, object]:
    latest = samples[-1] if samples else {}
    derived = latest.get("derived", {})
    channels = latest.get("channels", {})
    bump = _summarize_bump_state(channels)
    history_bytes = estimate_monitor_history_bytes(samples)
    dt_estimate = _estimate_sample_dt_seconds(samples)
    summary: Dict[str, object] = {
        "current": {
            "rf_readback_khz": _valid_float(derived.get("rf_readback")),
            "rf_readback_499mhz_khz": _valid_float(channels.get("rf_readback_499mhz", {}).get("value")),
            "rf_offset_hz": _valid_float(derived.get("rf_offset_hz")),
            "delta_l4_bpm_first_order": _valid_float(derived.get("delta_l4_bpm_first_order")),
            "beam_energy_from_bpm_mev": _valid_float(derived.get("beam_energy_from_bpm_mev")),
            "qpd_l4_sigma_delta_first_order": _valid_float(derived.get("qpd_l4_sigma_delta_first_order")),
            "qpd_l4_sigma_energy_mev": _valid_float(derived.get("qpd_l4_sigma_energy_mev")),
            "legacy_alpha0_corrected": _valid_float(derived.get("legacy_alpha0_corrected")),
            "tune_x_unitless": _valid_float(derived.get("tune_x_unitless")),
            "tune_y_unitless": _valid_float(derived.get("tune_y_unitless")),
            "tune_s_unitless": _valid_float(derived.get("tune_s_unitless")),
            "tune_x_period_s": _tune_period_seconds(derived.get("tune_x_unitless")),
            "tune_y_period_s": _tune_period_seconds(derived.get("tune_y_unitless")),
            "tune_s_period_s": _tune_period_seconds(derived.get("tune_s_unitless")),
            "tune_s_khz": _valid_float(derived.get("tune_s_khz")),
            "beam_current": _valid_float(channels.get("beam_current", {}).get("value")),
            "beam_current_scope": _valid_float(channels.get("beam_current_scope", {}).get("value")),
            "qpd_l4_sigma_x_mm": _valid_float(derived.get("qpd_l4_sigma_x_mm")),
            "qpd_l4_sigma_y_mm": _valid_float(derived.get("qpd_l4_sigma_y_mm")),
            "p1_h1_ampl": _valid_float(channels.get("p1_h1_ampl", {}).get("value")),
            "p1_h1_ampl_avg": _valid_float(channels.get("p1_h1_ampl_avg", {}).get("value")),
            "p1_h1_ampl_dev": _valid_float(channels.get("p1_h1_ampl_dev", {}).get("value")),
            "p3_h1_ampl": _valid_float(channels.get("p3_h1_ampl", {}).get("value")),
            "p3_h1_ampl_avg": _valid_float(channels.get("p3_h1_ampl_avg", {}).get("value")),
            "qpd_l4_center_x_avg_um": _valid_float(channels.get("qpd_l4_center_x_avg_um", {}).get("value")),
            "qpd_l2_center_x_avg_um": _valid_float(channels.get("qpd_l2_center_x_avg_um", {}).get("value")),
            "climate_kw13_return_temp_c": _valid_float(channels.get("climate_kw13_return_temp_c", {}).get("value")),
            "climate_sr_temp_c": _valid_float(channels.get("climate_sr_temp_c", {}).get("value")),
            "climate_sr_temp1_c": _valid_float(channels.get("climate_sr_temp1_c", {}).get("value")),
            "nonlinear_bpms": list(derived.get("bpm_x_nonlinear_labels") or []),
            "bump_bpm_avg_mm": bump.get("bpm_avg_mm"),
            "bump_orbit_error_mm": bump.get("orbit_error_mm"),
            "bump_feedback_ref_mm": bump.get("reference_mm"),
            "bump_feedback_gain": bump.get("gain"),
            "bump_feedback_deadband_mm": bump.get("deadband"),
            "bump_step_estimate": bump.get("step_estimate"),
            "bump_bpm_k1_mm": bump.get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_k1"),
            "bump_bpm_l2_mm": bump.get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_l2"),
            "bump_bpm_k3_mm": bump.get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_k3"),
            "bump_bpm_l4_mm": bump.get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_l4"),
        },
        "bump_state": bump,
        "what_can_be_measured_now": [
            "Passive readout: tunes, synchrotron monitor, beam current, orbit BPMs, QPD beam-size proxies, bump states, cavity voltage, beam energy readback.",
            "Passive readout of coherent-light observables P1 and P3 from the scope channels.",
            "Passive readout of SR-camera center drifts and environmental temperatures that may correlate with slow P1 motion.",
            "From passive L4 BPM orbit: first-order delta_s and BPM-based beam energy shift relative to the monitor baseline.",
            "From QPD00ZL4RP sigma_x: first-order momentum spread proxy and corresponding sigma_E estimate.",
            "From the 4-corrector bump PVs: whether the L4 bump is active, and whether bump feedback is enabled.",
        ],
        "what_needs_rf_sweep": [
            "Slip factor eta from fitted RF-vs-delta_s slope.",
            "Alpha0 from alpha0 = eta + 1/gamma^2 using reconstructed delta_s rather than RF alone.",
            "Tune slopes versus delta_s as chromaticity cross-checks in x, y, and synchrotron channels.",
            "P1 and P3 versus f_RF or versus delta_s as the key SSMB observables during the sweep.",
        ],
        "monitor_health": {
            "sample_count": len(samples),
            "buffer_span_s": None if len(samples) < 2 or dt_estimate is None else dt_estimate * max(0, len(samples) - 1),
            "approx_memory_bytes": history_bytes,
        },
    }

    sweep_state = detect_rf_sweep_active(samples) if include_extended else {"active": False, "reason": "disabled_for_fast_monitor_path", "rf_span_khz": 0.0}
    summary["rf_sweep_detection"] = sweep_state
    sweep_metrics: Dict[str, object] = {"available": False}

    delta_series = []
    rf_series = []
    qx_series = []
    qy_series = []
    qs_series = []
    p1_series = []
    p1_avg_series = []
    p3_series = []
    bump_strength_series = []
    bump_error_series = []
    for sample in samples:
        d = _valid_float(sample.get("derived", {}).get("delta_l4_bpm_first_order"))
        rf = _valid_float(sample.get("derived", {}).get("rf_readback"))
        qx = _valid_float(sample.get("derived", {}).get("tune_x_unitless"))
        qy = _valid_float(sample.get("derived", {}).get("tune_y_unitless"))
        qs = _valid_float(sample.get("derived", {}).get("tune_s_unitless"))
        p1 = _valid_float(sample.get("channels", {}).get("p1_h1_ampl", {}).get("value"))
        p1_avg = _valid_float(sample.get("channels", {}).get("p1_h1_ampl_avg", {}).get("value"))
        p3 = _valid_float(sample.get("channels", {}).get("p3_h1_ampl", {}).get("value"))
        bump_state_sample = _summarize_bump_state(sample.get("channels", {}))
        bump_strength = _valid_float(bump_state_sample.get("max_abs_corrector_a"))
        bump_error = _valid_float(bump_state_sample.get("orbit_error_mm"))
        if bump_strength is not None:
            bump_strength_series.append((bump_strength, p1_avg))
        if bump_error is not None:
            bump_error_series.append((bump_error, p1_avg))
        if d is not None and rf is not None:
            delta_series.append(d)
            rf_series.append(rf)
            qx_series.append((d, qx))
            qy_series.append((d, qy))
            qs_series.append((d, qs))
            p1_series.append((d, p1, rf))
            p1_avg_series.append((d, p1_avg, rf))
            p3_series.append((d, p3, rf))
    sigma_x_delta = []
    qpd00_center_delta = []
    qpd01_center_delta = []
    beam_current_delta = []
    if include_extended and len(delta_series) >= 3 and sweep_state["active"]:
        for sample in samples:
            d = _valid_float(sample.get("derived", {}).get("delta_l4_bpm_first_order"))
            if d is None:
                continue
            sigma_x = _valid_float(sample.get("derived", {}).get("qpd_l4_sigma_x_mm"))
            qpd00_center = _valid_float(sample.get("channels", {}).get("qpd_l4_center_x_avg_um", {}).get("value"))
            qpd01_center = _valid_float(sample.get("channels", {}).get("qpd_l2_center_x_avg_um", {}).get("value"))
            beam_current = _valid_float(sample.get("channels", {}).get("beam_current", {}).get("value"))
            if sigma_x is not None:
                sigma_x_delta.append((d, sigma_x))
            if qpd00_center is not None:
                qpd00_center_delta.append((d, qpd00_center))
            if qpd01_center is not None:
                qpd01_center_delta.append((d, qpd01_center))
            if beam_current is not None:
                beam_current_delta.append((d, beam_current))
        slip = fit_slip_factor(delta_series, rf_series)
        beam_energy_mev = _valid_float(channels.get("beam_energy_mev", {}).get("value"))
        legacy_alpha = _valid_float(derived.get("legacy_alpha0_corrected"))
        alpha_bpm = alpha0_from_eta(slip["eta"], beam_energy_mev) if beam_energy_mev is not None else None
        sweep_metrics = {
            "available": True,
            "phase_slip_factor_eta": slip["eta"],
            "alpha0_from_bpm_eta": alpha_bpm,
            "rf_reference_khz": slip["rf_reference"],
            "qx_vs_delta": _linear_fit([x for x, y in qx_series if y is not None], [y for _x, y in qx_series if y is not None]),
            "qy_vs_delta": _linear_fit([x for x, y in qy_series if y is not None], [y for _x, y in qy_series if y is not None]),
            "qs_vs_delta": _linear_fit([x for x, y in qs_series if y is not None], [y for _x, y in qs_series if y is not None]),
            "sample_count": len(delta_series),
            "legacy_alpha0_current": legacy_alpha,
            "alpha0_difference": None if legacy_alpha is None or alpha_bpm is None else legacy_alpha - alpha_bpm,
            "p1_vs_delta": _linear_fit([x for x, y, _rf in p1_series if y is not None], [y for _x, y, _rf in p1_series if y is not None]),
            "p1_avg_vs_delta": _linear_fit([x for x, y, _rf in p1_avg_series if y is not None], [y for _x, y, _rf in p1_avg_series if y is not None]),
            "p3_vs_delta": _linear_fit([x for x, y, _rf in p3_series if y is not None], [y for _x, y, _rf in p3_series if y is not None]),
            "p1_vs_rf": _linear_fit([rf for _x, y, rf in p1_series if y is not None], [y for _x, y, rf in p1_series if y is not None]),
            "p1_avg_vs_rf": _linear_fit([rf for _x, y, rf in p1_avg_series if y is not None], [y for _x, y, rf in p1_avg_series if y is not None]),
            "p3_vs_rf": _linear_fit([rf for _x, y, rf in p3_series if y is not None], [y for _x, y, rf in p3_series if y is not None]),
            "sigma_x_vs_delta": _linear_fit([x for x, y in sigma_x_delta], [y for _x, y in sigma_x_delta]) if len(sigma_x_delta) >= 2 else None,
            "qpd00_center_vs_delta": _linear_fit([x for x, y in qpd00_center_delta], [y for _x, y in qpd00_center_delta]) if len(qpd00_center_delta) >= 2 else None,
            "qpd01_center_vs_delta": _linear_fit([x for x, y in qpd01_center_delta], [y for _x, y in qpd01_center_delta]) if len(qpd01_center_delta) >= 2 else None,
            "beam_current_vs_delta": _linear_fit([x for x, y in beam_current_delta], [y for _x, y in beam_current_delta]) if len(beam_current_delta) >= 2 else None,
        }
    summary["rf_sweep_metrics"] = sweep_metrics
    summary["bump_monitor"] = {
        "feedback_active": bool(bump.get("active")),
        "quality_score": _bump_quality_score(summary),
        "p1_avg_vs_bump_strength": _linear_fit(
            [x for x, y in bump_strength_series if y is not None],
            [y for _x, y in bump_strength_series if y is not None],
        ) if include_extended and len([1 for _x, y in bump_strength_series if y is not None]) >= 2 else None,
        "p1_avg_vs_bump_error": _linear_fit(
            [x for x, y in bump_error_series if y is not None],
            [y for _x, y in bump_error_series if y is not None],
        ) if include_extended and len([1 for _x, y in bump_error_series if y is not None]) >= 2 else None,
    }
    summary["environment_monitor"] = {
        "p1_avg_vs_kw13_temp": _fit_channel_against_p1avg(samples, "climate_kw13_return_temp_c") if include_extended else None,
        "p1_avg_vs_sr_temp": _fit_channel_against_p1avg(samples, "climate_sr_temp_c") if include_extended else None,
        "p1_avg_vs_sr_temp1": _fit_channel_against_p1avg(samples, "climate_sr_temp1_c") if include_extended else None,
        "p1_avg_vs_qpd00_center": _fit_channel_against_p1avg(samples, "qpd_l4_center_x_avg_um") if include_extended else None,
        "p1_avg_vs_qpd01_center": _fit_channel_against_p1avg(samples, "qpd_l2_center_x_avg_um") if include_extended else None,
    }
    summary["temperature_state"] = _summarize_temperature_state(summary)
    summary["alpha_assessment"] = assess_alpha_monitor(summary) if include_extended else {
        "legacy_alpha0": (summary.get("current") or {}).get("legacy_alpha0_corrected"),
        "bpm_alpha0": None,
        "difference": None,
        "contamination_likely": False,
        "message": "Extended alpha/slip-factor fitting is deferred in the fast live-monitor path. Open the study windows for the full fit chain.",
        "color": "yellow",
    }
    summary["trend_data"] = extract_trend_data(samples)
    if include_oscillation:
        summary["oscillation_study"] = analyze_p1_oscillation(samples, extra_candidate_keys=extra_candidate_keys)
    else:
        checked_keys = list(OSCILLATION_CANDIDATE_KEYS)
        for key in extra_candidate_keys or ():
            if key and key not in checked_keys:
                checked_keys.append(key)
        summary["oscillation_study"] = {
            "available": False,
            "provisional": True,
            "reason": "disabled_for_fast_monitor_path",
            "checked_candidate_keys": checked_keys,
            "candidates": [],
            "candidate_count": 0,
            "sample_count": len(samples),
            "dt_s": dt_estimate,
            "certainty": "n/a",
        }
    tune_s_period = summary["current"].get("tune_s_period_s")
    p1_period = (summary.get("oscillation_study") or {}).get("dominant_period_s")
    ratio = _resonance_mismatch(p1_period, tune_s_period)
    summary["ssmb_resonance"] = {
        "observed_p1_period_s": p1_period,
        "synchrotron_period_s": tune_s_period,
        "period_ratio_to_qs": ratio,
        "message": (
            "Observed P1 period is many orders slower than the synchrotron period; that points to a slow control / thermal / optics modulation rather than a direct turn-by-turn Qs oscillation."
            if include_extended and ratio not in (None, 0.0) and abs(float(ratio)) > 100.0
            else "Observed P1 period is being compared live to the synchrotron period for a quick resonance sanity check."
        ),
    }
    return summary


def _summarize_temperature_state(summary: Dict[str, object]) -> Dict[str, object]:
    trend_data = (summary.get("trend_data") or {})
    current = (summary.get("current") or {})
    candidates = (
        ("climate_kw13_return_temp_c", "KW13 return"),
        ("climate_sr_temp_c", "SR temp"),
        ("climate_sr_temp1_c", "SR temp1"),
    )
    best_key = None
    best_label = None
    best_delta = 0.0
    best_mean = None
    for key, label in candidates:
        values = [float(v) for v in trend_data.get(key, []) if isinstance(v, (int, float))]
        current_value = _valid_float(current.get(key))
        if len(values) < 5 or current_value is None:
            continue
        mean = float(np.mean(np.asarray(values, dtype=float)))
        delta = abs(current_value - mean)
        if delta >= best_delta:
            best_delta = delta
            best_key = key
            best_label = label
            best_mean = mean
    return {
        "unstable": bool(best_delta >= TEMPERATURE_UNSTABLE_THRESHOLD_C),
        "threshold_c": TEMPERATURE_UNSTABLE_THRESHOLD_C,
        "max_deviation_c": best_delta,
        "primary_key": best_key,
        "primary_label": best_label,
        "baseline_mean_c": best_mean,
    }


def _bump_quality_score(summary: Dict[str, object]) -> Dict[str, object]:
    current = summary.get("current", {}) or {}
    orbit_error = abs(_valid_float(current.get("bump_orbit_error_mm")) or 0.0)
    l2_offset = abs(_valid_float(current.get("bump_bpm_l2_mm")) or 0.0)
    qpd01_center = abs(_valid_float(current.get("qpd_l2_center_x_avg_um")) or 0.0)
    sigma_delta = abs(_valid_float(current.get("qpd_l4_sigma_delta_first_order")) or 0.0)
    penalties = 25.0 * min(1.0, orbit_error / 0.5)
    penalties += 35.0 * min(1.0, l2_offset / 1.0)
    penalties += 20.0 * min(1.0, qpd01_center / 1200.0)
    penalties += 20.0 * min(1.0, sigma_delta / 5.0e-4)
    score = max(0.0, 100.0 - penalties)
    status = "good" if score >= 75.0 else "watch" if score >= 45.0 else "poor"
    return {"score": score, "status": status}


def assess_alpha_monitor(summary: Dict[str, object]) -> Dict[str, object]:
    bump = summary.get("bump_state", {})
    sweep = summary.get("rf_sweep_metrics", {})
    legacy = _valid_float((summary.get("current") or {}).get("legacy_alpha0_corrected"))
    bpm = _valid_float(sweep.get("alpha0_from_bpm_eta"))
    difference = None if legacy is None or bpm is None else legacy - bpm
    contamination_likely = bool(
        bump.get("active")
        and sweep.get("available")
        and difference is not None
        and abs(difference) >= ALPHA_CONTAMINATION_THRESHOLD
    )
    if not sweep.get("available"):
        status = "waiting_rf_sweep"
        message = "Waiting for enough RF motion to fit phase slip and BPM-based α₀."
        color = "yellow"
    elif contamination_likely:
        status = "bump_contaminated"
        message = "Bump is active and legacy/BPM α₀ disagree strongly. Treat RF-only α₀ as contaminated."
        color = "red"
    else:
        status = "usable"
        message = "BPM-based α₀ is available. Compare it to the legacy shortcut, but prefer the BPM/η route."
        color = "green"
    return {
        "status": status,
        "message": message,
        "color": color,
        "legacy_alpha0": legacy,
        "bpm_alpha0": bpm,
        "difference": difference,
        "bump_active": bool(bump.get("active")),
        "contamination_likely": contamination_likely,
    }


def extract_trend_data(samples: Sequence[Dict[str, object]]) -> Dict[str, List[Optional[float]]]:
    history = list(samples)
    bpm_alpha_series = []
    alpha_difference_series = []
    for sample in history:
        bpm_alpha = _valid_float(sample.get("derived", {}).get("alpha0_from_live_eta"))
        legacy = _valid_float(sample.get("derived", {}).get("legacy_alpha0_corrected"))
        bpm_alpha_series.append(bpm_alpha)
        alpha_difference_series.append(None if bpm_alpha is None or legacy is None else legacy - bpm_alpha)
    return {
        "index": [sample.get("sample_index") for sample in history],
        "rf_offset_hz": [_valid_float(sample.get("derived", {}).get("rf_offset_hz")) for sample in history],
        "rf_readback_499mhz_khz": [_valid_float(sample.get("channels", {}).get("rf_readback_499mhz", {}).get("value")) for sample in history],
        "cavity_voltage_kv": [_valid_float(sample.get("channels", {}).get("cavity_voltage_kv", {}).get("value")) for sample in history],
        "delta_s": [_valid_float(sample.get("derived", {}).get("delta_l4_bpm_first_order")) for sample in history],
        "legacy_alpha0": [_valid_float(sample.get("derived", {}).get("legacy_alpha0_corrected")) for sample in history],
        "bpm_alpha0": bpm_alpha_series,
        "alpha_difference": alpha_difference_series,
        "beam_energy_mev": [_valid_float(sample.get("derived", {}).get("beam_energy_from_bpm_mev")) for sample in history],
        "sigma_delta": [_valid_float(sample.get("derived", {}).get("qpd_l4_sigma_delta_first_order")) for sample in history],
        "tune_y": [_valid_float(sample.get("derived", {}).get("tune_y_unitless")) for sample in history],
        "tune_s": [_valid_float(sample.get("derived", {}).get("tune_s_unitless")) for sample in history],
        "beam_current": [_valid_float(sample.get("channels", {}).get("beam_current", {}).get("value")) for sample in history],
        "bump_strength_a": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("max_abs_corrector_a")
            )
            for sample in history
        ],
        "bump_bpm_avg_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("bpm_avg_mm")
            )
            for sample in history
        ],
        "bump_orbit_error_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("orbit_error_mm")
            )
            for sample in history
        ],
        "bump_bpm_k1_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_k1")
            )
            for sample in history
        ],
        "bump_bpm_l2_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_l2")
            )
            for sample in history
        ],
        "bump_bpm_k3_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_k3")
            )
            for sample in history
        ],
        "bump_bpm_l4_mm": [
            _valid_float(
                _summarize_bump_state(sample.get("channels", {})).get("bpm_values_mm", {}).get("l4_bump_orbit_bpm_l4")
            )
            for sample in history
        ],
        "p1_h1_ampl": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl", {}).get("value")) for sample in history],
        "p1_h1_ampl_avg": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl_avg", {}).get("value")) for sample in history],
        "p1_h1_ampl_dev": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl_dev", {}).get("value")) for sample in history],
        "p3_h1_ampl": [_valid_float(sample.get("channels", {}).get("p3_h1_ampl", {}).get("value")) for sample in history],
        "p3_h1_ampl_avg": [_valid_float(sample.get("channels", {}).get("p3_h1_ampl_avg", {}).get("value")) for sample in history],
        "qpd_l4_center_x_avg_um": [_valid_float(sample.get("channels", {}).get("qpd_l4_center_x_avg_um", {}).get("value")) for sample in history],
        "qpd_l2_center_x_avg_um": [_valid_float(sample.get("channels", {}).get("qpd_l2_center_x_avg_um", {}).get("value")) for sample in history],
        "qpd_l4_sigma_x_mm": [_valid_float(sample.get("derived", {}).get("qpd_l4_sigma_x_mm")) for sample in history],
        "qpd_l4_sigma_y_mm": [_valid_float(sample.get("derived", {}).get("qpd_l4_sigma_y_mm")) for sample in history],
        "qpd_l2_sigma_x_mm": [_valid_float(sample.get("channels", {}).get("qpd_l2_sigma_x", {}).get("value")) for sample in history],
        "qpd_l2_sigma_y_mm": [_valid_float(sample.get("channels", {}).get("qpd_l2_sigma_y", {}).get("value")) for sample in history],
        "climate_kw13_return_temp_c": [_valid_float(sample.get("channels", {}).get("climate_kw13_return_temp_c", {}).get("value")) for sample in history],
        "climate_sr_temp_c": [_valid_float(sample.get("channels", {}).get("climate_sr_temp_c", {}).get("value")) for sample in history],
        "climate_sr_temp1_c": [_valid_float(sample.get("channels", {}).get("climate_sr_temp1_c", {}).get("value")) for sample in history],
    }


def build_monitor_sections(summary: Dict[str, object]) -> List[Dict[str, object]]:
    current = summary.get("current", {})
    bump = summary.get("bump_state", {})
    sweep = summary.get("rf_sweep_metrics", {})
    bump_monitor = summary.get("bump_monitor", {})
    environment = summary.get("environment_monitor", {})
    alpha = summary.get("alpha_assessment", {})
    oscillation = summary.get("oscillation_study", {})
    temp_state = summary.get("temperature_state", {})
    sections = [
        {
            "key": "machine_state",
            "title": "Machine State",
            "color": "red" if temp_state.get("unstable") else ("green" if not current.get("nonlinear_bpms") else "yellow"),
            "rows": [
                ("Beam current", "%s mA" % _fmt(current.get("beam_current"))),
                ("Beam current (scope)", "%s µA" % _fmt(current.get("beam_current_scope"))),
                ("RF readback", "%s kHz" % _fmt(current.get("rf_readback_khz"))),
                ("RF rdFrq499", "%s kHz" % _fmt(current.get("rf_readback_499mhz_khz"))),
                ("RF offset", "%s Hz" % _fmt(current.get("rf_offset_hz"))),
                ("RF sweep detected", "ON" if summary.get("rf_sweep_detection", {}).get("active") else "OFF/idle"),
                ("L4 bump", "%s" % bump.get("state_label", "unknown")),
                ("Temperature state", "UNSTABLE" if temp_state.get("unstable") else "stable"),
                ("Temp deviation", "%s C" % _fmt(temp_state.get("max_deviation_c"))),
                ("Bump max |I|", "%s A" % _fmt(bump.get("max_abs_corrector_a"))),
                ("Nonlinear BPMs", ", ".join(current.get("nonlinear_bpms") or []) or "none"),
                ("Monitor samples", _fmt((summary.get("monitor_health") or {}).get("sample_count"))),
                ("Monitor span", _fmt_duration((summary.get("monitor_health") or {}).get("buffer_span_s"))),
                ("Monitor mem", "%s MB" % _fmt(((summary.get("monitor_health") or {}).get("approx_memory_bytes") or 0) / (1024.0 * 1024.0))),
            ],
            "equations": [],
            "note": "This section is available even when no RF sweep is running. RF sweep and bump state are the two top-level live condition flags for the experiment.",
            "default_trend": "beam_current",
            "trend_options": ["beam_current", "rf_offset_hz", "bump_strength_a"],
        },
        {
            "key": "bump_feedback",
            "title": "Bump Feedback / Orbit Lock",
            "color": "red" if bump.get("active") else "green",
            "rows": [
                ("Feedback state", bump.get("state_label", "unknown")),
                ("RF ctrl enable", _fmt(bump.get("rf_frequency_control_enable"))),
                ("Gain", _fmt(current.get("bump_feedback_gain"))),
                ("Ref orbit", "%s mm" % _fmt(current.get("bump_feedback_ref_mm"))),
                ("Deadband", "%s mm" % _fmt(current.get("bump_feedback_deadband_mm"))),
                ("⟨x⟩ of 4 bump BPMs", "%s mm" % _fmt(current.get("bump_bpm_avg_mm"))),
                ("Orbit error", "%s mm" % _fmt(current.get("bump_orbit_error_mm"))),
                ("Estimated step", _fmt(current.get("bump_step_estimate"))),
                ("BPMZ1L2RP", "%s mm" % _fmt(current.get("bump_bpm_l2_mm"))),
                ("BPMZ1K3RP", "%s mm" % _fmt(current.get("bump_bpm_k3_mm"))),
                ("BPMZ1L4RP", "%s mm" % _fmt(current.get("bump_bpm_l4_mm"))),
                ("P1avg vs bump |I| slope", _fmt((bump_monitor.get("p1_avg_vs_bump_strength") or {}).get("slope"))),
                ("Bump quality", "%s / %.1f" % (((bump_monitor.get("quality_score") or {}).get("status") or "n/a"), ((bump_monitor.get("quality_score") or {}).get("score") or 0.0))),
            ],
            "equations": [
                "x̄ = (x_K1 + x_L2 + x_K3 + x_L4) / 4",
                "Δu = g · (x_ref - x̄)  if  |x_ref - x̄| > deadband",
                "I_i ← I_i + f_i · Δu",
            ],
            "note": "This is a global orbit-lock loop. BPMZ1L2RP is near the L2/undulator side, while the other feedback BPMs are spread through K3 and L4, so the bump constrains a ring-wide closed-orbit family rather than only the undulator center.",
            "default_trend": "bump_orbit_error_mm",
            "trend_options": ["bump_orbit_error_mm", "bump_bpm_avg_mm", "bump_strength_a", "bump_bpm_l2_mm", "bump_bpm_k3_mm", "bump_bpm_l4_mm", "p1_h1_ampl_avg", "p1_h1_ampl_dev"],
        },
        {
            "key": "coherent_light",
            "title": "Coherent Light Monitor",
            "color": "green" if current.get("p1_h1_ampl") is not None or current.get("p1_h1_ampl_avg") is not None else "yellow",
            "rows": [
                ("P1 live", _fmt(current.get("p1_h1_ampl"))),
                ("P1 avg", _fmt(current.get("p1_h1_ampl_avg"))),
                ("P1 std", _fmt(current.get("p1_h1_ampl_dev"))),
                ("P3 live", _fmt(current.get("p3_h1_ampl"))),
                ("P3 avg", _fmt(current.get("p3_h1_ampl_avg"))),
                ("dP1/dδ", _fmt((sweep.get("p1_vs_delta") or {}).get("slope"))),
                ("dP1/dfRF", _fmt((sweep.get("p1_vs_rf") or {}).get("slope"))),
            ],
            "equations": [
                "P1 = coherent-light harmonic observable measured during the RF sweep",
                "Track P1(f_RF) and P1(δₛ) together with α₀ and η",
            ],
            "note": "For this experiment, P1 versus f_RF is the key observable. Compare it against BPM-derived δₛ and phase-slip fits.",
            "default_trend": "p1_h1_ampl_avg",
            "trend_options": ["p1_h1_ampl_avg", "p1_h1_ampl", "p1_h1_ampl_dev", "p3_h1_ampl", "p3_h1_ampl_avg", "rf_offset_hz", "delta_s"],
        },
        {
            "key": "camera_environment",
            "title": "Camera Centers And Temperature",
            "color": "red" if temp_state.get("unstable") else "yellow",
            "rows": [
                ("QPD00 center X avg", "%s um" % _fmt(current.get("qpd_l4_center_x_avg_um"))),
                ("QPD01 center X avg", "%s um" % _fmt(current.get("qpd_l2_center_x_avg_um"))),
                ("KW13 return temp", "%s C" % _fmt(current.get("climate_kw13_return_temp_c"))),
                ("SR temp", "%s C" % _fmt(current.get("climate_sr_temp_c"))),
                ("SR temp1", "%s C" % _fmt(current.get("climate_sr_temp1_c"))),
                ("Temp unstable", "yes" if temp_state.get("unstable") else "no"),
                ("Worst channel", "%s" % (temp_state.get("primary_label") or "n/a")),
                ("P1avg vs QPD00 center", _fmt((environment.get("p1_avg_vs_qpd00_center") or {}).get("slope"))),
                ("P1avg vs KW13 temp", _fmt((environment.get("p1_avg_vs_kw13_temp") or {}).get("slope"))),
                ("P1avg vs SR temp", _fmt((environment.get("p1_avg_vs_sr_temp") or {}).get("slope"))),
            ],
            "equations": [
                "Check P1(t) against slow thermal drift and camera-center motion",
                "Correlate P1avg with QPD centers and temperature channels to separate beam physics from diagnostics/environment drift",
            ],
            "note": "These are strong candidates for the ~5 minute P1 oscillation: slow thermal drift, SR-camera center drift, or optical transport changes.",
            "default_trend": "climate_kw13_return_temp_c",
            "trend_options": ["climate_kw13_return_temp_c", "climate_sr_temp_c", "climate_sr_temp1_c", "qpd_l4_center_x_avg_um", "qpd_l2_center_x_avg_um", "p1_h1_ampl_avg"],
        },
        {
            "key": "p1_oscillation",
            "title": "P1 Oscillation Study",
            "color": {"high": "green", "medium": "yellow"}.get(oscillation.get("certainty"), "red" if oscillation.get("available") else "yellow"),
            "rows": [
                ("Dominant period", _fmt_duration(oscillation.get("dominant_period_s"))),
                ("Autocorr period", _fmt_duration(oscillation.get("autocorr_period_s"))),
                ("Frequency", "%s Hz" % _fmt(oscillation.get("dominant_frequency_hz"))),
                ("Samples / span", "%s / %s" % (_fmt(oscillation.get("sample_count")), _fmt_duration(oscillation.get("span_s")))),
                ("Cycles seen", _fmt(oscillation.get("cycles_seen"))),
                ("Spectral confidence", _fmt(oscillation.get("peak_power_fraction"))),
                ("Autocorr confidence", _fmt(oscillation.get("autocorr_peak"))),
                ("Certainty", oscillation.get("certainty", "waiting")),
                ("Top candidate", ((oscillation.get("top_candidate") or {}).get("label")) or "n/a"),
                ("Top candidate lag", _fmt_duration((oscillation.get("top_candidate") or {}).get("lag_s"))),
                ("Top candidate r", _fmt((oscillation.get("top_candidate") or {}).get("pearson_r"))),
            ],
            "equations": [
                "Use rolling FFT and autocorrelation on P1avg to estimate dominant period without assuming a pure sine wave",
                "Rank candidate channels by Pearson correlation, lagged cross-correlation, and harmonic-period match",
            ],
            "note": "Designed for quasi-periodic, non-sinusoidal P1 motion. Confidence rises once the monitor history spans at least ~2 cycles; before that, treat rankings as provisional. This is still a live heuristic study, not a full statistical proof of SSMB resonance.",
            "default_trend": "p1_h1_ampl_avg",
            "trend_options": ["p1_h1_ampl_avg", "bump_orbit_error_mm", "bump_strength_a", "bump_bpm_l2_mm", "qpd_l4_center_x_avg_um", "climate_kw13_return_temp_c", "climate_sr_temp_c", "rf_offset_hz", "delta_s", "p3_h1_ampl_avg"],
        },
        {
            "key": "energy_momentum",
            "title": "Energy And Momentum",
            "color": "green",
            "rows": [
                ("δₛ from L4 BPMs", _fmt(current.get("delta_l4_bpm_first_order"))),
                ("E from BPMs", "%s MeV" % _fmt(current.get("beam_energy_from_bpm_mev"))),
                ("σδ from QPD00", _fmt(current.get("qpd_l4_sigma_delta_first_order"))),
                ("σE from QPD00", "%s MeV" % _fmt(current.get("qpd_l4_sigma_energy_mev"))),
                ("QPD00 σₓ", "%s mm" % _fmt(current.get("qpd_l4_sigma_x_mm"))),
                ("QPD00 σᵧ", "%s mm" % _fmt(current.get("qpd_l4_sigma_y_mm"))),
            ],
            "equations": [
                "xᵢ - xᵢ,ref ≈ Dₓ,ᵢ · δₛ",
                "E ≈ E₀ · (1 + δₛ)",
                "σₓ² ≈ βₓεₓ + (ηₓσδ)²",
            ],
            "note": "This is the practical energy/spread chain for L4: BPMs for centroid, QPD00 for spread proxy. Compare with BPMZ1L2RP and QPD01 to see what the undulator-side region is doing.",
            "default_trend": "delta_s",
            "trend_options": ["delta_s", "beam_energy_mev", "sigma_delta", "rf_offset_hz", "bump_bpm_l2_mm", "qpd_l2_center_x_avg_um"],
        },
        {
            "key": "alpha_phase_slip",
            "title": "α₀ And Phase Slip",
            "color": alpha.get("color", "yellow"),
            "rows": [
                ("Legacy α₀", _fmt(alpha.get("legacy_alpha0"))),
                ("BPM α₀", _fmt(alpha.get("bpm_alpha0"))),
                ("Legacy - BPM", _fmt(alpha.get("difference"))),
                ("η (phase slip)", _fmt(sweep.get("phase_slip_factor_eta"))),
                ("Bump contamination", "likely" if alpha.get("contamination_likely") else "not evident"),
            ],
            "equations": [
                "Δf_RF / f_RF ≈ -η · δₛ",
                "α₀ = η + 1/γ²",
                "α₀,legacy ∝ Qₛ² · E / (f_RF² · U_cav)",
            ],
            "note": alpha.get("message"),
            "default_trend": "alpha_difference",
            "trend_options": ["alpha_difference", "bpm_alpha0", "legacy_alpha0", "delta_s", "rf_offset_hz"],
        },
        {
            "key": "tunes_chromatic",
            "title": "Tunes And Chromatic Cross-Checks",
            "color": "green" if sweep.get("available") else "yellow",
            "rows": [
                ("Qₓ", _fmt(current.get("tune_x_unitless"))),
                ("Qₓ source", "TUNEZRP:measX"),
                ("Qᵧ", _fmt(current.get("tune_y_unitless"))),
                ("Qᵧ source", "TUNEZRP:measY"),
                ("Qₛ", _fmt(current.get("tune_s_unitless"))),
                ("Qₛ source", "cumz4x003gp:tuneSyn"),
                ("Tₓ oscillation", _fmt_duration(current.get("tune_x_period_s"))),
                ("Tᵧ oscillation", _fmt_duration(current.get("tune_y_period_s"))),
                ("Tₛ oscillation", _fmt_duration(current.get("tune_s_period_s"))),
                ("dQₓ/dδ", _fmt((sweep.get("qx_vs_delta") or {}).get("slope"))),
                ("dQᵧ/dδ", _fmt((sweep.get("qy_vs_delta") or {}).get("slope"))),
                ("dQₛ/dδ", _fmt((sweep.get("qs_vs_delta") or {}).get("slope"))),
                ("dσₓ/dδ", _fmt((sweep.get("sigma_x_vs_delta") or {}).get("slope"))),
                ("dQPD00 center/dδ", _fmt((sweep.get("qpd00_center_vs_delta") or {}).get("slope"))),
            ],
            "equations": [
                "Qₓ(δ) ≈ Qₓ0 + ξₓ δ",
                "Qᵧ(δ) ≈ Qᵧ0 + ξᵧ δ",
                "Additional sweep-derived cross-checks: σₓ(δ), center_X(δ), I_beam(δ), P1(δ)",
            ],
            "note": "There is currently one live tune source per plane. Treat tune slopes as cross-checks; the strongest SSMB chain remains RF → δₛ → η → α₀.",
            "default_trend": "tune_y",
            "trend_options": ["tune_y", "tune_s", "delta_s", "rf_offset_hz"],
        },
    ]
    return sections


def build_theory_sections(summary: Dict[str, object]) -> List[Dict[str, object]]:
    current = summary.get("current", {})
    bump = summary.get("bump_state", {})
    sweep = summary.get("rf_sweep_metrics", {})
    bump_monitor = summary.get("bump_monitor", {})
    environment = summary.get("environment_monitor", {})
    oscillation = summary.get("oscillation_study", {})
    return [
        {
            "title": "1. Raw Instruments",
            "lines": [
                "L4 BPM chain: BPMZ3L4RP, BPMZ4L4RP, BPMZ5L4RP, BPMZ6L4RP",
                "Bump-loop BPM chain: BPMZ1K1RP, BPMZ1L2RP, BPMZ1K3RP, BPMZ1L4RP",
                "Profile monitors: QPD00ZL4RP and QPD01ZL2RP (σx, σy, center X avg)",
                "Coherent-light observables: SCOPE1ZULP:h1p1:* and h1p3:*",
                "Environment candidates: KLIMAC1CP:coolKW13:rdRetTemp, KLIMAC1CP:sr:rdTemp, KLIMAC1CP:sr:rd1Temp",
                "RF references: MCLKHGP:setFrq, MCLKHGP:rdFrq499",
                "Tunes: Qx from TUNEZRP:measX, Qy from TUNEZRP:measY, Qs from cumz4x003gp:tuneSyn",
                "Bump-state context: HS1P2K3RP, HS3P1L4RP, HS3P2L4RP, HS1P1K1RP, AKC10VP",
            ],
        },
        {
            "title": "2. Bump-Controlled Orbit Family",
            "equations": [
                "x̄ = (x_{K1}+x_{L2}+x_{K3}+x_{L4})/4",
                "u ← u + g · (x_ref - x̄)",
                "x(s;δ) = x_disp(s,δ) + u(δ) · B(s)",
            ],
            "lines": [
                "The recovered notebook shows a scalar orbit-lock loop, not a feed-forward RF-to-bump table.",
                "Because BPMZ1L2RP is in L2 near the undulator side, the loop helps keep the source-region orbit centered, but the resulting closed orbit is still global.",
                "Current live bump state: %s, orbit error = %s mm, P1avg-vs-bump slope = %s" % (
                    bump.get("state_label", "unknown"),
                    _fmt(current.get("bump_orbit_error_mm")),
                    _fmt((bump_monitor.get("p1_avg_vs_bump_strength") or {}).get("slope")),
                ),
            ],
        },
        {
            "title": "3. Momentum Offset δₛ",
            "equations": [
                "Δx_i = x_i - x_{i,ref}",
                "Δx_i ≈ D_{x,i} · δₛ",
                "δₛ ≈ (Σ_i w_i D_{x,i} Δx_i) / (Σ_i w_i D_{x,i}²)",
            ],
            "lines": [
                "Raw data: horizontal L4 BPM offsets relative to the stored baseline.",
                "Meaning: synchronous off-momentum state occupied during the RF sweep.",
                "Current live value: δₛ = %s" % _fmt(current.get("delta_l4_bpm_first_order")),
            ],
        },
        {
            "title": "4. Phase Slip Factor η",
            "equations": [
                "-Δf_RF / f_RF ≈ η · δₛ",
                "η = -(1/f_RF) · d f_RF / dδₛ",
            ],
            "lines": [
                "Raw data: RF readback plus reconstructed δₛ history.",
                "Fit performed only when enough RF motion is detected.",
                "Current live fit: η = %s" % _fmt(sweep.get("phase_slip_factor_eta")),
            ],
        },
        {
            "title": "5. Momentum Compaction α₀",
            "equations": [
                "α₀ = η + 1/γ²",
                "α₀,legacy ∝ Qₛ² · E / (f_RF² · U_cav)",
            ],
            "lines": [
                "Preferred chain: BPMs → δₛ → η → α₀.",
                "Legacy shortcut uses tune_s, RF, voltage, and energy only, so it misses bump contamination and nonlinear beam-state effects.",
                "Current live values: α₀,legacy = %s, α₀,BPM = %s" % (
                    _fmt(current.get("legacy_alpha0_corrected")),
                    _fmt(sweep.get("alpha0_from_bpm_eta")),
                ),
            ],
        },
        {
            "title": "6. Spread And Coherent-Light Observables",
            "equations": [
                "σₓ² ≈ βₓ εₓ + (ηₓ σδ)²",
                "σ_E ≈ E₀ · σδ",
                "P1 = P1(f_RF) or P1(δₛ)",
            ],
            "lines": [
                "QPD00ZL4RP provides the first-order spread proxy through σx in a dispersive region.",
                "P1 is the main SSMB observable; compare P1(f_RF), P1(δₛ), and P1 versus bump, camera-center, and temperature activity against α₀ and bump state.",
                "Bump status now: %s, max |I| = %s A" % (bump.get("state_label", "unknown"), _fmt(bump.get("max_abs_corrector_a"))),
                "Current env slopes: P1avg-vs-KW13 temp = %s, P1avg-vs-QPD00 center = %s" % (
                    _fmt((environment.get("p1_avg_vs_kw13_temp") or {}).get("slope")),
                    _fmt((environment.get("p1_avg_vs_qpd00_center") or {}).get("slope")),
                ),
            ],
        },
        {
            "title": "7. P1 Oscillation Study",
            "equations": [
                "Estimate dominant P1avg period from rolling FFT/autocorrelation",
                "Compare candidate channels using correlation, lag, and harmonic-period match",
            ],
            "lines": [
                "This is designed for the slow ~5 minute problem without requiring a separate heavyweight offline run.",
                "Current dominant P1 period: %s, autocorr period: %s, certainty %s" % (
                    _fmt_duration(oscillation.get("dominant_period_s")),
                    _fmt_duration(oscillation.get("autocorr_period_s")),
                    oscillation.get("certainty", "waiting"),
                ),
                "Current top candidate: %s, lag = %s, r = %s" % (
                    ((oscillation.get("top_candidate") or {}).get("label")) or "n/a",
                    _fmt_duration((oscillation.get("top_candidate") or {}).get("lag_s")),
                    _fmt((oscillation.get("top_candidate") or {}).get("pearson_r")),
                ),
                "Checked candidates: %s" % (", ".join(oscillation.get("checked_candidate_keys") or []) or "none"),
            ],
        },
    ]


def trend_definitions() -> Dict[str, Dict[str, object]]:
    return TREND_DEFINITIONS


def format_monitor_summary(summary: Dict[str, object]) -> List[str]:
    current = summary.get("current", {})
    sweep_state = summary.get("rf_sweep_detection", {})
    sweep_metrics = summary.get("rf_sweep_metrics", {})
    bump_monitor = summary.get("bump_monitor", {})
    oscillation = summary.get("oscillation_study", {})
    temp_state = summary.get("temperature_state", {})
    lines = [
        "SSMB Live Monitor",
        "",
        "Available even without RF sweep:",
    ]
    for item in summary.get("what_can_be_measured_now", []):
        lines.append("- %s" % item)
    lines.extend(
        [
            "",
            "Needs RF sweep motion:",
        ]
    )
    for item in summary.get("what_needs_rf_sweep", []):
        lines.append("- %s" % item)
    lines.extend(
        [
            "",
            "Current readout:",
            "RF readback: %s kHz" % _fmt(current.get("rf_readback_khz")),
            "RF rdFrq499: %s kHz" % _fmt(current.get("rf_readback_499mhz_khz")),
            "RF offset: %s Hz" % _fmt(current.get("rf_offset_hz")),
            "delta_s from L4 BPMs: %s" % _fmt(current.get("delta_l4_bpm_first_order")),
            "BPM-based beam energy: %s MeV" % _fmt(current.get("beam_energy_from_bpm_mev")),
            "QPD00 sigma_delta proxy: %s" % _fmt(current.get("qpd_l4_sigma_delta_first_order")),
            "QPD00 sigma_E proxy: %s MeV" % _fmt(current.get("qpd_l4_sigma_energy_mev")),
            "Legacy alpha0 shortcut: %s" % _fmt(current.get("legacy_alpha0_corrected")),
            "P1 live / avg / std: %s / %s / %s" % (_fmt(current.get("p1_h1_ampl")), _fmt(current.get("p1_h1_ampl_avg")), _fmt(current.get("p1_h1_ampl_dev"))),
            "P3 live / avg: %s / %s" % (_fmt(current.get("p3_h1_ampl")), _fmt(current.get("p3_h1_ampl_avg"))),
            "QPD00 / QPD01 center X avg: %s / %s um" % (_fmt(current.get("qpd_l4_center_x_avg_um")), _fmt(current.get("qpd_l2_center_x_avg_um"))),
            "KW13 return temp / SR temp / SR temp1: %s / %s / %s C" % (
                _fmt(current.get("climate_kw13_return_temp_c")),
                _fmt(current.get("climate_sr_temp_c")),
                _fmt(current.get("climate_sr_temp1_c")),
            ),
            "Temperature stability: %s (Δ=%s C, channel=%s)" % (
                "UNSTABLE" if temp_state.get("unstable") else "stable",
                _fmt(temp_state.get("max_deviation_c")),
                temp_state.get("primary_label") or "n/a",
            ),
            "P1 oscillation period / certainty: %s / %s" % (_fmt_duration(oscillation.get("dominant_period_s")), oscillation.get("certainty", "waiting")),
            "P1 autocorr period: %s" % _fmt_duration(oscillation.get("autocorr_period_s")),
            "P1 top candidate: %s" % ((((oscillation.get("top_candidate") or {}).get("label")) or "n/a")),
            "Tunes (x, y, s): %s, %s, %s" % (
                _fmt(current.get("tune_x_unitless")),
                _fmt(current.get("tune_y_unitless")),
                _fmt(current.get("tune_s_unitless")),
            ),
            "Oscillation periods (Tx, Ty, Ts): %s, %s, %s" % (
                _fmt_duration(current.get("tune_x_period_s")),
                _fmt_duration(current.get("tune_y_period_s")),
                _fmt_duration(current.get("tune_s_period_s")),
            ),
            "Tune_s monitor: %s kHz" % _fmt(current.get("tune_s_khz")),
            "Beam current: %s" % _fmt(current.get("beam_current")),
            "QPD00 sigma_x / sigma_y: %s mm / %s mm" % (_fmt(current.get("qpd_l4_sigma_x_mm")), _fmt(current.get("qpd_l4_sigma_y_mm"))),
            "L4 bump state: %s" % summary.get("bump_state", {}).get("state_label", "unknown"),
            "L4 bump feedback enable: %s" % summary.get("bump_state", {}).get("feedback_enable", "n/a"),
            "Bump BPM average: %s mm" % _fmt(current.get("bump_bpm_avg_mm")),
            "Bump orbit error: %s mm" % _fmt(current.get("bump_orbit_error_mm")),
            "Bump BPMs (L2/K3/L4): %s / %s / %s mm" % (
                _fmt(current.get("bump_bpm_l2_mm")),
                _fmt(current.get("bump_bpm_k3_mm")),
                _fmt(current.get("bump_bpm_l4_mm")),
            ),
        ]
    )
    nonlinear = current.get("nonlinear_bpms") or []
    if nonlinear:
        lines.append("Nonlinear BPM warning: %s" % ", ".join(nonlinear))
    lines.extend(
        [
            "",
            "RF sweep detection:",
            "active=%s, rf_span=%s kHz" % (sweep_state.get("active"), _fmt(sweep_state.get("rf_span_khz"))),
        ]
    )
    if sweep_metrics.get("available"):
        lines.extend(
            [
                "",
                "Live sweep-derived values:",
                "phase slip factor eta: %s" % _fmt(sweep_metrics.get("phase_slip_factor_eta")),
                "alpha0 from BPM eta: %s" % _fmt(sweep_metrics.get("alpha0_from_bpm_eta")),
                "legacy alpha0 shortcut: %s" % _fmt(sweep_metrics.get("legacy_alpha0_current")),
                "legacy - BPM alpha0: %s" % _fmt(sweep_metrics.get("alpha0_difference")),
                "P1 vs f_RF slope: %s" % _fmt((sweep_metrics.get("p1_vs_rf") or {}).get("slope")),
                "P1 vs δ slope: %s" % _fmt((sweep_metrics.get("p1_vs_delta") or {}).get("slope")),
                "P3 vs f_RF slope: %s" % _fmt((sweep_metrics.get("p3_vs_rf") or {}).get("slope")),
                "P1avg vs bump |I| slope: %s" % _fmt((bump_monitor.get("p1_avg_vs_bump_strength") or {}).get("slope")),
                "P1avg vs bump error slope: %s" % _fmt((bump_monitor.get("p1_avg_vs_bump_error") or {}).get("slope")),
                "P1avg vs KW13 temp slope: %s" % _fmt((summary.get("environment_monitor", {}).get("p1_avg_vs_kw13_temp") or {}).get("slope")),
                "P1avg vs QPD00 center slope: %s" % _fmt((summary.get("environment_monitor", {}).get("p1_avg_vs_qpd00_center") or {}).get("slope")),
                "P1 dominant period: %s" % _fmt_duration(oscillation.get("dominant_period_s")),
                "P1 autocorr period: %s" % _fmt_duration(oscillation.get("autocorr_period_s")),
                "P1 top candidate lag: %s" % _fmt_duration((oscillation.get("top_candidate") or {}).get("lag_s")),
                "Qx vs delta slope: %s" % _fmt((sweep_metrics.get("qx_vs_delta") or {}).get("slope")),
                "Qy vs delta slope: %s" % _fmt((sweep_metrics.get("qy_vs_delta") or {}).get("slope")),
                "Qs vs delta slope: %s" % _fmt((sweep_metrics.get("qs_vs_delta") or {}).get("slope")),
                "QPD00 sigma_x vs delta slope: %s" % _fmt((sweep_metrics.get("sigma_x_vs_delta") or {}).get("slope")),
                "QPD00 center X vs delta slope: %s" % _fmt((sweep_metrics.get("qpd00_center_vs_delta") or {}).get("slope")),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Live sweep-derived values:",
                "Not enough RF motion yet to fit eta / alpha0 / chromatic slopes.",
            ]
        )
    return lines


def format_channel_snapshot(sample: Dict[str, object], spec_map: Optional[Dict[str, object]] = None) -> List[str]:
    channels = sample.get("channels", {})
    lines = ["Current channel snapshot", ""]
    for label in sorted(channels):
        payload = channels[label]
        value = payload.get("value")
        spec = (spec_map or {}).get(label)
        unit = getattr(spec, "unit", "") or ""
        if isinstance(value, list):
            lines.append("%s = [waveform len=%d]" % (label, len(value)))
        else:
            unit_text = (" %s" % unit) if unit else ""
            lines.append("%s = %s%s    (%s)" % (label, value, unit_text, payload.get("pv")))
    return lines


def format_oscillation_study(summary: Dict[str, object]) -> List[str]:
    osc = summary.get("oscillation_study", {}) or {}
    lines = ["P1 Oscillation Study", ""]
    if not osc.get("available"):
        lines.extend(
            [
                "Not enough stable history yet for a confident oscillation study.",
                "Reason: %s" % osc.get("reason", "waiting"),
                "",
                "Guidance:",
                "- For a ~5 minute effect, keep the live monitor running for at least 10 minutes for medium/high confidence.",
                "- The ranking is computed from P1avg against bump, RF/delta, camera-center, temperature, tune, P3, and derived alpha/energy candidates.",
            ]
        )
        checked = osc.get("checked_candidate_keys") or []
        if checked:
            lines.extend(["", "Checked candidates:", ", ".join(checked)])
        return lines
    lines.extend(
        [
            "Dominant P1 period: %s" % _fmt_duration(osc.get("dominant_period_s")),
            "Dominant P1 frequency: %s Hz" % _fmt(osc.get("dominant_frequency_hz")),
            "Samples / span: %s / %s" % (_fmt(osc.get("sample_count")), _fmt_duration(osc.get("span_s"))),
            "Cycles seen: %s" % _fmt(osc.get("cycles_seen")),
            "Spectral confidence: %s" % _fmt(osc.get("peak_power_fraction")),
            "Overall certainty: %s" % osc.get("certainty", "n/a"),
            "Mode: %s" % ("provisional short-history ranking" if osc.get("provisional") else "full period + correlation ranking"),
            "P1 drift slope: %s per s" % _fmt(osc.get("p1_drift_slope_per_s")),
            "",
            "Top candidates:",
        ]
    )
    for idx, candidate in enumerate(osc.get("candidates", []), start=1):
        lines.append(
            "%d. %s | score=%s | r=%s | lag=%s | harmonic=%s | period=%s"
            % (
                idx,
                candidate.get("label", candidate.get("key", "candidate")),
                _fmt(candidate.get("score")),
                _fmt(candidate.get("pearson_r")),
                _fmt_duration(candidate.get("lag_s")),
                _fmt(candidate.get("harmonic_similarity")),
                _fmt_duration(candidate.get("candidate_period_s")),
            )
        )
    lines.extend(
        [
            "",
            "Checked candidates:",
            ", ".join(osc.get("checked_candidate_keys") or []) or "none",
            "",
            "Interpretation:",
            "- High score with small lag and similar/harmonic period is the strongest live clue.",
            "- A temperature or QPD-center candidate suggests diagnostics/environment drift.",
            "- A bump-error or bump-current candidate suggests the orbit-lock loop may be driving the oscillation.",
            "- This is still a live heuristic study, not a full statistical proof of SSMB resonance.",
            "- The current certainty is based on rolling FFT/autocorrelation/correlation logic, not a full offline uncertainty model yet.",
        ]
    )
    return lines


def _fit_channel_against_p1avg(samples: Sequence[Dict[str, object]], channel_label: str):
    x_values = []
    y_values = []
    for sample in samples:
        x_value = _valid_float(sample.get("channels", {}).get(channel_label, {}).get("value"))
        y_value = _valid_float(sample.get("channels", {}).get("p1_h1_ampl_avg", {}).get("value"))
        if x_value is None or y_value is None:
            continue
        x_values.append(x_value)
        y_values.append(y_value)
    if len(x_values) < 2:
        return None
    return _linear_fit(x_values, y_values)


def _summarize_bump_state(channels: Dict[str, object]) -> Dict[str, object]:
    labels = (
        "l4_bump_hcorr_k3_upstream",
        "l4_bump_hcorr_l4_upstream",
        "l4_bump_hcorr_l4_downstream",
        "l4_bump_hcorr_k1_downstream",
    )
    values = {}
    max_abs = 0.0
    for label in labels:
        value = _valid_float(channels.get(label, {}).get("value"))
        values[label] = value
        if value is not None:
            max_abs = max(max_abs, abs(value))
    feedback = _valid_float(channels.get("l4_bump_feedback_enable", {}).get("value"))
    gain = _valid_float(channels.get("l4_bump_feedback_gain", {}).get("value"))
    reference = _valid_float(channels.get("l4_bump_feedback_ref", {}).get("value"))
    deadband = _valid_float(channels.get("l4_bump_feedback_deadband", {}).get("value"))
    rf_ctrl_enable = _valid_float(channels.get("rf_frequency_control_enable", {}).get("value"))
    bpm_labels = (
        "l4_bump_orbit_bpm_k1",
        "l4_bump_orbit_bpm_l2",
        "l4_bump_orbit_bpm_k3",
        "l4_bump_orbit_bpm_l4",
    )
    bpm_values = {
        label: _valid_float(channels.get(label, {}).get("value"))
        for label in bpm_labels
    }
    bpm_clean = [value for value in bpm_values.values() if value is not None]
    bpm_avg = sum(bpm_clean) / len(bpm_clean) if bpm_clean else None
    orbit_error = None if bpm_avg is None or reference is None else reference - bpm_avg
    step_estimate = None
    if orbit_error is not None and gain is not None:
        if deadband is None or abs(orbit_error) > deadband:
            step_estimate = gain * orbit_error
    active = max_abs >= BUMP_CORRECTOR_ACTIVE_THRESHOLD_A or (feedback is not None and feedback != 0.0)
    return {
        "active": active,
        "state_label": "ON" if active else "OFF/idle",
        "feedback_enable": feedback,
        "rf_frequency_control_enable": rf_ctrl_enable,
        "gain": gain,
        "reference_mm": reference,
        "deadband": deadband,
        "bpm_values_mm": bpm_values,
        "bpm_avg_mm": bpm_avg,
        "orbit_error_mm": orbit_error,
        "step_estimate": step_estimate,
        "max_abs_corrector_a": max_abs,
        "corrector_currents_a": values,
    }


def _fmt(value) -> str:
    numeric = _valid_float(value)
    if numeric is None:
        return "n/a"
    if abs(numeric) >= 1e4 or (abs(numeric) > 0 and abs(numeric) < 1e-3):
        return "%.6e" % numeric
    return "%.6f" % numeric
