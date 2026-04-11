import json
import tempfile
import unittest
from pathlib import Path

from SSMB.ssmb_tool.config import LoggerConfig
from SSMB.ssmb_tool.epics_io import FakeEpicsAdapter
from SSMB.ssmb_tool.sweep import RF_PV_NAME, RF_PV_UNITS_PER_HZ, SweepRuntimeConfig, build_plan_from_hz, preview_lines, run_rf_sweep_session


class SSMBSweepTest(unittest.TestCase):
    def test_preview_lines_use_explicit_hz_conversion(self):
        plan = build_plan_from_hz(center_rf_pv=499652.5, delta_min_hz=-100.0, delta_max_hz=100.0, n_points=3, settle_seconds=0.0, samples_per_point=1, sample_spacing_seconds=0.0)
        lines = preview_lines(plan, initial_rf_pv=499652.5)
        self.assertIn("Assumed conversion: 1 RF PV unit = 1000 Hz", lines[1])
        self.assertTrue(any("delta -100.000 Hz" in line for line in lines))
        self.assertTrue(any("delta 100.000 Hz" in line for line in lines))

    def test_rf_sweep_requires_explicit_write_enable(self):
        config = LoggerConfig(duration_seconds=1.0, sample_hz=1.0, output_root=Path(tempfile.gettempdir()) / "unused")
        plan = build_plan_from_hz(center_rf_pv=499652.5, delta_min_hz=-10.0, delta_max_hz=10.0, n_points=3, settle_seconds=0.0, samples_per_point=1, sample_spacing_seconds=0.0)
        runtime = SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=False)
        with self.assertRaises(ValueError):
            runtime.validate()

    def test_rf_sweep_restores_initial_rf_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LoggerConfig(
                duration_seconds=1.0,
                sample_hz=1.0,
                output_root=Path(tmpdir),
                safe_mode=False,
                allow_writes=True,
                include_bpm_buffer=False,
                include_candidate_bpm_scalars=False,
                include_ring_bpm_scalars=False,
                include_octupoles=False,
                session_label="bump_on",
            )
            plan = build_plan_from_hz(center_rf_pv=499652.5, delta_min_hz=-10.0, delta_max_hz=10.0, n_points=3, settle_seconds=0.0, samples_per_point=1, sample_spacing_seconds=0.0)
            runtime = SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=True)
            adapter = FakeEpicsAdapter(
                {
                    RF_PV_NAME: 499652.5,
                    "TUNEZRP:measX": 1100.0,
                    "TUNEZRP:measY": 1400.0,
                    "cumz4x003gp:tuneSyn": 11500.0,
                    "PAHRP:setVoltCav": 480.0,
                    "ERMPCGP:rdRmp": 629.0,
                },
                allow_writes=True,
            )
            session_dir = run_rf_sweep_session(runtime, adapter=adapter)
            self.assertTrue((session_dir / "metadata.json").exists())
            self.assertTrue((session_dir / "samples.jsonl").exists())
            self.assertTrue((session_dir / "samples.csv").exists())
            self.assertTrue((session_dir / "session.log").exists())
            self.assertEqual(adapter.values[RF_PV_NAME], 499652.5)
            self.assertGreaterEqual(len(adapter.put_calls), 4)
            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["sweep_plan"]["n_points"], 3)
            self.assertEqual(metadata["config"]["session_label"], "bump_on")

    def test_rf_plan_conversion_matches_pv_units(self):
        plan = build_plan_from_hz(center_rf_pv=500000.0, delta_min_hz=-50.0, delta_max_hz=50.0, n_points=3, settle_seconds=0.0, samples_per_point=1, sample_spacing_seconds=0.0)
        points = plan.rf_points_pv()
        self.assertAlmostEqual(points[0], 500000.0 - 50.0 * RF_PV_UNITS_PER_HZ)
        self.assertAlmostEqual(points[2], 500000.0 + 50.0 * RF_PV_UNITS_PER_HZ)


if __name__ == "__main__":
    unittest.main()
