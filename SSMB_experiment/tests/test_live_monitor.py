import unittest

from SSMB_experiment.ssmb_tool.live_monitor import build_monitor_sections, detect_rf_sweep_active, summarize_live_monitor


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


if __name__ == "__main__":
    unittest.main()
