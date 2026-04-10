"""Compatibility wrapper for the new control-room safe GUI launcher."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Optional, Sequence

def main(argv: Optional[Sequence[str]] = None) -> int:
    script_path = Path(__file__).resolve().parents[1] / "control_room" / "betagui_safe.py"
    saved_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path)] + list(argv or [])
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = saved_argv
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
