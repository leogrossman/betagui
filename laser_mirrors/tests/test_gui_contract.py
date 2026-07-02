from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import AppConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.gui import LaserMirrorApp, apply_launch_mode, build_parser
from laser_mirrors_app.hardware import DisconnectedController


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


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

    def test_overlap_span_sync_does_not_change_slope(self) -> None:
        app = object.__new__(LaserMirrorApp)
        app.geometry = LaserMirrorGeometry(AppConfig().geometry)
        app._syncing_overlap_spans = False
        app.overlap_axis_var = FakeVar("vertical")
        app.overlap_slope_var = FakeVar(-1.234)
        app.overlap_m1_span_steps_var = FakeVar(420.2)
        app.overlap_m1_span_urad_var = FakeVar(0.0)
        app.overlap_m2_span_steps_var = FakeVar(300.0)
        app.overlap_m2_span_urad_var = FakeVar(0.0)
        app._on_live_setting_changed = lambda: None

        app._sync_overlap_span_units("m1", "steps")

        self.assertEqual(app.overlap_m1_span_steps_var.get(), 420.0)
        self.assertAlmostEqual(app.overlap_m1_span_urad_var.get(), 793.8)
        self.assertEqual(app.overlap_slope_var.get(), -1.234)


if __name__ == "__main__":
    unittest.main()
