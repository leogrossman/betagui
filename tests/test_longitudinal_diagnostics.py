import importlib.util
import math
import sys
import unittest
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LongitudinalDiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.module = load_module(
            root / "control_room" / "tools" / "longitudinal_diagnostics.py",
            "longitudinal_diagnostics_test",
        )

    def test_parse_extra_pvs(self):
        mapping = self.module.parse_extra_pvs(["alpha1=PV:ALPHA1", "oct1=PV:OCT1"])
        self.assertEqual(mapping["alpha1"], "PV:ALPHA1")
        self.assertEqual(mapping["oct1"], "PV:OCT1")

    def test_dominant_modulation_frequency(self):
        sample_hz = 10.0
        values = [math.sin(2.0 * math.pi * 1.5 * n / sample_hz) for n in range(100)]
        dominant = self.module.dominant_modulation_frequency(values, sample_hz)
        self.assertIsNotNone(dominant)
        self.assertAlmostEqual(dominant, 1.5, delta=0.2)

    def test_analyze_samples_reports_correlation(self):
        rows = []
        for index in range(20):
            rows.append(
                {
                    "t_rel_s": float(index),
                    "rf_pv": float(index),
                    "tune_x_raw": float(index),
                    "tune_y_raw": float(index) * 2.0,
                    "tune_s_raw": float(index),
                }
            )
        summary = self.module.analyze_samples(rows, sample_hz=2.0)
        correlation = summary["correlations"]["tune_s_raw_vs_rf_pv"]
        self.assertIsNotNone(correlation)
        self.assertGreater(correlation, 0.99)


if __name__ == "__main__":
    unittest.main()
