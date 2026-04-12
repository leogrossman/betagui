from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .analyze_session import _linear_fit, alpha0_from_eta, fit_slip_factor

RF_SWEEP_ACTIVE_THRESHOLD_KHZ = 0.002
RF_SWEEP_ACTIVE_MIN_POINTS = 4
BUMP_CORRECTOR_ACTIVE_THRESHOLD_A = 0.002
ALPHA_CONTAMINATION_THRESHOLD = 5.0e-5

TREND_DEFINITIONS: Dict[str, Dict[str, object]] = {
    "rf_offset_hz": {"label": "Δf_RF [Hz]", "color": "#1e88e5"},
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
    "beam_current": {"label": "Beam current [mA]", "color": "#2e7d32"},
    "bump_strength_a": {"label": "max |I_bump| [A]", "color": "#ad1457"},
}


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
            "nonlinear_bpms": list(derived.get("bpm_x_nonlinear_labels") or []),
        },
        "bump_state": bump,
        "what_can_be_measured_now": [
            "Passive readout: tunes, synchrotron monitor, beam current, orbit BPMs, QPD beam-size proxies, bump states, cavity voltage, beam energy readback.",
            "Passive readout of coherent-light observables P1 and P3 from the scope channels.",
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
    }

    sweep_state = detect_rf_sweep_active(samples)
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
    for sample in samples:
        d = _valid_float(sample.get("derived", {}).get("delta_l4_bpm_first_order"))
        rf = _valid_float(sample.get("derived", {}).get("rf_readback"))
        qx = _valid_float(sample.get("derived", {}).get("tune_x_unitless"))
        qy = _valid_float(sample.get("derived", {}).get("tune_y_unitless"))
        qs = _valid_float(sample.get("derived", {}).get("tune_s_unitless"))
        p1 = _valid_float(sample.get("channels", {}).get("p1_h1_ampl", {}).get("value"))
        p1_avg = _valid_float(sample.get("channels", {}).get("p1_h1_ampl_avg", {}).get("value"))
        p3 = _valid_float(sample.get("channels", {}).get("p3_h1_ampl", {}).get("value"))
        if d is not None and rf is not None:
            delta_series.append(d)
            rf_series.append(rf)
            qx_series.append((d, qx))
            qy_series.append((d, qy))
            qs_series.append((d, qs))
            p1_series.append((d, p1, rf))
            p1_avg_series.append((d, p1_avg, rf))
            p3_series.append((d, p3, rf))
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
            "p1_vs_delta": _linear_fit([x for x, y, _rf in p1_series if y is not None], [y for _x, y, _rf in p1_series if y is not None]),
            "p1_avg_vs_delta": _linear_fit([x for x, y, _rf in p1_avg_series if y is not None], [y for _x, y, _rf in p1_avg_series if y is not None]),
            "p3_vs_delta": _linear_fit([x for x, y, _rf in p3_series if y is not None], [y for _x, y, _rf in p3_series if y is not None]),
            "p1_vs_rf": _linear_fit([rf for _x, y, rf in p1_series if y is not None], [y for _x, y, rf in p1_series if y is not None]),
            "p1_avg_vs_rf": _linear_fit([rf for _x, y, rf in p1_avg_series if y is not None], [y for _x, y, rf in p1_avg_series if y is not None]),
            "p3_vs_rf": _linear_fit([rf for _x, y, rf in p3_series if y is not None], [y for _x, y, rf in p3_series if y is not None]),
        }
    summary["rf_sweep_metrics"] = sweep_metrics
    summary["alpha_assessment"] = assess_alpha_monitor(summary)
    summary["trend_data"] = extract_trend_data(samples)
    return summary


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
    history = list(samples)[-120:]
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
        "p1_h1_ampl": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl", {}).get("value")) for sample in history],
        "p1_h1_ampl_avg": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl_avg", {}).get("value")) for sample in history],
        "p1_h1_ampl_dev": [_valid_float(sample.get("channels", {}).get("p1_h1_ampl_dev", {}).get("value")) for sample in history],
        "p3_h1_ampl": [_valid_float(sample.get("channels", {}).get("p3_h1_ampl", {}).get("value")) for sample in history],
        "p3_h1_ampl_avg": [_valid_float(sample.get("channels", {}).get("p3_h1_ampl_avg", {}).get("value")) for sample in history],
    }


