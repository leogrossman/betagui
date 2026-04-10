"""Compatibility wrapper for the new write-capable control-room CLI."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Optional, Sequence
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    script_path = PROJECT_ROOT / "control_room" / "betagui_cli.py"
    saved_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path)] + list(argv or [])
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = saved_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
