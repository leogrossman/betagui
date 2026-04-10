#!/usr/bin/env python3
"""Development launcher for mock mode, digital twin mode, and debugging."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import betagui_py3


if __name__ == "__main__":
    raise SystemExit(betagui_py3.main())
