#!/usr/bin/env python3
"""Small helper for running betagui in mock mode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import betagui_py3


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run a small mock measurement without starting the GUI.",
    )
    parser.add_argument(
        "--alpha0",
        type=float,
        default=0.03,
        help="Alpha0 used for headless mock measurement.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.headless:
        state = betagui_py3.create_runtime(
            betagui_py3.RuntimeConfig(use_mock=True, allow_machine_writes=False)
        )
        xi = betagui_py3.MeaChrom(
            state,
            {
                "ntimes": "3",
                "Npoints": "5",
                "dfmin": "-0.2",
                "dfmax": "0.2",
                "fit_order": "1",
                "delay_set_rf": "0",
                "delay_mea_Tunes": "0",
                "alpha0": str(args.alpha0),
            },
        )
        print("Measured xi in mock mode:", xi)
        return 0
    return betagui_py3.main([])


if __name__ == "__main__":
    raise SystemExit(main())
