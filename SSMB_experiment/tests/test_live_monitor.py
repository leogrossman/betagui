import math
import unittest

from SSMB_experiment.ssmb_tool.live_monitor import (
    analyze_p1_oscillation,
    build_monitor_sections,
    build_theory_sections,
    detect_rf_sweep_active,
    format_oscillation_study,
    summarize_live_monitor,
    trend_definitions,
)


class SSMBExperimentLiveMonitorTest(unittest.TestCase):
    def test_detect_rf_sweep_active_uses_rf_span(self):
        samples = [
            {"derived": {"rf_readback": 499688.38770}},
            {"derived": {"rf_readback": 499688.38780}},
            {"derived": {"rf_readback": 499688.38990}},
            {"derived": {"rf_readback": 499688.39010}},
        ]
        result = detect_rf_sweep_active(samples)
        self.assertTrue(result["active"])
        self.assertGreater(result["rf_span_khz"], 0.002)

    def test_summarize_live_monitor_produces_sweep_metrics_when_rf_moves(self):
        samples = []
        for index, rf in enumerate((499688.38770, 499688.38870, 499688.38970, 499688.39070), start=1):
            samples.append(
                {
                    "channels": {
                        "beam_energy_mev": {"value": 250.0},
                        "beam_current": {"value": 4.2},
                        "beam_current_scope": {"value": 512.293},
                        "rf_readback_499mhz": {"value": 685.685},
                        "p1_h1_ampl": {"value": 0.035 + 0.005 * index},
                        "p1_h1_ampl_avg": {"value": 0.061 + 0.006 * index},
                        "p1_h1_ampl_dev": {"value": 0.018},
                        "p3_h1_ampl": {"value": 0.019 + 0.002 * index},
                        "p3_h1_ampl_avg": {"value": 0.006 + 0.001 * index},
                        "l4_bump_hcorr_k3_upstream": {"value": 0.0},
                        "l4_bump_hcorr_l4_upstream": {"value": 0.0},
                        "l4_bump_hcorr_l4_downstream": {"value": 0.0},
                        "l4_bump_hcorr_k1_downstream": {"value": 0.0},
                        "l4_bump_feedback_enable": {"value": 0.0},
                    },
                    "derived": {
                        "rf_readback": rf,
                        "rf_offset_hz": (rf - 499688.38770) * 1e3,
                        "delta_l4_bpm_first_order": 1.0e-4 * index,
                        "beam_energy_from_bpm_mev": 250.0 * (1.0 + 1.0e-4 * index),
                        "qpd_l4_sigma_delta_first_order": 2.0e-4,
                        "qpd_l4_sigma_energy_mev": 0.05,
                        "legacy_alpha0_corrected": 6.3e-4,
                        "tune_x_unitless": 0.0,
                        "tune_y_unitless": 0.12 + 1.0e-4 * index,
                        "tune_s_unitless": 0.013 + 2.0e-4 * index,
                        "tune_s_khz": 19.5,
                        "qpd_l4_sigma_x_mm": 0.6,
                        "qpd_l4_sigma_y_mm": 0.2,
                        "bpm_x_nonlinear_labels": [],
                    },
                }
            )
        summary = summarize_live_monitor(samples)
        self.assertTrue(summary["rf_sweep_detection"]["active"])
        self.assertTrue(summary["rf_sweep_metrics"]["available"])
        self.assertIsNotNone(summary["rf_sweep_metrics"]["phase_slip_factor_eta"])
        self.assertIsNotNone(summary["rf_sweep_metrics"]["alpha0_from_bpm_eta"])
        self.assertIsNotNone(summary["rf_sweep_metrics"]["p1_vs_rf"])
        self.assertIsNotNone(summary["rf_sweep_metrics"]["p1_vs_delta"])

    def test_summarize_live_monitor_detects_bump_state(self):
        sample = {
            "channels": {
                "beam_energy_mev": {"value": 250.0},
                "l4_bump_hcorr_k3_upstream": {"value": 0.01},
                "l4_bump_hcorr_l4_upstream": {"value": 0.0},
                "l4_bump_hcorr_l4_downstream": {"value": 0.0},
                "l4_bump_hcorr_k1_downstream": {"value": 0.0},
                "l4_bump_feedback_enable": {"value": 1.0},
            },
            "derived": {},
        }
        summary = summarize_live_monitor([sample])
        self.assertTrue(summary["bump_state"]["active"])
        self.assertEqual(summary["bump_state"]["state_label"], "ON")

    def test_monitor_sections_include_alpha_panel(self):
        samples = []
        for index, rf in enumerate((499688.38770, 499688.38870, 499688.38970, 499688.39070), start=1):
            samples.append(
                {
                    "channels": {
                        "beam_energy_mev": {"value": 250.0},
                        "beam_current": {"value": 4.2},
                        "l4_bump_hcorr_k3_upstream": {"value": 0.01},
                        "l4_bump_hcorr_l4_upstream": {"value": 0.0},
                        "l4_bump_hcorr_l4_downstream": {"value": 0.0},
                        "l4_bump_hcorr_k1_downstream": {"value": 0.0},
                        "l4_bump_feedback_enable": {"value": 1.0},
                        "l4_bump_feedback_gain": {"value": 0.3},
                        "l4_bump_feedback_ref": {"value": 0.0},
                        "l4_bump_feedback_deadband": {"value": 0.01},
                        "rf_frequency_control_enable": {"value": 0.0},
                        "l4_bump_orbit_bpm_k1": {"value": -0.5},
                        "l4_bump_orbit_bpm_l2": {"value": -0.4},
                        "l4_bump_orbit_bpm_k3": {"value": -0.3},
                        "l4_bump_orbit_bpm_l4": {"value": -0.2},
                        "p1_h1_ampl_avg": {"value": 0.06 + 0.004 * index},
                    },
                    "derived": {
                        "rf_readback": rf,
                        "rf_offset_hz": (rf - 499688.38770) * 1e3,
                        "delta_l4_bpm_first_order": 1.0e-4 * index,
                        "beam_energy_from_bpm_mev": 250.0 * (1.0 + 1.0e-4 * index),
                        "qpd_l4_sigma_delta_first_order": 2.0e-4,
                        "qpd_l4_sigma_energy_mev": 0.05,
                        "legacy_alpha0_corrected": 6.3e-4,
                        "tune_x_unitless": 0.0,
                        "tune_y_unitless": 0.12 + 1.0e-4 * index,
                        "tune_s_unitless": 0.013 + 2.0e-4 * index,
                        "tune_s_khz": 19.5,
                        "qpd_l4_sigma_x_mm": 0.6,
                        "qpd_l4_sigma_y_mm": 0.2,
                        "bpm_x_nonlinear_labels": [],
                    },
                }
            )
        summary = summarize_live_monitor(samples)
        sections = build_monitor_sections(summary)
        alpha_section = [section for section in sections if section["title"] == "α₀ And Phase Slip"][0]
        self.assertIn("α₀ = η + 1/γ²", alpha_section["equations"])
        self.assertTrue(any(label == "BPM α₀" for label, _value in alpha_section["rows"]))
        tune_section = [section for section in sections if section["title"] == "Tunes And Chromatic Cross-Checks"][0]
        self.assertTrue(any(label == "Qₓ source" and value == "TUNEZRP:measX" for label, value in tune_section["rows"]))
        self.assertTrue(any(label == "Qₛ source" and value == "cumz4x003gp:tuneSyn" for label, value in tune_section["rows"]))
        light_section = [section for section in sections if section["title"] == "Coherent Light Monitor"][0]
        self.assertTrue(any(label == "P1 avg" for label, _value in light_section["rows"]))
        bump_section = [section for section in sections if section["title"] == "Bump Feedback / Orbit Lock"][0]
        self.assertTrue(any(label == "⟨x⟩ of 4 bump BPMs" for label, _value in bump_section["rows"]))
        self.assertIn("x̄ = (x_K1 + x_L2 + x_K3 + x_L4) / 4", bump_section["equations"])

    def test_theory_sections_and_trend_catalog_exist(self):
        samples = [
            {
                "channels": {
                    "beam_energy_mev": {"value": 250.0},
                    "beam_current": {"value": 4.2},
                    "l4_bump_hcorr_k3_upstream": {"value": 0.01},
                    "l4_bump_hcorr_l4_upstream": {"value": 0.0},
                    "l4_bump_hcorr_l4_downstream": {"value": 0.0},
                    "l4_bump_hcorr_k1_downstream": {"value": 0.0},
                    "l4_bump_feedback_enable": {"value": 1.0},
                    "l4_bump_feedback_gain": {"value": 0.3},
                    "l4_bump_feedback_ref": {"value": 0.0},
                    "l4_bump_feedback_deadband": {"value": 0.01},
                    "rf_frequency_control_enable": {"value": 0.0},
                    "l4_bump_orbit_bpm_k1": {"value": -0.5},
                    "l4_bump_orbit_bpm_l2": {"value": -0.4},
                    "l4_bump_orbit_bpm_k3": {"value": -0.3},
                    "l4_bump_orbit_bpm_l4": {"value": -0.2},
                    "p1_h1_ampl": {"value": 0.02},
                    "p1_h1_ampl_avg": {"value": 0.03},
                    "p1_h1_ampl_dev": {"value": 0.01},
                    "qpd_l4_center_x_avg_um": {"value": 480.0},
                    "qpd_l2_center_x_avg_um": {"value": 950.0},
                    "climate_kw13_return_temp_c": {"value": 29.5},
                    "climate_sr_temp_c": {"value": 26.3},
                    "climate_sr_temp1_c": {"value": 26.1},
                },
                "derived": {
                    "rf_readback": 499688.388,
                    "rf_offset_hz": 1.0,
                    "delta_l4_bpm_first_order": 1.0e-4,
                    "beam_energy_from_bpm_mev": 250.01,
                    "qpd_l4_sigma_delta_first_order": 2.0e-4,
                    "qpd_l4_sigma_energy_mev": 0.05,
                    "legacy_alpha0_corrected": 6.3e-4,
                    "tune_y_unitless": 0.12,
                    "tune_s_unitless": 0.013,
                    "alpha0_from_live_eta": 2.1e-5,
                    "bpm_x_nonlinear_labels": [],
                },
            }
        ]
        summary = summarize_live_monitor(samples)
        theory = build_theory_sections(summary)
        self.assertTrue(any(section["title"] == "2. Bump-Controlled Orbit Family" for section in theory))
        raw_section = [section for section in theory if section["title"] == "1. Raw Instruments"][0]
        self.assertTrue(any("TUNEZRP:measX" in line for line in raw_section["lines"]))
        self.assertTrue(any("KLIMAC1CP:coolKW13:rdRetTemp" in line for line in raw_section["lines"]))
        env_section = [section for section in build_monitor_sections(summary) if section["title"] == "Camera Centers And Temperature"][0]
        self.assertTrue(any(label == "QPD00 center X avg" for label, _value in env_section["rows"]))
        self.assertIn("delta_s", summary["trend_data"])
        self.assertIn("alpha_difference", summary["trend_data"])
        self.assertIn("bump_orbit_error_mm", summary["trend_data"])
        self.assertIn("p1_h1_ampl_avg", trend_definitions())
        self.assertIn("climate_kw13_return_temp_c", trend_definitions())

    def test_p1_oscillation_study_finds_period_and_candidate(self):
        samples = []
        dt_s = 1.0
        period_s = 40.0
        for index in range(160):
            phase = 2.0 * math.pi * index * dt_s / period_s
            p1 = 0.05 + 0.01 * math.sin(phase)
            climate_temp = 29.5 - 0.4 * math.sin(phase + 0.1)
            qpd_center = 450.0 + 20.0 * math.sin(phase * 2.0)
            samples.append(
                {
                    "timestamp_epoch_s": 1_000_000.0 + index * dt_s,
                    "sample_index": index,
                    "channels": {
                        "p1_h1_ampl_avg": {"value": p1},
                        "climate_kw13_return_temp_c": {"value": climate_temp},
                        "qpd_l4_center_x_avg_um": {"value": qpd_center},
                    },
                    "derived": {},
                }
            )
        analysis = analyze_p1_oscillation(samples)
        self.assertTrue(analysis["available"])
        self.assertAlmostEqual(analysis["dominant_period_s"], period_s, delta=5.0)
        self.assertEqual((analysis["top_candidate"] or {}).get("key"), "climate_kw13_return_temp_c")
        lines = format_oscillation_study({"oscillation_study": analysis})
        self.assertTrue(any("Dominant P1 period" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
