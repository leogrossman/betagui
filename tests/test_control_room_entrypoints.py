import importlib.util
import unittest
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ControlRoomEntrypointsTest(unittest.TestCase):
    def test_control_room_files_import(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "control_room" / "betagui.py",
            root / "control_room" / "betagui_cli.py",
            root / "development" / "betagui.py",
        ]
        for index, path in enumerate(files):
            module = load_module(path, "entrypoint_%d" % index)
            self.assertTrue(hasattr(module, "__file__"))

    def test_control_room_files_are_bundled(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "control_room" / "betagui.py",
            root / "control_room" / "betagui_cli.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("build_control_room_standalone", text, msg=str(path))
            self.assertNotIn("sys.path.insert", text, msg=str(path))
            self.assertNotIn("from src.", text, msg=str(path))
            self.assertNotIn("_BUNDLED_MODULES", text, msg=str(path))
            self.assertEqual(text.count('if __name__ == "__main__":'), 1, msg=str(path))
        gui_text = (root / "control_room" / "betagui.py").read_text(encoding="utf-8")
        self.assertIn("EMBEDDED_DEFAULT_MATRIX_3D", gui_text)
        self.assertNotIn("twin-mls", gui_text)
        self.assertNotIn("MockEpicsAdapter", gui_text)
