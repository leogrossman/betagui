import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


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

    def test_synchrotron_pv_is_scaled_from_hz_to_khz_and_unitless_qs(self):
        module = self.module
        adapter = FakeAdapter(
            {
                module.pvfreqX: 1099.0,
                module.pvfreqY: 1408.0,
                module.pvfreqS: 11605.0,
                module.pvUcavSet: 150.0,
                module.pvE: 630.0,
                module.pvfrfSet: 499652.0,
            }
        )
        sampled = module.sample_tunes(adapter, module.BetaguiPVs.legacy(), 3, delay_between_reads_s=0.0)
        self.assertAlmostEqual(sampled["x"], 1099.0)
        self.assertAlmostEqual(sampled["y"], 1408.0)
        self.assertAlmostEqual(sampled["s"], 11.605)
        alpha0, details = module.calculate_alpha0_with_details(adapter, module.BetaguiPVs.legacy(), samples=3)
        self.assertLess(alpha0, 0.01)
        self.assertAlmostEqual(details["tune_s_mean_khz"], 11.605)
        self.assertAlmostEqual(details["tune_s_mean_unitless"], 11.605 / module.REVOLUTION_FREQUENCY_KHZ)

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

    def test_apply_sextupole_response_rejects_missing_current_readback(self):
        module = self.module
        adapter = FakeAdapter({})
        with self.assertRaises(ValueError):
            module.apply_sextupole_response(
                adapter=adapter,
                delta_chrom=[1.0, 0.0, 0.0],
                response_matrix=np.eye(3),
                mat_status=3,
                pvs=module.BetaguiPVs.legacy(),
            )

    def test_apply_sextupole_response_p2_mode_only_touches_p2_families(self):
        module = self.module
        values = {
            module.pvS1P2: 10.0,
            module.pvS2P2K: 20.0,
            module.pvS2P2L: 20.0,
            module.pvS3P2: 30.0,
            module.pvS1P1: 11.0,
            module.pvS2P1: 21.0,
            module.pvS3P1: 31.0,
        }
        adapter = FakeAdapter(values)
        applied = module.apply_sextupole_response(
            adapter=adapter,
            delta_chrom=[1.0, 2.0, 3.0],
            response_matrix=np.eye(3),
            mat_status=4,
            pvs=module.BetaguiPVs.legacy(),
        )
        self.assertIn(module.pvS1P2, applied)
        self.assertIn(module.pvS2P2K, applied)
        self.assertIn(module.pvS2P2L, applied)
        self.assertIn(module.pvS3P2, applied)
        self.assertNotIn(module.pvS1P1, applied)
        self.assertNotIn(module.pvS2P1, applied)
        self.assertNotIn(module.pvS3P1, applied)

    def test_response_matrix_restores_axis_after_minus_failure(self):
        module = self.module
        values = {
            module.pvS1P1: 11.0,
            module.pvS1P2: 12.0,
            module.pvS2P1: 21.0,
            module.pvS2P2K: 22.0,
            module.pvS2P2L: 23.0,
            module.pvS3P1: 31.0,
            module.pvS3P2: 32.0,
        }
        state = self.make_state(values, allow_writes=True)
        state.bump_option = 3
        original_mea = module.MeaChrom
        module.MeaChrom = lambda _state, _entries: None
        try:
            result = module.measure_response_matrix(state, {"alpha0": "0.03"})
        finally:
            module.MeaChrom = original_mea
        self.assertIsNone(result)
        self.assertEqual(state.adapter.values[module.pvS1P1], 11.0)
        self.assertEqual(state.adapter.values[module.pvS1P2], 12.0)

    def test_response_matrix_computes_inverse_and_writes_payload(self):
        module = self.module
        values = {
            module.pvS1P1: 11.0,
            module.pvS1P2: 12.0,
            module.pvS2P1: 21.0,
            module.pvS2P2K: 22.0,
            module.pvS2P2L: 23.0,
            module.pvS3P1: 31.0,
            module.pvS3P2: 32.0,
            module.pvfrfSet: 499652.0,
            module.pvfreqX: 1100.0,
            module.pvfreqY: 1400.0,
            module.pvfreqS: 11500.0,
            module.pvOptTab: 2.0,
            module.pvfdbsetX: 1.0,
            module.pvfdbsetY: 1.0,
            module.pvfdbsetS: 1.0,
            module.pvorbitrdbk: 1.0,
            module.pvUcavSet: 480.0,
            module.pvE: 629.0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config = module.RuntimeConfig(allow_machine_writes=True, auto_load_default_matrix=False, log_root=Path(tmpdir))
            state = module.RuntimeState(config=config)
            state.session_logger = module.SessionLogger.create(Path(tmpdir), "betagui_gui")
            state.adapter = module.GuardedAdapter(FakeAdapter(values), True, state.log, event_recorder=state.record_event)
            state.bump_option = 3
            sequence = iter(
                [
                    [0.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0], [0.0, 3.0, 0.0],
                    [0.0, 0.0, 0.0], [0.0, 0.0, 4.0],
                ]
            )
            original_mea = module.MeaChrom
            module.MeaChrom = lambda _state, _entries: next(sequence)
            try:
                matrix = module.measure_response_matrix(state, {"alpha0": "0.03"})
            finally:
                module.MeaChrom = original_mea
            self.assertTrue(np.allclose(matrix, np.diag([0.5, 1.0 / 3.0, 0.25])))
            inner_adapter = state.adapter._adapter
            self.assertIn((module.pvS1P1, 10.0), inner_adapter.put_calls)
            self.assertIn((module.pvS1P2, 11.0), inner_adapter.put_calls)
            self.assertEqual(inner_adapter.values[module.pvS1P1], 11.0)
            self.assertEqual(inner_adapter.values[module.pvS1P2], 12.0)
            payload_files = sorted((state.session_logger.session_dir / "measurements").glob("response_matrix_*.json"))
            self.assertEqual(len(payload_files), 1)
            payload = json.loads(payload_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["bump_dim"], 3)
            self.assertEqual(len(payload["axis_records"]), 3)
            self.assertEqual(payload["axis_records"][0]["baseline_currents"][module.pvS1P1], 11.0)
            self.assertEqual(payload["axis_records"][0]["minus_targets"][module.pvS1P1], 10.0)
            self.assertEqual(payload["axis_records"][0]["plus_targets"][module.pvS1P1], 11.0)

    def test_export_measurement_result_writes_csv_and_json(self):
        module = self.module
        state = self.make_state({})
        result = module.MeasurementResult(
            rf_points_hz=np.asarray([1.0, 2.0]),
            delta_hz=np.asarray([-0.5, 0.5]),
            tune_x_khz=np.asarray([1100.0, 1101.0]),
            tune_y_khz=np.asarray([1400.0, 1401.0]),
            tune_s_khz=np.asarray([11.5, 11.6]),
            fit_x=np.poly1d([1.0, 0.0]),
            fit_y=np.poly1d([1.0, 0.0]),
            fit_s=np.poly1d([1.0, 0.0]),
            xi=[1.0, 2.0, 3.0],
            alpha0=0.03,
            point_records=[
                {
                    "rf_target_hz": 1.0,
                    "rf_readback_hz": 1.0,
                    "tune_x_mean_khz": 1100.0,
                    "tune_y_mean_khz": 1400.0,
                    "tune_s_mean_khz": 11.5,
                    "tune_x_mean_unitless": 0.1,
                    "tune_y_mean_unitless": 0.2,
                    "tune_s_mean_unitless": 0.01,
                },
                {
                    "rf_target_hz": 2.0,
                    "rf_readback_hz": 2.0,
                    "tune_x_mean_khz": 1101.0,
                    "tune_y_mean_khz": 1401.0,
                    "tune_s_mean_khz": 11.6,
                    "tune_x_mean_unitless": 0.11,
                    "tune_y_mean_unitless": 0.21,
                    "tune_s_mean_unitless": 0.011,
                },
            ],
            fit_x_coeffs=[1.0, 0.0],
            fit_y_coeffs=[1.0, 0.0],
            fit_s_coeffs=[1.0, 0.0],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "result"
            ok = module.export_measurement_result(state, result, {"alpha0": "0.03"}, target)
            self.assertTrue(ok)
            self.assertTrue((Path(tmpdir) / "result.csv").exists())
            self.assertTrue((Path(tmpdir) / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
