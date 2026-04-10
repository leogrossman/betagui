import io
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import betagui_py3
import control_room_cli_tools


class MeasureCliTest(unittest.TestCase):
    def test_parser_uses_dynamic_alpha0_by_default(self):
        parser = control_room_cli_tools.build_measurement_arg_parser("test")
        args = parser.parse_args([])
        self.assertEqual(args.alpha0, "dynamic")

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
            rc = control_room_cli_tools.run_measurement(state, args)
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
            rc = control_room_cli_tools.run_measurement(state, args)
            self.assertEqual(rc, 0)
            data = np.loadtxt(args.output)
            self.assertEqual(data.shape, (3,))
