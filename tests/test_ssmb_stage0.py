import json
import tempfile
import unittest
from pathlib import Path

from SSMB.ssmb_tool import analyze_session, inventory, lattice, log_now
from SSMB.ssmb_tool.config import LoggerConfig
from SSMB.ssmb_tool.epics_io import FakeEpicsAdapter, ReadOnlyViolationError


class SSMBStage0Test(unittest.TestCase):
    def test_default_inventory_contains_rf_and_tunes(self):
        context = lattice.LatticeContext.load(Path("SSMB/MLS_lattice/mls_lattice_low_emittance_export.json"))
        specs = inventory.build_default_inventory(context)
        labels = {spec.label for spec in specs}
        self.assertIn("rf_setpoint", labels)
        self.assertIn("tune_x_raw", labels)
        self.assertIn("tune_s_raw", labels)
        self.assertIn("s1m2k1rp", labels)
        self.assertIn("q3m2k1rp", labels)

    def test_fake_adapter_blocks_put(self):
        adapter = FakeEpicsAdapter({"pv": 1.0})
        with self.assertRaises(ReadOnlyViolationError):
            adapter.put("pv", 2.0)

    def test_stage0_logger_writes_required_files_with_missing_pvs(self):
        class MissingAdapter:
            def get(self, _name, default=None):
                return default

            def put(self, _name, _value):
                raise ReadOnlyViolationError("no writes")

        original_factory = log_now.ReadOnlyEpicsAdapter
        log_now.ReadOnlyEpicsAdapter = lambda timeout=0.5: MissingAdapter()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config = LoggerConfig(
                    duration_seconds=0.25,
                    sample_hz=2.0,
                    output_root=Path(tmpdir),
                    include_bpm_buffer=False,
                    include_candidate_bpm_scalars=False,
                )
                session_dir = log_now.run_stage0_logger(config)
                self.assertTrue((session_dir / "metadata.json").exists())
                self.assertTrue((session_dir / "samples.jsonl").exists())
                self.assertTrue((session_dir / "samples.csv").exists())
                self.assertTrue((session_dir / "session.log").exists())
                metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertGreaterEqual(metadata["sample_count"], 1)
                self.assertIn("rf_setpoint", metadata["missing_pvs"])
        finally:
            log_now.ReadOnlyEpicsAdapter = original_factory

    def test_stage0_logger_rejects_write_capable_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LoggerConfig(
                duration_seconds=1.0,
                sample_hz=1.0,
                output_root=Path(tmpdir),
                safe_mode=False,
                allow_writes=True,
            )
            with self.assertRaises(ValueError):
                log_now.run_stage0_logger(config, adapter=FakeEpicsAdapter({}))

    def test_stage0_session_label_appears_in_session_dir_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            class MissingAdapter:
                def get(self, _name, default=None):
                    return default
            config = LoggerConfig(
                duration_seconds=0.25,
                sample_hz=1.0,
                output_root=Path(tmpdir),
                include_bpm_buffer=False,
                include_candidate_bpm_scalars=False,
                include_ring_bpm_scalars=False,
                include_quadrupoles=False,
                include_sextupoles=False,
                include_octupoles=False,
                session_label="bump_on",
            )
            session_dir = log_now.run_stage0_logger(config, adapter=MissingAdapter())
            self.assertIn("bump_on", session_dir.name)

    def test_parse_extra_pvs(self):
        mapping = log_now.parse_labeled_pvs(["alpha1=PV:ALPHA1", "eta2=PV:ETA2"])
        self.assertEqual(mapping["alpha1"], "PV:ALPHA1")
        self.assertEqual(mapping["eta2"], "PV:ETA2")


if __name__ == "__main__":
    unittest.main()
