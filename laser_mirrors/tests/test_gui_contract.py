from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.gui import LaserMirrorApp, apply_launch_mode, build_parser
from laser_mirrors_app.hardware import DisconnectedController


class GuiContractTests(unittest.TestCase):
    def test_parser_supports_demo_mode(self) -> None:
        args = build_parser().parse_args(["--demo-mode"])
        self.assertTrue(args.demo_mode)
        self.assertFalse(args.safe_mode)

    def test_refresh_plots_method_exists(self) -> None:
        self.assertTrue(hasattr(LaserMirrorApp, "_refresh_plots"))
        self.assertTrue(callable(getattr(LaserMirrorApp, "_refresh_plots")))

    def test_default_write_launch_clears_persisted_safe_mode(self) -> None:
        config = AppConfig()
        config.controller.safe_mode = True
        config.controller.write_mode = False
        apply_launch_mode(config, force_write_mode=True)
        self.assertFalse(config.controller.safe_mode)
        self.assertTrue(config.controller.write_mode)

    def test_safe_mode_wins_over_write_mode(self) -> None:
        config = AppConfig()
        apply_launch_mode(config, force_safe_mode=True, force_write_mode=True)
        self.assertTrue(config.controller.safe_mode)
        self.assertFalse(config.controller.write_mode)

    def test_overlap_preview_returns_cleanly_when_disconnected(self) -> None:
        class Status:
            value = ""

            def set(self, value):
                self.value = value

        app = object.__new__(LaserMirrorApp)
        app.controller = DisconnectedController(AppConfig().controller, "simulated EPICS failure")
        app.status_var = Status()
        app._log = lambda _message: None
        with patch("laser_mirrors_app.gui.messagebox.showerror") as showerror:
            result = app._preview_overlap_scan()
        self.assertIsNone(result)
        showerror.assert_called_once()
        self.assertEqual(app.status_var.value, "Motor backend disconnected.")


if __name__ == "__main__":
    unittest.main()
