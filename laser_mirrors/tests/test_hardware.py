from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import ControllerConfig
from laser_mirrors_app.hardware import (
    DisconnectedController,
    MirrorController,
    PVFactory,
    SignalBackend,
    VisualOnlySignalBackend,
    build_passive_signal_backends,
    build_signal_backend,
)


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

    def test_default_limits_allow_coarse_2000_step_moves(self) -> None:
        config = ControllerConfig(safe_mode=True)
        controller = MirrorController(config, PVFactory(True))
        controller.reference_steps = {"m1_horizontal": 0.0, "m1_vertical": 0.0, "m2_horizontal": 0.0, "m2_vertical": 0.0}
        targets = {"m1_horizontal": 0.0, "m1_vertical": 0.0, "m2_horizontal": 2000.0, "m2_vertical": -2000.0}
        ok, errors = controller.validate_targets(targets)
        self.assertTrue(ok, errors)

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

    def test_visual_only_signal_backend_does_not_require_pv(self) -> None:
        backend = build_signal_backend(False, "visual_only", None, PVFactory(True))
        self.assertIsInstance(backend, VisualOnlySignalBackend)
        reading = backend.read()
        self.assertTrue(reading.ok)
        self.assertEqual(reading.pv, "none")

    def test_passive_backends_exclude_visual_only_empty_pv(self) -> None:
        backends = build_passive_signal_backends(PVFactory(True))
        self.assertNotIn("visual_only", backends)
        self.assertTrue(backends)
        self.assertTrue(all(backend.pv_name for backend in backends.values()))

    def test_real_epics_factory_never_receives_empty_passive_pv_name(self) -> None:
        created_names = []

        class StrictPV:
            def __init__(self, name, connection_timeout=1.0):
                if not name:
                    raise ValueError("empty EPICS PV name")
                created_names.append(name)

        fake_epics = types.SimpleNamespace(PV=StrictPV)
        with patch.dict(sys.modules, {"epics": fake_epics}):
            factory = PVFactory(False)
            backends = build_passive_signal_backends(factory)

        self.assertNotIn("", created_names)
        self.assertNotIn("none", created_names)
        self.assertEqual(len(backends), len(created_names))
        self.assertNotIn("visual_only", backends)

    def test_real_epics_connection_bundle_sees_all_four_motors(self) -> None:
        class FakePV:
            def __init__(self, name, connection_timeout=1.0):
                if not name or name == "none":
                    raise ValueError(f"invalid EPICS PV name: {name!r}")
                self.name = name

            def get(self, timeout=None):
                if self.name.endswith(".DMOV"):
                    return 1
                if self.name.endswith(".DESC"):
                    return self.name.split(".", 1)[0]
                if self.name.endswith(".EGU"):
                    return "steps"
                if self.name.endswith(".STAT") or self.name.endswith(".SEVR"):
                    return "NO_ALARM"
                if self.name.endswith(".RTYP"):
                    return "motor"
                return 0.0

            def put(self, value, wait=False, timeout=None):
                return True

        fake_epics = types.SimpleNamespace(PV=FakePV)
        with patch.dict(sys.modules, {"epics": fake_epics}):
            factory = PVFactory(False)
            controller = MirrorController(ControllerConfig(write_mode=False), factory)
            signal = build_signal_backend(False, "visual_only", "none", factory)
            passive = build_passive_signal_backends(factory)

        self.assertEqual(
            set(controller.current_steps()),
            {"m1_horizontal", "m1_vertical", "m2_horizontal", "m2_vertical"},
        )
        self.assertIsInstance(signal, VisualOnlySignalBackend)
        self.assertNotIn("visual_only", passive)

    def test_disconnected_controller_preview_fails_cleanly(self) -> None:
        controller = DisconnectedController(ControllerConfig(), "test connection failure")
        with self.assertRaisesRegex(RuntimeError, "EPICS motor backend unavailable"):
            controller.plan_absolute_move({}, {})

    def test_completion_tolerance_has_margin(self) -> None:
        factory = PVFactory(True)
        config = ControllerConfig(safe_mode=True, max_step_per_put=8.0)
        controller = MirrorController(config, factory)
        self.assertAlmostEqual(controller.completion_tolerance_steps(), 10.0)


if __name__ == "__main__":
    unittest.main()
