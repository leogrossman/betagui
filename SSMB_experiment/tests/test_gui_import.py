import unittest


class SSMBExperimentGuiImportTest(unittest.TestCase):
    def test_gui_module_imports(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        self.assertTrue(hasattr(gui, "main"))

    def test_gui_parser_defaults_to_write_capable_start(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        parser = gui.build_arg_parser()
        args = parser.parse_args([])
        self.assertFalse(args.unsafe_start)

    def test_gui_parser_accepts_safe_mode_flag(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        parser = gui.build_arg_parser()
        args = parser.parse_args(["--safe-mode"])
        self.assertTrue(args.safe_mode)

    def test_gui_parser_accepts_unsafe_start_flag(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        parser = gui.build_arg_parser()
        args = parser.parse_args(["--unsafe-start"])
        self.assertTrue(args.unsafe_start)


if __name__ == "__main__":
    unittest.main()
