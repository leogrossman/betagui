from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

from .models import PassiveSample


class SessionRecorder:
    """Persist application-level logs and passive observations incrementally."""

    def __init__(self, output_root: Path):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = output_root / f"laser_mirror_ui_{stamp}"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.session_dir / "app.log"
        self.passive_jsonl_path = self.session_dir / "passive_samples.jsonl"
        self.passive_csv_path = self.session_dir / "passive_samples.csv"
        self.summary_path = self.session_dir / "session_summary.json"
        self._csv_header_written = False
        self._csv_fields: list[str] | None = None
        self._log_handle = self.log_path.open("a", encoding="utf-8")

    def log(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._log_handle.write(f"[{timestamp}] {message}\n")
        self._log_handle.flush()

    def record_sample(self, sample: PassiveSample) -> None:
        payload = asdict(sample)
        with self.passive_jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        if not self._csv_header_written:
            self._csv_fields = list(payload.keys())
            with self.passive_csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=self._csv_fields)
                writer.writeheader()
                writer.writerow(payload)
            self._csv_header_written = True
            return
        with self.passive_csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._csv_fields or list(payload.keys()))
            writer.writerow(payload)

    def write_summary(self, summary: dict[str, object]) -> None:
        self.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    def close(self) -> None:
        try:
            self._log_handle.flush()
        finally:
            self._log_handle.close()

