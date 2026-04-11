import unittest


class SSMBGuiImportTest(unittest.TestCase):
    def test_gui_module_imports(self):
        import SSMB.ssmb_tool.gui as gui

        self.assertTrue(hasattr(gui, "main"))


if __name__ == "__main__":
    unittest.main()
