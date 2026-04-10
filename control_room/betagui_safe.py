#!/usr/bin/env python3
"""Read-only legacy-profile control-room GUI launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import betagui_py3


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only legacy-profile control-room GUI."
    )
    parser.add_argument(
        "--no-default-matrix",
        action="store_true",
        help="Do not auto-load the bundled legacy response matrix on startup.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state = betagui_py3.create_runtime(
        betagui_py3.RuntimeConfig(
            use_mock=False,
            allow_machine_writes=False,
            auto_load_default_matrix=not args.no_default_matrix,
            pv_profile="legacy",
            pv_prefix="",
        )
    )
    return betagui_py3.launch_gui(state, window_title="Chromaticity tool pos alpha@MLS [safe]")


if __name__ == "__main__":
    raise SystemExit(main())
