#!/usr/bin/env python3
"""Launcher for the standalone laser mirror scan tool."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSMB laser mirror scan tool")
    parser.add_argument("--safe-mode", action="store_true", help="Use real EPICS readback/signal, but keep motor writes disabled")
    parser.add_argument("--demo-mode", action="store_true", help="Run fully offline with simulated motors and simulated signal")
    parser.add_argument("--write-mode", action="store_true", help="Enable real motor writes")
    parser.add_argument("--config", default="laser_mirrors_config.json", help="Path to JSON config file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from laser_mirrors_app.gui import main as gui_main

    forwarded = []
    if args.safe_mode:
        forwarded.append("--safe-mode")
    if args.demo_mode:
        forwarded.append("--demo-mode")
    if args.write_mode:
        forwarded.append("--write-mode")
    forwarded.extend(["--config", args.config])
    return gui_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
