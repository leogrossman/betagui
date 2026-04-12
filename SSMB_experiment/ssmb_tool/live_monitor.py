from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .analyze_session import _linear_fit, alpha0_from_eta, fit_slip_factor

RF_SWEEP_ACTIVE_THRESHOLD_KHZ = 0.002
RF_SWEEP_ACTIVE_MIN_POINTS = 4
BUMP_CORRECTOR_ACTIVE_THRESHOLD_A = 0.002


def _valid_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def summarize_live_monitor(samples: Sequence[Dict[str, object]]) -> Dict[str, object]:
    latest = samples[-1] if samples else {}
    derived = latest.get("derived", {})
    channels = latest.get("channels", {})
    bump = _summarize_bump_state(channels)
    summary: Dict[str, object] = {
        "current": {
            "rf_readback_khz": _valid_float(derived.get("rf_readback")),
            "rf_offset_hz": _valid_float(derived.get("rf_offset_hz")),
            "delta_l4_bpm_first_order": _valid_float(derived.get("delta_l4_bpm_first_order")),
            "beam_energy_from_bpm_mev": _valid_float(derived.get("beam_energy_from_bpm_mev")),
            "qpd_l4_sigma_delta_first_order": _valid_float(derived.get("qpd_l4_sigma_delta_first_order")),
            "qpd_l4_sigma_energy_mev": _valid_float(derived.get("qpd_l4_sigma_energy_mev")),
            "legacy_alpha0_corrected": _valid_float(derived.get("legacy_alpha0_corrected")),
            "tune_x_unitless": _valid_float(derived.get("tune_x_unitless")),
            "tune_y_unitless": _valid_float(derived.get("tune_y_unitless")),
            "tune_s_unitless": _valid_float(derived.get("tune_s_unitless")),
            "tune_s_khz": _valid_float(derived.get("tune_s_khz")),
            "beam_current": _valid_float(channels.get("beam_current", {}).get("value")),
            "qpd_l4_sigma_x_mm": _valid_float(derived.get("qpd_l4_sigma_x_mm")),
            "qpd_l4_sigma_y_mm": _valid_float(derived.get("qpd_l4_sigma_y_mm")),
            "nonlinear_bpms": list(derived.get("bpm_x_nonlinear_labels") or []),
        },
        "bump_state": bump,
        "what_can_be_measured_now": [
            "Passive readout: tunes, synchrotron monitor, beam current, orbit BPMs, QPD beam-size proxies, bump states, cavity voltage, beam energy readback.",
            "From passive L4 BPM orbit: first-order delta_s and BPM-based beam energy shift relative to the monitor baseline.",
            "From QPD00ZL4RP sigma_x: first-order momentum spread proxy and corresponding sigma_E estimate.",
            "From the 4-corrector bump PVs: whether the L4 bump is active, and whether bump feedback is enabled.",
        ],
        "what_needs_rf_sweep": [
            "Slip factor eta from fitted RF-vs-delta_s slope.",
            "Alpha0 from alpha0 = eta + 1/gamma^2 using reconstructed delta_s rather than RF alone.",
            "Tune slopes versus delta_s as chromaticity cross-checks in x, y, and synchrotron channels.",
        ],
    }

    sweep_state = detect_rf_sweep_active(samples)
    summary["rf_sweep_detection"] = sweep_state
    sweep_metrics: Dict[str, object] = {"available": False}

    delta_series = []
    rf_series = []
    qx_series = []
    qy_series = []
    qs_series = []
    for sample in samples:
        d = _valid_float(sample.get("derived", {}).get("delta_l4_bpm_first_order"))
        rf = _valid_float(sample.get("derived", {}).get("rf_readback"))
        qx = _valid_float(sample.get("derived", {}).get("tune_x_unitless"))
        qy = _valid_float(sample.get("derived", {}).get("tune_y_unitless"))
        qs = _valid_float(sample.get("derived", {}).get("tune_s_unitless"))
        if d is not None and rf is not None:
            delta_series.append(d)
            rf_series.append(rf)
            qx_series.append((d, qx))
            qy_series.append((d, qy))
            qs_series.append((d, qs))
    if len(delta_series) >= 3 and sweep_state["active"]:
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
        }
    summary["rf_sweep_metrics"] = sweep_metrics
    return summary


def format_monitor_summary(summary: Dict[str, object]) -> List[str]:
    current = summary.get("current", {})
    sweep_state = summary.get("rf_sweep_detection", {})
    sweep_metrics = summary.get("rf_sweep_metrics", {})
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
            "RF offset: %s Hz" % _fmt(current.get("rf_offset_hz")),
            "delta_s from L4 BPMs: %s" % _fmt(current.get("delta_l4_bpm_first_order")),
            "BPM-based beam energy: %s MeV" % _fmt(current.get("beam_energy_from_bpm_mev")),
            "QPD00 sigma_delta proxy: %s" % _fmt(current.get("qpd_l4_sigma_delta_first_order")),
            "QPD00 sigma_E proxy: %s MeV" % _fmt(current.get("qpd_l4_sigma_energy_mev")),
            "Legacy alpha0 shortcut: %s" % _fmt(current.get("legacy_alpha0_corrected")),
            "Tunes (x, y, s): %s, %s, %s" % (
                _fmt(current.get("tune_x_unitless")),
                _fmt(current.get("tune_y_unitless")),
                _fmt(current.get("tune_s_unitless")),
            ),
            "Tune_s monitor: %s kHz" % _fmt(current.get("tune_s_khz")),
            "Beam current: %s" % _fmt(current.get("beam_current")),
            "QPD00 sigma_x / sigma_y: %s mm / %s mm" % (_fmt(current.get("qpd_l4_sigma_x_mm")), _fmt(current.get("qpd_l4_sigma_y_mm"))),
            "L4 bump state: %s" % summary.get("bump_state", {}).get("state_label", "unknown"),
            "L4 bump feedback enable: %s" % summary.get("bump_state", {}).get("feedback_enable", "n/a"),
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
                "Qx vs delta slope: %s" % _fmt((sweep_metrics.get("qx_vs_delta") or {}).get("slope")),
                "Qy vs delta slope: %s" % _fmt((sweep_metrics.get("qy_vs_delta") or {}).get("slope")),
                "Qs vs delta slope: %s" % _fmt((sweep_metrics.get("qs_vs_delta") or {}).get("slope")),
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


def format_channel_snapshot(sample: Dict[str, object]) -> List[str]:
    channels = sample.get("channels", {})
    lines = ["Current channel snapshot", ""]
    for label in sorted(channels):
        payload = channels[label]
        value = payload.get("value")
        if isinstance(value, list):
            lines.append("%s = [waveform len=%d]" % (label, len(value)))
        else:
            lines.append("%s = %s    (%s)" % (label, value, payload.get("pv")))
    return lines


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
    active = max_abs >= BUMP_CORRECTOR_ACTIVE_THRESHOLD_A or (feedback is not None and feedback != 0.0)
    return {
        "active": active,
        "state_label": "ON" if active else "OFF/idle",
        "feedback_enable": feedback,
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