def build_monitor_sections(summary: Dict[str, object]) -> List[Dict[str, object]]:
    current = summary.get("current", {})
    bump = summary.get("bump_state", {})
    sweep = summary.get("rf_sweep_metrics", {})
    alpha = summary.get("alpha_assessment", {})
    sections = [
        {
            "key": "machine_state",
            "title": "Machine State",
            "color": "green" if not current.get("nonlinear_bpms") else "yellow",
            "rows": [
                ("Beam current", "%s mA" % _fmt(current.get("beam_current"))),
                ("Beam current (scope)", "%s µA" % _fmt(current.get("beam_current_scope"))),
                ("RF readback", "%s kHz" % _fmt(current.get("rf_readback_khz"))),
                ("RF rdFrq499", "%s kHz" % _fmt(current.get("rf_readback_499mhz_khz"))),
                ("RF offset", "%s Hz" % _fmt(current.get("rf_offset_hz"))),
                ("L4 bump", "%s" % bump.get("state_label", "unknown")),
                ("Bump max |I|", "%s A" % _fmt(bump.get("max_abs_corrector_a"))),
                ("Nonlinear BPMs", ", ".join(current.get("nonlinear_bpms") or []) or "none"),
            ],
            "equations": [],
            "note": "This section is available even when no RF sweep is running.",
            "default_trend": "beam_current",
            "trend_options": ["beam_current", "rf_offset_hz", "bump_strength_a"],
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
            "note": "This is the practical energy/spread chain for L4: BPMs for centroid, QPD00 for spread proxy.",
            "default_trend": "delta_s",
            "trend_options": ["delta_s", "beam_energy_mev", "sigma_delta", "rf_offset_hz"],
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
                ("Qᵧ", _fmt(current.get("tune_y_unitless"))),
                ("Qₛ", _fmt(current.get("tune_s_unitless"))),
                ("dQₓ/dδ", _fmt((sweep.get("qx_vs_delta") or {}).get("slope"))),
                ("dQᵧ/dδ", _fmt((sweep.get("qy_vs_delta") or {}).get("slope"))),
                ("dQₛ/dδ", _fmt((sweep.get("qs_vs_delta") or {}).get("slope"))),
            ],
            "equations": [
                "Qₓ(δ) ≈ Qₓ0 + ξₓ δ",
                "Qᵧ(δ) ≈ Qᵧ0 + ξᵧ δ",
            ],
            "note": "Treat tune slopes as cross-checks. The strongest SSMB chain remains RF → δₛ → η → α₀.",
            "default_trend": "tune_y",
            "trend_options": ["tune_y", "tune_s", "delta_s", "rf_offset_hz"],
        },
    ]
    return sections


def build_theory_sections(summary: Dict[str, object]) -> List[Dict[str, object]]:
    current = summary.get("current", {})
    bump = summary.get("bump_state", {})
    sweep = summary.get("rf_sweep_metrics", {})
    return [
        {
            "title": "1. Raw Instruments",
            "lines": [
                "L4 BPM chain: BPMZ3L4RP, BPMZ4L4RP, BPMZ5L4RP, BPMZ6L4RP",
                "Profile monitor: QPD00ZL4RP (σx, σy)",
                "Coherent-light observables: SCOPE1ZULP:h1p1:* and h1p3:*",
                "RF references: MCLKHGP:setFrq, MCLKHGP:rdFrq499",
                "Tunes: tune_x_raw, tune_y_raw, tune_s_raw",
                "Bump-state context: HS1P2K3RP, HS3P1L4RP, HS3P2L4RP, HS1P1K1RP, AKC10VP",
            ],
        },
        {
            "title": "2. Momentum Offset δₛ",
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
            "title": "3. Phase Slip Factor η",
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
            "title": "4. Momentum Compaction α₀",
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
            "title": "5. Spread And Coherent-Light Observables",
            "equations": [
                "σₓ² ≈ βₓ εₓ + (ηₓ σδ)²",
                "σ_E ≈ E₀ · σδ",
                "P1 = P1(f_RF) or P1(δₛ)",
            ],
            "lines": [
                "QPD00ZL4RP provides the first-order spread proxy through σx in a dispersive region.",
                "P1 is the main SSMB observable; compare P1(f_RF) and P1(δₛ) against α₀ and bump state.",
                "Bump status now: %s, max |I| = %s A" % (bump.get("state_label", "unknown"), _fmt(bump.get("max_abs_corrector_a"))),
            ],
        },
    ]


def trend_definitions() -> Dict[str, Dict[str, object]]:
    return TREND_DEFINITIONS


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
            "RF rdFrq499: %s kHz" % _fmt(current.get("rf_readback_499mhz_khz")),
            "RF offset: %s Hz" % _fmt(current.get("rf_offset_hz")),
            "delta_s from L4 BPMs: %s" % _fmt(current.get("delta_l4_bpm_first_order")),
            "BPM-based beam energy: %s MeV" % _fmt(current.get("beam_energy_from_bpm_mev")),
            "QPD00 sigma_delta proxy: %s" % _fmt(current.get("qpd_l4_sigma_delta_first_order")),
            "QPD00 sigma_E proxy: %s MeV" % _fmt(current.get("qpd_l4_sigma_energy_mev")),
            "Legacy alpha0 shortcut: %s" % _fmt(current.get("legacy_alpha0_corrected")),
            "P1 live / avg / std: %s / %s / %s" % (_fmt(current.get("p1_h1_ampl")), _fmt(current.get("p1_h1_ampl_avg")), _fmt(current.get("p1_h1_ampl_dev"))),
            "P3 live / avg: %s / %s" % (_fmt(current.get("p3_h1_ampl")), _fmt(current.get("p3_h1_ampl_avg"))),
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
                "P1 vs f_RF slope: %s" % _fmt((sweep_metrics.get("p1_vs_rf") or {}).get("slope")),
                "P1 vs δ slope: %s" % _fmt((sweep_metrics.get("p1_vs_delta") or {}).get("slope")),
                "P3 vs f_RF slope: %s" % _fmt((sweep_metrics.get("p3_vs_rf") or {}).get("slope")),
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
