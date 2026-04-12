import json
import tempfile
import unittest
from pathlib import Path

from SSMB_experiment.ssmb_tool.config import LoggerConfig
from SSMB_experiment.ssmb_tool.epics_io import FakeEpicsAdapter
from SSMB_experiment.ssmb_tool.sweep import (
    PRIMARY_L4_BPM_LABELS,
    RF_PV_NAME,
    SweepRuntimeConfig,
    build_plan_from_hz,
    preview_lines,
    run_rf_sweep_session,
)


class SSMBExperimentSweepTest(unittest.TestCase):
    def test_preview_lines_use_explicit_hz_conversion(self):
        plan = build_plan_from_hz(
            center_rf_pv=499652.5,
            delta_min_hz=-20.0,
            delta_max_hz=20.0,
            n_points=3,
            settle_seconds=0.0,
            samples_per_point=5,
            sample_spacing_seconds=0.25,
        )
        lines = preview_lines(plan, initial_rf_pv=499652.5)
        self.assertIn("Assumed conversion: 1 RF PV unit = 1000 Hz", lines[1])
        self.assertTrue(any("delta -20.000 Hz" in line for line in lines))
        self.assertTrue(any("delta 20.000 Hz" in line for line in lines))

    def test_rf_sweep_restores_initial_rf_and_writes_rich_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LoggerConfig(
                duration_seconds=60.0,
                sample_hz=1.0,
                output_root=Path(tmpdir),
                safe_mode=False,
                allow_writes=True,
                include_bpm_buffer=False,
                include_candidate_bpm_scalars=True,
                include_ring_bpm_scalars=False,
                include_octupoles=False,
                session_label="rf_sweep_bump_off",
            )
            plan = build_plan_from_hz(
                center_rf_pv=499688.38770589296,
                delta_min_hz=-20.0,
                delta_max_hz=20.0,
                n_points=3,
                settle_seconds=0.0,
                samples_per_point=2,
                sample_spacing_seconds=0.0,
            )
            runtime = SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=True)
            adapter = FakeEpicsAdapter(
                {
                    RF_PV_NAME: 499688.38770589296,
                    "TUNEZRP:measX": 0.0,
                    "TUNEZRP:measY": 1450.0,
                    "cumz4x003gp:tuneSyn": 19500.0,
                    "PAHRP:setVoltCav": 40.0,
                    "ERMPCGP:rdRmp": 250.0,
                    "QPD00ZL4RP:rdSigmaX": 0.6,
                    "QPD00ZL4RP:rdSigmaY": 0.2,
                    "BPMZ3L4RP:rdX": -0.06064241411164305,
                    "BPMZ4L4RP:rdX": -0.09744634305495894,
                    "BPMZ5L4RP:rdX": -0.09744634305157819,
                    "BPMZ6L4RP:rdX": -0.05908095004017995,
                },
                allow_writes=True,
            )
            session_dir = run_rf_sweep_session(runtime, adapter=adapter)

            self.assertTrue((session_dir / "metadata.json").exists())
            self.assertTrue((session_dir / "samples.jsonl").exists())
            self.assertTrue((session_dir / "samples.csv").exists())
            self.assertTrue((session_dir / "session.log").exists())
            self.assertEqual(adapter.values[RF_PV_NAME], 499688.38770589296)
            self.assertGreaterEqual(len(adapter.put_calls), 4)

            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["online_analysis"]["primary_l4_bpms"], list(PRIMARY_L4_BPM_LABELS))
            self.assertEqual(metadata["session_status"], "completed")
            self.assertIn("estimated_session_size_bytes", metadata)
            self.assertIn("disk_usage_at_start", metadata)

            log_text = (session_dir / "session.log").read_text(encoding="utf-8")
            self.assertIn("Online analysis sensors:", log_text)
            self.assertIn("α0_BPM=", log_text)
            self.assertIn("samples.jsonl", log_text)

            sample_lines = (session_dir / "samples.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(sample_lines), 1 + plan.n_points * plan.samples_per_point + 1)


if __name__ == "__main__":
    unittest.main()
