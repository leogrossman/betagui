import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import betagui_py3


class OutputRegressionTest(unittest.TestCase):
    def test_mock_chromaticity_matches_reference_fixture(self):
        state = betagui_py3.create_runtime()
        xi = betagui_py3.MeaChrom(
            state,
            {
                "ntimes": "3",
                "Npoints": "5",
                "dfmin": "-0.2",
                "dfmax": "0.2",
                "fit_order": "1",
                "delay_set_rf": "0",
                "delay_mea_Tunes": "0",
                "alpha0": "0.03",
            },
        )
        expected = np.loadtxt(Path(__file__).resolve().parent / "data" / "mock_chromaticity_expected.txt")
        np.testing.assert_allclose(np.asarray(xi, dtype=float), expected, atol=1e-9, rtol=0.0)
