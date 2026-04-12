import unittest
from unittest import mock


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

    def test_live_monitor_filter_stays_lean_by_default(self):
        import SSMB_experiment.ssmb_tool.gui as gui
        from SSMB_experiment.ssmb_tool.config import LoggerConfig
        from SSMB_experiment.ssmb_tool.log_now import build_specs

        cfg = LoggerConfig(
            duration_seconds=60.0,
            sample_hz=1.0,
            include_bpm_buffer=True,
            include_candidate_bpm_scalars=True,
            include_ring_bpm_scalars=True,
            include_quadrupoles=True,
            include_sextupoles=True,
            include_octupoles=True,
        )
        _lattice, specs = build_specs(cfg)
        filtered = gui._filter_live_monitor_specs(specs, [])
        labels = {spec.label for spec in filtered}
        self.assertNotIn("bpm_buffer_raw", labels)
        self.assertNotIn("bpmz1k1rp_x", labels)
        self.assertIn("p1_h1_ampl_avg", labels)
        self.assertIn("climate_kw13_return_temp_c", labels)
        self.assertIn("qpd_l4_sigma_x", labels)

    def test_downsample_tail_keeps_last_point(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        values = list(range(1000))
        sampled = gui._downsample_tail(values, 100)
        self.assertLessEqual(len(sampled), 101)
        self.assertEqual(sampled[-1], values[-1])
        self.assertEqual(sampled[0], values[0])

    def test_monitor_history_path_uses_tempdir_by_default(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        app = object.__new__(gui.SSMBGui)
        with mock.patch.dict(gui.os.environ, {}, clear=False):
            path = gui.SSMBGui._monitor_history_path(app)
        self.assertIn("ssmb_experiment_live_monitor", str(path))
        self.assertNotIn("/tmp/betagui/SSMB_experiment/.ssmb_local", str(path))

    def test_open_monitor_window_can_handle_no_live_sample(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        self.assertTrue(hasattr(gui.SSMBGui, "_open_monitor_window"))


if __name__ == "__main__":
    unittest.main()
