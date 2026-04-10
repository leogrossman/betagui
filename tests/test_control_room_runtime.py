import importlib.util
import json
import tempfile
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

    def test_session_logger_writes_files_under_requested_root(self):
        module = self.module
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = module.SessionLogger.create(Path(tmpdir), "betagui_gui")
            logger.log_line("hello")
            logger.record("event_test", value=1)
            payload_path = logger.write_payload("measurements/test.json", {"ok": True})
            self.assertTrue(str(logger.session_dir).startswith(tmpdir))
            self.assertTrue(logger.text_log_path.exists())
            self.assertTrue(logger.event_log_path.exists())
            self.assertTrue(payload_path.exists())

    def test_measurement_logging_creates_raw_payload_without_large_event_log(self):
        module = self.module
        values = {
            module.pvfrfSet: 499654096.666667,
            module.pvfreqX: 0.20,
            module.pvfreqY: 0.22,
            module.pvfreqS: 0.01,
            module.pvOptTab: 0,
            module.pvfdbsetX: 1.0,
            module.pvfdbsetY: 1.0,
            module.pvfdbsetS: 1.0,
            module.pvorbitrdbk: 1.0,
            module.pvUcavSet: 150.0,
            module.pvE: 630.0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config = module.RuntimeConfig(allow_machine_writes=True, auto_load_default_matrix=False, log_root=Path(tmpdir))
            state = module.RuntimeState(config=config)
            state.session_logger = module.SessionLogger.create(Path(tmpdir), "betagui_gui")
            state.adapter = module.GuardedAdapter(FakeAdapter(values), True, state.log, event_recorder=state.record_event)
            entry_values = {
                "ntimes": "3",
                "Npoints": "5",
                "dfmin": "-0.2",
                "dfmax": "0.2",
                "fit_order": "1",
                "delay_set_rf": "0",
                "delay_mea_Tunes": "0",
                "alpha0": "0.03",
            }
            xi = module.MeaChrom(state, entry_values)
            self.assertIsNotNone(xi)
            self.assertTrue(state.session_logger.session_dir.exists())
            measurement_files = sorted((state.session_logger.session_dir / "measurements").glob("chromaticity_*.json"))
            self.assertEqual(len(measurement_files), 1)
            payload = json.loads(measurement_files[0].read_text(encoding="utf-8"))
            self.assertEqual(len(payload["result"]["point_records"]), 5)
            self.assertIn("machine_context", payload["result"]["point_records"][0])
            event_log_size = state.session_logger.event_log_path.stat().st_size
            self.assertLess(event_log_size, 30000)


if __name__ == "__main__":
    unittest.main()
