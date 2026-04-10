import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MachineCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.module = load_module(root / "control_room" / "machine_check.py", "machine_check_test")

    def test_restore_actions_only_include_writable_pvs(self):
        module = self.module
        snapshot = {
            "records": [
                {"label": "rf_setpoint", "pv": "MCLKHGP:setFrq", "value": 1.0},
                {"label": "tune_x", "pv": "TUNEZRP:measX", "value": 0.2},
                {"label": "S1P1", "pv": "S1P1RP:setCur", "value": 3.0},
            ]
        }
        actions = module.restore_actions(snapshot)
        labels = [item[0] for item in actions]
        self.assertEqual(labels, ["rf_setpoint", "S1P1"])

    def test_diff_snapshot_reports_changed_rf(self):
        module = self.module
        saved = {
            "records": [
                {"label": "rf_setpoint", "pv": "MCLKHGP:setFrq", "value": 100.0},
                {"label": "tune_x", "pv": "TUNEZRP:measX", "value": 0.2},
            ]
        }
        current = {
            "records": [
                {"label": "rf_setpoint", "pv": "MCLKHGP:setFrq", "value": 101.0},
                {"label": "tune_x", "pv": "TUNEZRP:measX", "value": 0.2},
            ]
        }
        diffs = module.diff_snapshot(saved, current)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["label"], "rf_setpoint")

    def test_snapshot_output_root_defaults_to_cwd(self):
        module = self.module
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            original_cwd = Path.cwd()
            try:
                import os
                os.chdir(root)
                out = module._output_root(None)
            finally:
                os.chdir(original_cwd)
            self.assertEqual(out, root / "control_room_outputs" / "machine_checks")


if __name__ == "__main__":
    unittest.main()
