import unittest

from SSMB_experiment.ssmb_tool.log_now import _derived_metrics


class SSMBExperimentLogNowTest(unittest.TestCase):
    def test_derived_metrics_include_bpm_and_qpd_estimators(self):
        sample = {
            "channels": {
                "rf_readback": {"value": 499688.38770589296},
                "tune_x_raw": {"value": 0.0},
                "tune_y_raw": {"value": 1450.0},
                "tune_s_raw": {"value": 19500.0},
                "beam_energy_mev": {"value": 250.0},
                "cavity_voltage_kv": {"value": 40.0},
                "qpd_l4_sigma_x": {"value": 0.6},
                "qpd_l4_sigma_y": {"value": 0.2},
                "bpmz3l4rp_x": {"value": -0.06064241411164305},
                "bpmz4l4rp_x": {"value": -0.09744634305495894},
                "bpmz5l4rp_x": {"value": -0.09744634305157819},
                "bpmz6l4rp_x": {"value": -0.05908095004017995},
            }
        }
        derived = _derived_metrics(
            sample,
            derived_context={
                "rf_reference_khz": 499688.38770589296,
                "l4_bpm_reference_mm": {
                    "bpmz3l4rp_x": 0.0,
                    "bpmz4l4rp_x": 0.0,
                    "bpmz5l4rp_x": 0.0,
                    "bpmz6l4rp_x": 0.0,
                },
            },
        )
        self.assertAlmostEqual(derived["delta_l4_bpm_first_order"], 1.0e-4, places=8)
        self.assertAlmostEqual(derived["beam_energy_from_bpm_mev"], 250.025, places=6)
        self.assertIsNotNone(derived["legacy_alpha0_corrected"])
        self.assertIsNotNone(derived["qpd_l4_sigma_delta_first_order"])
        self.assertEqual(
            derived["delta_l4_bpms_used"],
            ["bpmz3l4rp_x", "bpmz4l4rp_x", "bpmz5l4rp_x", "bpmz6l4rp_x"],
        )


if __name__ == "__main__":
    unittest.main()
