#!/usr/bin/env python3
"""Launcher for the standalone laser mirror scan tool."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SSMB laser mirror scan tool")
    parser.add_argument("--safe-mode", action="store_true", help="Run with simulated motors and simulated P1")
    parser.add_argument("--config", default="laser_mirrors_config.json", help="Path to JSON config file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    import tkinter as tk
    from laser_mirrors_app.gui import LaserMirrorApp

    root = tk.Tk()
    LaserMirrorApp(root, Path(args.config), force_safe_mode=args.safe_mode)
    root.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
