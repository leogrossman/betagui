#!/usr/bin/env python3
"""Legacy-style write-capable control-room CLI measurement path."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import betagui_py3
from control_room_cli_tools import build_measurement_arg_parser, run_measurement


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_measurement_arg_parser(
        "Write-capable legacy-profile control-room CLI for chromaticity measurement."
    )
    args = parser.parse_args(argv)
    state = betagui_py3.create_runtime(
        betagui_py3.RuntimeConfig(
            use_mock=False,
            allow_machine_writes=True,
            auto_load_default_matrix=not args.no_default_matrix,
            pv_profile="legacy",
            pv_prefix="",
        )
    )
    return run_measurement(state, args)


if __name__ == "__main__":
    raise SystemExit(main())
