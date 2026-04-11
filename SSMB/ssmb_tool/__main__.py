from __future__ import annotations

import argparse
from typing import Optional, Sequence

from . import analyze_session, log_now


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MLS SSMB tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("log-now", help="Run the Stage 0 passive logger.")
    sub.add_parser("analyze", help="Analyze a saved Stage 0 session.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args, remaining = parser.parse_known_args(argv)
    if args.command == "log-now":
        return log_now.main(remaining)
    if args.command == "analyze":
        return analyze_session.main(remaining)
    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
