import io
import sys
import tempfile
import unittest
from argparse import Namespace
import importlib.util
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import betagui_py3


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MeasureCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.cli = load_module(root / "control_room" / "betagui_cli.py", "control_room_betagui_cli_test")

    def test_parser_uses_dynamic_alpha0_by_default(self):
        parser = self.cli.build_arg_parser()
        args = parser.parse_args([])
        self.assertEqual(args.alpha0, "dynamic")
        self.assertEqual(args.delay_set_rf, "5")
        self.assertEqual(args.delay_mea_tunes, "1")

    def test_run_measurement_with_mock_state(self):
        state = betagui_py3.create_runtime()
        args = Namespace(
            ntimes="3",
            npoints="5",
            dfmin="-0.2",
            dfmax="0.2",
            fit_order="1",
            delay_set_rf="0",
            delay_mea_tunes="0",
            alpha0="0.03",
            output=None,
        )
        capture = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = capture
            result = self.cli.measure_chromaticity(
                state,
                self.cli.MeasurementInputs(
                    n_tune_samples=int(args.ntimes),
                    n_rf_points=int(args.npoints),
                    delta_x_min_mm=float(args.dfmin),
                    delta_x_max_mm=float(args.dfmax),
                    fit_order=int(args.fit_order),
                    delay_after_rf_s=float(args.delay_set_rf),
                    delay_between_tune_reads_s=float(args.delay_mea_tunes),
                ),
                alpha0=float(args.alpha0),
            )
            self.cli.set_frf_slowly(state, state.frf0, delay_s=0.0)
            print("Measured xi:")
            print("  xi_x = %.6f" % result.xi[0])
            print("  xi_y = %.6f" % result.xi[1])
            print("  xi_s = %.6f" % result.xi[2])
            rc = 0
        finally:
            sys.stdout = original_stdout
        self.assertEqual(rc, 0)
        self.assertIn("xi_x", capture.getvalue())

    def test_run_measurement_writes_output_file(self):
        state = betagui_py3.create_runtime()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = Namespace(
                ntimes="3",
                npoints="5",
                dfmin="-0.2",
                dfmax="0.2",
                fit_order="1",
                delay_set_rf="0",
                delay_mea_tunes="0",
                alpha0="0.03",
                output=str(Path(tmpdir) / "xi.txt"),
            )
            result = self.cli.measure_chromaticity(
                state,
                self.cli.MeasurementInputs(
                    n_tune_samples=int(args.ntimes),
                    n_rf_points=int(args.npoints),
                    delta_x_min_mm=float(args.dfmin),
                    delta_x_max_mm=float(args.dfmax),
                    fit_order=int(args.fit_order),
                    delay_after_rf_s=float(args.delay_set_rf),
                    delay_between_tune_reads_s=float(args.delay_mea_tunes),
                ),
                alpha0=float(args.alpha0),
            )
            np.savetxt(args.output, np.asarray(result.xi, dtype=float))
            rc = 0
            self.assertEqual(rc, 0)
            data = np.loadtxt(args.output)
            self.assertEqual(data.shape, (3,))
