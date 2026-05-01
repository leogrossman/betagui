from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.gui import LaserMirrorApp


class GuiContractTests(unittest.TestCase):
    def test_refresh_plots_method_exists(self) -> None:
        self.assertTrue(hasattr(LaserMirrorApp, "_refresh_plots"))
        self.assertTrue(callable(getattr(LaserMirrorApp, "_refresh_plots")))


if __name__ == "__main__":
    unittest.main()
