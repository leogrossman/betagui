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
            root / "control_room" / "betagui_safe.py",
            root / "control_room" / "betagui_cli.py",
            root / "control_room" / "betagui_cli_safe.py",
            root / "development" / "betagui.py",
        ]
        for index, path in enumerate(files):
            module = load_module(path, "entrypoint_%d" % index)
            self.assertTrue(hasattr(module, "__file__"))
