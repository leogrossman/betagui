import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import betagui_py3


class MatrixIoTest(unittest.TestCase):
    def test_load_legacy_3d_matrix(self):
        state = betagui_py3.create_runtime()
        ok = betagui_py3.load_matrix_file(
            state, Path("original/SUwithoutorbitbumpResMat.txt")
        )
        self.assertTrue(ok)
        self.assertEqual(state.B.shape, (3, 3))
        self.assertEqual(state.mat_status, 3)

    def test_load_legacy_2d_matrix(self):
        state = betagui_py3.create_runtime()
        ok = betagui_py3.load_matrix_file(
            state, Path("original/SUwithoutorbitbumpResMat2D.txt")
        )
        self.assertTrue(ok)
        self.assertEqual(state.B.shape, (2, 2))
        self.assertEqual(state.mat_status, 1)

    def test_save_and_reload_matrix(self):
        state = betagui_py3.create_runtime()
        state.B = np.array([[1.0, 2.0], [3.0, 4.0]])
        state.mat_status = 1
        state.bump_dim = 2
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "matrix.txt"
            self.assertTrue(betagui_py3.save_matrix_file(state, output))
            reloaded = betagui_py3.create_runtime()
            self.assertTrue(betagui_py3.load_matrix_file(reloaded, output))
            np.testing.assert_allclose(reloaded.B, state.B)
            self.assertEqual(reloaded.mat_status, 1)


if __name__ == "__main__":
    unittest.main()
