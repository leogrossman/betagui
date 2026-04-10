import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epics_adapter import BetaguiPVs
from measurement_logic import (
    MeasurementInputs,
    apply_sextupole_response,
    calculate_alpha0,
    measure_chromaticity,
)
from mock_epics import MockEpicsAdapter
import betagui_py3


class MockMeasurementTest(unittest.TestCase):
    def setUp(self):
        self.adapter = MockEpicsAdapter()
        self.pvs = BetaguiPVs.legacy()

    def test_calculate_alpha0_returns_positive_value(self):
        alpha0 = calculate_alpha0(self.adapter, self.pvs)
        self.assertGreater(alpha0, 0.0)

    def test_measure_chromaticity_runs_in_mock_mode(self):
        result = measure_chromaticity(
            self.adapter,
            self.pvs,
            MeasurementInputs(n_tune_samples=3, n_rf_points=5, fit_order=1),
            alpha0=0.03,
        )
        self.assertEqual(result.tune_x_khz.shape[0], 5)
        self.assertEqual(result.tune_y_khz.shape[0], 5)
        self.assertEqual(result.tune_s_khz.shape[0], 5)
        self.assertEqual(len(result.xi), 3)
        self.assertAlmostEqual(
            self.adapter.get(self.pvs.rf_setpoint),
            499_654_096.6666665,
            places=6,
        )

    def test_apply_sextupole_response_updates_expected_pvs(self):
        matrix = np.eye(3)
        applied = apply_sextupole_response(
            self.adapter,
            delta_chrom=[1.0, -2.0, 0.5],
            response_matrix=matrix,
            mat_status=3,
            pvs=self.pvs,
        )
        self.assertIn(self.pvs.sext_s1p1, applied)
        self.assertIn(self.pvs.sext_s1p2, applied)
        self.assertIn(self.pvs.sext_s2p1, applied)
        self.assertIn(self.pvs.sext_s3p1, applied)
        self.assertIn(self.pvs.sext_s3p2, applied)
        self.assertAlmostEqual(self.adapter.get(self.pvs.sext_s1p2), 46.8)
        self.assertAlmostEqual(self.adapter.get(self.pvs.sext_s2p2k), -66.2)

    def test_measure_poly_response_matrix_writes_legacy_output_files(self):
        state = betagui_py3.create_runtime()
        entry_values = {
            "ntimes": "3",
            "Npoints": "3",
            "dfmin": "-0.2",
            "dfmax": "0.2",
            "fit_order": "1",
            "delay_set_rf": "0",
            "delay_mea_Tunes": "0",
            "alpha0": "0.03",
        }
        scan_ranges = [(-1.0, 1.0), (-1.0, 0.0), (-1.0, 1.0), (-1.0, 1.0)]
        with tempfile.TemporaryDirectory() as tmpdir:
            matrix = betagui_py3.measure_poly_response_matrix(
                state,
                entry_values,
                scan_ranges,
                Path(tmpdir),
            )
            self.assertEqual(matrix.shape, (3, 8))
            self.assertTrue((Path(tmpdir) / "ploy_co_mat.txt").exists())
            self.assertTrue((Path(tmpdir) / "bumpdataS1.txt").exists())

    def test_generate_scan_candidates_returns_seven_setpoints(self):
        matrix = np.zeros((3, 8), dtype=float)
        matrix[0, 1] = 1.0
        matrix[1, 3] = 1.0
        candidates = betagui_py3._candidate_settings_from_poly_matrix(
            baseline_currents=[45.8, 45.8, -47.6, -64.2, -64.2, 0.0, 0.0],
            scan_ranges=[(-1.0, 1.0, 3), (-1.0, 1.0, 3), (-1.0, 1.0, 3), (-1.0, 1.0, 3)],
            xi_ranges=[(-0.1, 0.1), (-0.1, 0.1)],
            matrix=matrix,
        )
        self.assertEqual(candidates.shape[1], 7)
        self.assertGreaterEqual(candidates.shape[0], 1)


if __name__ == "__main__":
    unittest.main()
