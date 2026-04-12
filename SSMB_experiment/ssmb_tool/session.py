from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parent
SSMB_ROOT = PACKAGE_ROOT.parent
DEFAULT_LOG_DIRNAME = str(SSMB_ROOT / ".ssmb_local" / "ssmb_stage0")


def json_ready(value: Any):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return repr(value)


@dataclass
class SessionLogger:
    session_dir: Path
    text_log_path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def create(cls, root: Optional[Path], prefix: str) -> "SessionLogger":
        root_dir = Path(root) if root is not None else Path.cwd() / DEFAULT_LOG_DIRNAME
        session_name = "%s_%s_pid%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"), os.getpid())
        session_dir = root_dir / session_name
        suffix = 0
        while True:
            candidate = session_dir if suffix == 0 else root_dir / ("%s_%02d" % (session_name, suffix))
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                session_dir = candidate
                break
            except FileExistsError:
                suffix += 1
        return cls(session_dir=session_dir, text_log_path=session_dir / "session.log")

    def log(self, message: str) -> None:
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), message)
        print(line)
        with self._lock:
            with self.text_log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def write_json(self, relative_name: str, payload: Any) -> Path:
        path = self.session_dir / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with path.open("w", encoding="utf-8") as stream:
                json.dump(json_ready(payload), stream, indent=2, sort_keys=True)
                stream.write("\n")
        return path

    def append_jsonl(self, relative_name: str, payload: Any) -> Path:
        path = self.session_dir / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(json_ready(payload), sort_keys=True) + "\n")
                stream.flush()
        return path


def disk_usage_summary(path: Path) -> Dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"total_bytes": int(usage.total), "used_bytes": int(usage.used), "free_bytes": int(usage.free)}
