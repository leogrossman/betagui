import sys
import importlib.util
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SmokeImportTest(unittest.TestCase):
    def test_import_and_mock_runtime(self):
        import betagui_py3

        state = betagui_py3.create_runtime()
        self.assertTrue(state.is_mock)
        self.assertEqual(state.B.shape, (3, 3))

    def test_import_control_room_entrypoint(self):
        root = Path(__file__).resolve().parents[1]
        module = load_module(root / "control_room" / "betagui.py", "betagui_entry")
        self.assertTrue(hasattr(module, "build_arg_parser"))


if __name__ == "__main__":
    unittest.main()
