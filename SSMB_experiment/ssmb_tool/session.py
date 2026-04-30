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
JSONL_ROTATE_BYTES = 16 * 1024 * 1024


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
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _jsonl_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)

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
        path = self._jsonl_target(relative_name)
        with self._lock:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(json_ready(payload), sort_keys=True) + "\n")
                stream.flush()
        return path

    def _jsonl_target(self, relative_name: str) -> Path:
        with self._lock:
            state = self._jsonl_state.get(relative_name)
            if state is None:
                path = self.session_dir / relative_name
                path.parent.mkdir(parents=True, exist_ok=True)
                state = {"index": 1, "path": path}
                self._jsonl_state[relative_name] = state
            path = state["path"]
            try:
                size = path.stat().st_size if path.exists() else 0
            except Exception:
                size = 0
            if size >= JSONL_ROTATE_BYTES:
                rel_path = Path(relative_name)
                stem = rel_path.stem
                suffix = rel_path.suffix or ".jsonl"
                state["index"] = int(state.get("index", 1)) + 1
                rotated = rel_path.with_name("%s_part%03d%s" % (stem, state["index"], suffix))
                path = self.session_dir / rotated
                path.parent.mkdir(parents=True, exist_ok=True)
                state["path"] = path
            return path


def disk_usage_summary(path: Path) -> Dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"total_bytes": int(usage.total), "used_bytes": int(usage.used), "free_bytes": int(usage.free)}
