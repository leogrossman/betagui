#!/usr/bin/env python3
"""Compare matrix files or simple numeric text outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def load_array(path: Path) -> np.ndarray:
    return np.loadtxt(path)


def compare_arrays(left: np.ndarray, right: np.ndarray):
    diff = right - left
    return {
        "left_shape": left.shape,
        "right_shape": right.shape,
        "max_abs_diff": float(np.max(np.abs(diff))) if left.shape == right.shape else None,
        "mean_abs_diff": float(np.mean(np.abs(diff))) if left.shape == right.shape else None,
        "diff": diff if left.shape == right.shape else None,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", help="Left-hand matrix/text file.")
    parser.add_argument("right", help="Right-hand matrix/text file.")
    parser.add_argument(
        "--assert-max-abs",
        type=float,
        help="Exit with failure if the max absolute difference is larger than this threshold.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    left_path = Path(args.left)
    right_path = Path(args.right)
    left = load_array(left_path)
    right = load_array(right_path)
    summary = compare_arrays(left, right)
    print("Left shape:", summary["left_shape"])
    print("Right shape:", summary["right_shape"])
    if summary["max_abs_diff"] is None:
        print("Shapes differ; numeric diff skipped.")
        return 1
    print("Max abs diff:", summary["max_abs_diff"])
    print("Mean abs diff:", summary["mean_abs_diff"])
    if args.assert_max_abs is not None and summary["max_abs_diff"] > args.assert_max_abs:
        print("Comparison failed: max abs diff exceeds threshold.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
