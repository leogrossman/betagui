from __future__ import annotations

import os
from pathlib import Path


def _ensure_local_mplconfig() -> None:
    if os.environ.get("MPLCONFIGDIR"):
        return
    root = Path(__file__).resolve().parent
    mpl_dir = root / ".ssmb_local" / "mplconfig"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(mpl_dir)


_ensure_local_mplconfig()

from ssmb_tool import gui


if __name__ == "__main__":
    raise SystemExit(gui.main())
