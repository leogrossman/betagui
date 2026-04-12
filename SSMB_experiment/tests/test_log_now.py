import json
import tempfile
import threading
import unittest
from pathlib import Path

from SSMB_experiment.ssmb_tool.config import DEFAULT_LATTICE_EXPORT
from SSMB_experiment.ssmb_tool.config import LoggerConfig
from SSMB_experiment.ssmb_tool.epics_io import FakeEpicsAdapter
from SSMB_experiment.ssmb_tool.inventory import build_default_inventory
from SSMB_experiment.ssmb_tool.lattice import LatticeContext
from SSMB_experiment.ssmb_tool.log_now import _derived_metrics, run_stage0_logger


class SSMBExperimentLogNowTest(unittest.TestCase):
    def test_derived_metrics_include_bpm_and_qpd_estimators(self):
        sample = {
            "channels": {
                "rf_readback": {"value": 499688.38770589296},
                "tune_x_raw": {"value": 0.0},
                "tune_y_raw": {"value": 1450.0},
                "tune_s_raw": {"value": 19500.0},
                "beam_energy_mev": {"value": 250.0},
                "cavity_voltage_kv": {"value": 40.0},
                "qpd_l4_sigma_x": {"value": 0.6},
                "qpd_l4_sigma_y": {"value": 0.2},
                "bpmz3l4rp_x": {"value": -0.06064241411164305},
                "bpmz4l4rp_x": {"value": -0.09744634305495894},
                "bpmz5l4rp_x": {"value": -0.09744634305157819},
                "bpmz6l4rp_x": {"value": -0.05908095004017995},
            }
        }
        derived = _derived_metrics(
            sample,
            derived_context={
                "rf_reference_khz": 499688.38770589296,
                "l4_bpm_reference_mm": {
                    "bpmz3l4rp_x": 0.0,
                    "bpmz4l4rp_x": 0.0,
                    "bpmz5l4rp_x": 0.0,
                    "bpmz6l4rp_x": 0.0,
                },
            },
        )
        self.assertAlmostEqual(derived["delta_l4_bpm_first_order"], 1.0e-4, places=8)
        self.assertAlmostEqual(derived["beam_energy_from_bpm_mev"], 250.025, places=6)
        self.assertIsNotNone(derived["legacy_alpha0_corrected"])
        self.assertIsNotNone(derived["qpd_l4_sigma_delta_first_order"])
        self.assertEqual(
            derived["delta_l4_bpms_used"],
            ["bpmz3l4rp_x", "bpmz4l4rp_x", "bpmz5l4rp_x", "bpmz6l4rp_x"],
        )
        self.assertEqual(derived["bpm_x_nonlinear_labels"], [])

    def test_derived_metrics_flag_nonlinear_bpms(self):
        sample = {
            "channels": {
                "beam_energy_mev": {"value": 250.0},
                "bpmz3l4rp_x": {"value": 4.2},
                "bpmz4l4rp_x": {"value": 3.2},
                "bpmz5l4rp_x": {"value": 0.5},
                "bpmz6l4rp_x": {"value": -4.6},
            }
        }
        derived = _derived_metrics(sample, derived_context={"l4_bpm_reference_mm": {}})
        lookup = {item["label"]: item for item in derived["bpm_x_status"]}
        self.assertEqual(lookup["bpmz3l4rp_x"]["severity"], "red")
        self.assertEqual(lookup["bpmz4l4rp_x"]["severity"], "yellow")
        self.assertEqual(lookup["bpmz5l4rp_x"]["severity"], "green")
        self.assertEqual(lookup["bpmz6l4rp_x"]["severity"], "red")
        self.assertEqual(set(derived["bpm_x_nonlinear_labels"]), {"bpmz3l4rp_x", "bpmz6l4rp_x"})

    def test_inventory_includes_recovered_bump_hardware(self):
        lattice = LatticeContext.load(DEFAULT_LATTICE_EXPORT)
        specs = build_default_inventory(lattice)
        lookup = {spec.label: spec for spec in specs}
        self.assertEqual(lookup["l4_bump_hcorr_k3_upstream"].pv, "HS1P2K3RP:setCur")
        self.assertEqual(lookup["l4_bump_hcorr_l4_upstream"].pv, "HS3P1L4RP:setCur")
        self.assertEqual(lookup["l4_bump_hcorr_l4_downstream"].pv, "HS3P2L4RP:setCur")
        self.assertEqual(lookup["l4_bump_hcorr_k1_downstream"].pv, "HS1P1K1RP:setCur")
        self.assertEqual(lookup["l4_bump_feedback_enable"].pv, "AKC10VP")
        self.assertEqual(lookup["l4_bump_feedback_gain"].pv, "AKC11VP")
        self.assertEqual(lookup["l4_bump_feedback_ref"].pv, "AKC12VP")
        self.assertEqual(lookup["l4_bump_feedback_deadband"].pv, "AKC13VP")
        self.assertEqual(lookup["rf_frequency_control_enable"].pv, "MCLKHGP:ctrl:enable")
        self.assertEqual(lookup["l4_bump_orbit_bpm_l4"].pv, "BPMZ1L4RP:rdX")
        self.assertEqual(lookup["qpd_l4_sigma_y_avg"].pv, "QPD00ZL4RP:rdSigmaYav")
        self.assertEqual(lookup["qpd_l2_sigma_y_avg"].pv, "QPD01ZL2RP:rdSigmaYav")

    def test_manual_stop_event_still_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stop_event = threading.Event()
            stop_event.set()
            config = LoggerConfig(
                duration_seconds=120.0,
                sample_hz=1.0,
                output_root=Path(tmpdir),
                include_bpm_buffer=False,
                include_candidate_bpm_scalars=True,
                include_ring_bpm_scalars=False,
                include_quadrupoles=False,
                include_sextupoles=False,
                include_octupoles=False,
                session_label="manual_test",
            )
            adapter = FakeEpicsAdapter(
                {
                    "MCLKHGP:setFrq": 499688.38770589296,
                    "ERMPCGP:rdRmp": 250.0,
                }
            )
            session_dir = run_stage0_logger(
                config,
                adapter=adapter,
                stop_event=stop_event,
                session_prefix="ssmb_manual",
                extra_metadata={"manual_stop_mode": True},
            )
            self.assertTrue((session_dir / "metadata.json").exists())
            self.assertTrue((session_dir / "samples.jsonl").exists())
            self.assertTrue((session_dir / "samples.csv").exists())
            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["session_status"], "completed")
            self.assertEqual(metadata["partial_sample_count"], 0)
            self.assertTrue(metadata["manual_stop_mode"])
            log_text = (session_dir / "session.log").read_text(encoding="utf-8")
            self.assertIn("Stop requested by operator", log_text)


if __name__ == "__main__":
    unittest.main()
