from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.models import PassiveSample
from laser_mirrors_app.monitoring import SessionRecorder


class MonitoringTests(unittest.TestCase):
    def test_session_recorder_writes_log_and_samples(self) -> None:
        root = Path(tempfile.mkdtemp())
        recorder = SessionRecorder(root)
        recorder.log("hello world")
        sample = PassiveSample(
            elapsed_s=1.2,
            signal_label="P1",
            signal_pv="pv",
            signal_value=3.4,
            m1_horizontal=1.0,
            m1_vertical=2.0,
            m2_horizontal=3.0,
            m2_vertical=4.0,
            dmov_all=1,
            movn_any=0,
        )
        recorder.record_sample(sample)
        recorder.write_summary({"ok": True})
        recorder.close()
        self.assertTrue(recorder.log_path.exists())
        self.assertTrue(recorder.passive_jsonl_path.exists())
        self.assertTrue(recorder.passive_csv_path.exists())
        self.assertTrue(recorder.summary_path.exists())
        self.assertIn("hello world", recorder.log_path.read_text())
        summary = json.loads(recorder.summary_path.read_text())
        self.assertEqual(summary["ok"], True)


if __name__ == "__main__":
    unittest.main()
