from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import analyze_session, gui, log_now, sweep


COMMANDS = {
    "log-now": log_now.main,
    "analyze": analyze_session.main,
    "gui": gui.main,
    "rf-sweep": sweep.main,
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MLS SSMB tooling")
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS), help="Subcommand to run.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        build_arg_parser().print_help()
        return 0
    command = args[0]
    handler = COMMANDS.get(command)
    if handler is None:
        build_arg_parser().error("Unknown command %r." % command)
    return handler(args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
