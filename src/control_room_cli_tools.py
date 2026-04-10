"""Small helpers shared by the control-room CLI entrypoints."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

import numpy as np

import betagui_py3


def build_measurement_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--ntimes", default="7", help="Number of tune samples at each RF point.")
    parser.add_argument("--npoints", default="11", help="Number of RF points in the sweep.")
    parser.add_argument("--dfmin", default="-2", help="Minimum X-dispersion offset input in mm.")
    parser.add_argument("--dfmax", default="2", help="Maximum X-dispersion offset input in mm.")
    parser.add_argument("--fit-order", default="1", help="Polynomial fit order.")
    parser.add_argument("--delay-set-rf", default="5", help="Delay after changing RF, in seconds.")
    parser.add_argument("--delay-mea-tunes", default="1", help="Delay between tune reads, in seconds.")
    parser.add_argument(
        "--alpha0",
        default="dynamic",
        help="Alpha0 value or 'dynamic'. Use a numeric value if dynamic alpha0 is unavailable.",
    )
    parser.add_argument("--output", help="Optional text file to save the measured xi vector.")
    parser.add_argument(
        "--no-default-matrix",
        action="store_true",
        help="Do not auto-load the bundled legacy matrix files on startup.",
    )
    return parser


def measurement_entry_values(args: argparse.Namespace) -> Dict[str, str]:
    return {
        "ntimes": str(args.ntimes),
        "Npoints": str(args.npoints),
        "dfmin": str(args.dfmin),
        "dfmax": str(args.dfmax),
        "fit_order": str(args.fit_order),
        "delay_set_rf": str(args.delay_set_rf),
        "delay_mea_Tunes": str(args.delay_mea_tunes),
        "alpha0": str(args.alpha0),
    }


def run_measurement(state: "betagui_py3.RuntimeState", args: argparse.Namespace) -> int:
    xi = betagui_py3.MeaChrom(state, measurement_entry_values(args))
    if xi is None:
        return 1
    result = state.last_result
    print("Measured xi:")
    print("  xi_x = %.6f" % xi[0])
    print("  xi_y = %.6f" % xi[1])
    print("  xi_s = %.6f" % xi[2])
    if result is not None:
        print("  alpha0 = %.8f" % result.alpha0)
    if args.output:
        output_path = Path(args.output)
        np.savetxt(output_path, np.asarray(xi, dtype=float))
        print("Saved xi to %s" % output_path)
    return 0
