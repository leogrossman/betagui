from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import ControllerConfig
from laser_mirrors_app.hardware import MirrorController, PVFactory, SignalBackend, build_signal_backend


class HardwareTests(unittest.TestCase):
    def test_plan_absolute_move_splits_large_ramp(self) -> None:
        config = ControllerConfig(safe_mode=True, max_step_per_put=5.0)
        controller = MirrorController(config, PVFactory(True))
        controller.reference_steps = {"m1_horizontal": 0.0, "m1_vertical": 0.0, "m2_horizontal": 0.0, "m2_vertical": 0.0}
        plan = controller.plan_absolute_move(controller.current_steps(), {"m1_horizontal": 12.0, "m1_vertical": 0.0, "m2_horizontal": 0.0, "m2_vertical": 0.0})
        self.assertGreater(len(plan["m1_horizontal"]), 1)

    def test_validate_targets_blocks_large_delta(self) -> None:
        config = ControllerConfig(safe_mode=True, max_delta_from_reference=10.0)
        controller = MirrorController(config, PVFactory(True))
        controller.reference_steps = {"m1_horizontal": 0.0, "m1_vertical": 0.0, "m2_horizontal": 0.0, "m2_vertical": 0.0}
        ok, errors = controller.validate_targets({"m1_horizontal": 25.0, "m1_vertical": 0.0, "m2_horizontal": 0.0, "m2_vertical": 0.0})
        self.assertFalse(ok)
        self.assertTrue(errors)

    def test_move_absolute_group_updates_safe_mode_rbv(self) -> None:
        config = ControllerConfig(safe_mode=True, max_step_per_put=100.0, inter_put_delay_s=0.0, settle_s=0.0, max_delta_from_reference=500.0)
        controller = MirrorController(config, PVFactory(True))
        targets = {"m1_horizontal": 7.0, "m1_vertical": -4.0, "m2_horizontal": 3.0, "m2_vertical": 2.0}
        moved = controller.move_absolute_group(targets, request_stop=lambda: False, command_path=Path(tempfile.mkdtemp()) / "last.json")
        self.assertTrue(moved)
        current = controller.current_steps()
        self.assertEqual(current["m1_horizontal"], 7.0)
        self.assertEqual(current["m1_vertical"], -4.0)

    def test_build_signal_backend_does_not_simulate_main_gui_signal(self) -> None:
        backend = build_signal_backend(False, "p1_h1_avg", None, PVFactory(True))
        self.assertIsInstance(backend, SignalBackend)

    def test_completion_tolerance_has_margin(self) -> None:
        factory = PVFactory(True)
        config = ControllerConfig(safe_mode=True, max_step_per_put=8.0)
        controller = MirrorController(config, factory)
        self.assertAlmostEqual(controller.completion_tolerance_steps(), 10.0)


if __name__ == "__main__":
    unittest.main()
