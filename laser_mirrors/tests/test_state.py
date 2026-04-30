from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from laser_mirrors_app.config import GeometryConfig
from laser_mirrors_app.geometry import LaserMirrorGeometry
from laser_mirrors_app.models import MirrorAngles, UndulatorTarget
from laser_mirrors_app.state import load_state, save_state


class StateTests(unittest.TestCase):
    def test_load_missing_state_returns_zero_snapshot(self) -> None:
        snapshot = load_state(Path(tempfile.mkdtemp()) / "missing.ini")
        self.assertEqual(snapshot.last_known_x.offset_mm, 0.0)
        self.assertEqual(snapshot.last_set_y.angle_urad, 0.0)

    def test_save_then_load_round_trip(self) -> None:
        geometry = LaserMirrorGeometry(GeometryConfig())
        tmp = Path(tempfile.mkdtemp()) / "mirror_state.ini"
        save_state(
            tmp,
            geometry,
            current_angles_x=MirrorAngles(12.0, -21.0),
            current_angles_y=MirrorAngles(-5.0, 8.0),
            requested_x=UndulatorTarget(offset_mm=0.3, angle_urad=40.0),
            requested_y=UndulatorTarget(offset_mm=-0.5, angle_urad=-65.0),
        )
        snapshot = load_state(tmp)
        self.assertAlmostEqual(snapshot.last_set_x.offset_mm, 0.3, places=6)
        self.assertAlmostEqual(snapshot.last_set_y.angle_urad, -65.0, places=6)
        reconstructed_x = geometry.to_mirror_angles(snapshot.last_known_x, "x")
        reconstructed_y = geometry.to_mirror_angles(snapshot.last_known_y, "y")
        self.assertAlmostEqual(reconstructed_x.mirror1_urad, 12.0, places=6)
        self.assertAlmostEqual(reconstructed_x.mirror2_urad, -21.0, places=6)
        self.assertAlmostEqual(reconstructed_y.mirror1_urad, -5.0, places=6)
        self.assertAlmostEqual(reconstructed_y.mirror2_urad, 8.0, places=6)


if __name__ == "__main__":
    unittest.main()
