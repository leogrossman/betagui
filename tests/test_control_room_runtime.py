import importlib.util
import unittest
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeAdapter:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.put_calls = []

    def get(self, name, default=None):
        return self.values.get(name, default)

    def put(self, name, value):
        self.put_calls.append((name, value))
        self.values[name] = value
        return True


class ControlRoomRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.module = load_module(root / "control_room" / "betagui.py", "control_room_betagui_runtime")

    def make_state(self, values=None, allow_writes=True):
        module = self.module
        state = module.RuntimeState(config=module.RuntimeConfig(allow_machine_writes=allow_writes))
        state.adapter = FakeAdapter(values)
        return state

    def test_save_setting_requires_valid_rf(self):
        module = self.module
        state = self.make_state({})
        ok = module.save_setting(state)
        self.assertFalse(ok)
        self.assertFalse(state.saved_settings_valid)
        self.assertIn("RF setpoint is unavailable", state.messages[-1])

    def test_reset_refuses_without_valid_snapshot(self):
        module = self.module
        state = self.make_state({})
        ok = module.set_all2ini(state)
        self.assertFalse(ok)
        self.assertIn("Reset is unavailable", state.messages[-1])
        self.assertEqual(state.adapter.put_calls, [])

    def test_measurement_logs_start_immediately(self):
        module = self.module
        state = self.make_state({})
        result = module.MeaChrom(
            state,
            {
                "ntimes": "7",
                "Npoints": "11",
                "dfmin": "-2",
                "dfmax": "2",
                "fit_order": "1",
                "delay_set_rf": "5",
                "delay_mea_Tunes": "1",
                "alpha0": "dynamic",
            },
        )
        self.assertIsNone(result)
        self.assertIn("Starting chromaticity measurement.", state.messages[0])
        self.assertIn("RF sweep plan:", state.messages[1])

    def test_sample_tunes_respects_delay_parameter(self):
        module = self.module
        adapter = FakeAdapter(
            {
                module.pvfreqX: 0.2,
                module.pvfreqY: 0.3,
                module.pvfreqS: 0.01,
            }
        )
        delays = []
        original_sleep = module.time.sleep
        module.time.sleep = delays.append
        try:
            result = module.sample_tunes(adapter, module.BetaguiPVs.legacy(), 3, delay_between_reads_s=0.25)
        finally:
            module.time.sleep = original_sleep
        self.assertAlmostEqual(result["x"], 0.2)
        self.assertEqual(delays, [0.25, 0.25])


if __name__ == "__main__":
    unittest.main()
