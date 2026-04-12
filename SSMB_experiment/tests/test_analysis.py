import json
import tempfile
import unittest
from pathlib import Path

from SSMB_experiment.ssmb_tool.analyze_session import (
    DEFAULT_L4_DISPERSION_M,
    alpha0_from_eta,
    analyze_ssmb_rich_session,
    fit_slip_factor,
    reconstruct_delta_first_order,
)


class SSMBExperimentAnalysisTest(unittest.TestCase):
    def test_reconstruct_delta_first_order(self):
        orbit = {"bpm1": 2.1e-3, "bpm2": 3.9e-3}
        ref = {"bpm1": 1.0e-4, "bpm2": -1.0e-4}
        dispersion = {"bpm1": 1.0, "bpm2": 2.0}
        delta = reconstruct_delta_first_order(orbit, ref, dispersion)
        self.assertAlmostEqual(delta, 0.0020, places=6)

    def test_fit_slip_factor_and_alpha0(self):
        delta = [0.0, 1e-3, 2e-3]
        eta_true = 1.7e-5
        rf0 = 499688.38770589296
        rf = [rf0 * (1.0 - eta_true * value) for value in delta]
        fit = fit_slip_factor(delta, rf)
        self.assertAlmostEqual(fit["eta"], eta_true, places=9)
        self.assertGreater(alpha0_from_eta(fit["eta"], beam_energy_mev=250.0), eta_true)

    def test_analyze_ssmb_rich_session_on_synthetic_rf_sweep(self):
        rf0 = 499688.38770589296
        eta_true = 1.7e-5
        deltas = [0.0, 1.0e-4, 2.0e-4, 3.0e-4]
        bpm_order = list(DEFAULT_L4_DISPERSION_M.items())

        with tempfile.TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir)
            rows = []
            for idx, delta in enumerate(deltas):
                channels = {
                    "rf_readback": {"value": rf0 * (1.0 - eta_true * delta)},
                    "beam_energy_mev": {"value": 250.0},
                    "qpd_l4_sigma_x": {"value": 0.45 + 100.0 * delta},
                }
                for label, dispersion_m in bpm_order:
                    channels[label] = {"value": dispersion_m * delta * 1.0e3}
                row = {
                    "timestamp_epoch_s": 1_000_000.0 + idx,
                    "sample_index": idx,
                    "phase": "baseline" if idx == 0 else "sweep",
                    "channels": channels,
                    "derived": {
                        "delta_l4_bpm_first_order": delta,
                        "tune_x_unitless": 0.0,
                        "tune_y_unitless": 0.21 + 0.5 * delta,
                        "tune_s_unitless": 0.003 + 0.1 * delta,
                        "legacy_alpha0_corrected": 6.3e-4,
                    },
                }
                rows.append(row)
            with (session_dir / "samples.jsonl").open("w", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row) + "\n")

            analysis = analyze_ssmb_rich_session(session_dir)

        self.assertIn("ssmb_rich", analysis)
        self.assertIsNotNone(analysis.get("slip_factor_fit"))
        self.assertIsNotNone(analysis["ssmb_rich"].get("alpha0_from_bpm_eta"))
        self.assertIsNotNone(analysis["ssmb_rich"].get("phase_slip_factor"))
        self.assertEqual(
            analysis["ssmb_rich"]["bpm_labels_used"],
            list(DEFAULT_L4_DISPERSION_M.keys()),
        )
        self.assertNotIn("bpmz7l4rp_x", analysis["ssmb_rich"]["bpm_labels_used"])


if __name__ == "__main__":
    unittest.main()
