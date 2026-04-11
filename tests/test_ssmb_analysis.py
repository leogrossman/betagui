import unittest

from SSMB.ssmb_tool.analyze_session import alpha0_from_eta, fit_slip_factor, reconstruct_delta_first_order


class SSMBAnalysisTest(unittest.TestCase):
    def test_reconstruct_delta_first_order(self):
        orbit = {"bpm1": 2.1e-3, "bpm2": 3.9e-3}
        ref = {"bpm1": 1.0e-4, "bpm2": -1.0e-4}
        dispersion = {"bpm1": 1.0, "bpm2": 2.0}
        delta = reconstruct_delta_first_order(orbit, ref, dispersion)
        self.assertAlmostEqual(delta, 0.0020, places=6)

    def test_fit_slip_factor(self):
        delta = [0.0, 1e-3, 2e-3]
        eta_true = 0.03
        rf0 = 500000.0
        rf = [rf0 * (1.0 - eta_true * value) for value in delta]
        fit = fit_slip_factor(delta, rf)
        self.assertAlmostEqual(fit["eta"], eta_true, places=6)

    def test_alpha0_from_eta(self):
        alpha0 = alpha0_from_eta(eta=0.001, beam_energy_mev=629.0)
        self.assertGreater(alpha0, 0.001)


if __name__ == "__main__":
    unittest.main()
