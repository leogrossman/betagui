from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_local_mplconfig() -> None:
    if os.environ.get("MPLCONFIGDIR"):
        return
    root = Path(__file__).resolve().parent
    mpl_dir = root / ".ssmb_local" / "mplconfig"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(mpl_dir)


_ensure_local_mplconfig()

print("[ssmb_experiment] MPLCONFIGDIR=%s" % os.environ.get("MPLCONFIGDIR", ""), flush=True)
print("[ssmb_experiment] importing ssmb_tool.gui", flush=True)

from ssmb_tool import gui


if __name__ == "__main__":
    print("[ssmb_experiment] entering gui.main()", flush=True)
    raise SystemExit(gui.main())
