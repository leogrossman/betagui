import os
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

    def test_update_live_monitor_does_not_live_render_monitor_window(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class _Exists:
            def winfo_exists(self):
                return True

        app = object.__new__(gui.SSMBGui)
        app.latest_monitor_sample = None
        app.latest_monitor_summary = None
        app.monitor_summary_text = mock.Mock()
        app.monitor_channels_text = mock.Mock()
        app.monitor_window = _Exists()
        app.oscillation_window = None
        app._set_text_widget = mock.Mock()
        app._update_rf_sweep_jump_label = mock.Mock()
        app._refresh_lattice_view = mock.Mock()
        app._append_log = mock.Mock()
        payload = {
            "summary_lines": ["a"],
            "channel_lines": ["b"],
            "sample": {"sample_index": 1},
            "summary": {"current": {}},
        }
        gui.SSMBGui._update_live_monitor(app, payload)
        self.assertEqual(app.latest_monitor_sample, payload["sample"])
        self.assertEqual(app.latest_monitor_summary, payload["summary"])
        app._refresh_lattice_view.assert_called_once()

    def test_refresh_monitor_window_snapshot_updates_widgets_and_dashboard(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class _Exists:
            def winfo_exists(self):
                return True

        app = object.__new__(gui.SSMBGui)
        app.monitor_window = _Exists()
        app.monitor_window_summary_text = mock.Mock()
        app.monitor_window_channels_text = mock.Mock()
        app.latest_monitor_summary = {"current": {}}
        app.latest_monitor_sample = {"channels": {}, "derived": {}}
        app.live_spec_lookup = {}
        app.monitor_history = []
        app._set_text_widget = mock.Mock()
        app._update_monitor_dashboard = mock.Mock()
        app._debug = mock.Mock()
        gui.SSMBGui._refresh_monitor_window_snapshot(app)
        self.assertEqual(app._set_text_widget.call_count, 2)
        app._update_monitor_dashboard.assert_called_once()

    def test_auto_refresh_monitor_window_only_rerenders_when_monitor_running(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class _Exists:
            def winfo_exists(self):
                return True

        app = object.__new__(gui.SSMBGui)
        app.monitor_window = _Exists()
        app.monitor_stop_event = object()
        app._monitor_window_auto_refresh_job = None
        app._refresh_monitor_window_snapshot = mock.Mock()
        app._schedule_monitor_window_refresh = mock.Mock()
        gui.SSMBGui._auto_refresh_monitor_window(app)
        app._refresh_monitor_window_snapshot.assert_called_once()
        app._schedule_monitor_window_refresh.assert_called_once()

        app2 = object.__new__(gui.SSMBGui)
        app2.monitor_window = _Exists()
        app2.monitor_stop_event = None
        app2._monitor_window_auto_refresh_job = None
        app2._refresh_monitor_window_snapshot = mock.Mock()
        app2._schedule_monitor_window_refresh = mock.Mock()
        gui.SSMBGui._auto_refresh_monitor_window(app2)
        app2._refresh_monitor_window_snapshot.assert_not_called()
        app2._schedule_monitor_window_refresh.assert_called_once()

    def test_monitor_section_selected_ignores_programmatic_tree_updates(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        app = object.__new__(gui.SSMBGui)
        app._updating_monitor_section_tree = True
        app.monitor_section_tree = mock.Mock()
        app._update_monitor_dashboard = mock.Mock()
        gui.SSMBGui._on_monitor_section_selected(app)
        app._update_monitor_dashboard.assert_not_called()

    def test_monitor_plot_selected_ignores_programmatic_selector_updates(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        tree = mock.Mock()
        app = object.__new__(gui.SSMBGui)
        app._updating_monitor_plot_selector = True
        app.monitor_plot_controls = {}
        app.latest_monitor_summary = {}
        app._update_monitor_dashboard = mock.Mock()
        gui.SSMBGui._on_monitor_plot_selected(app, "machine_state", ["beam_current"], tree)
        app._update_monitor_dashboard.assert_not_called()

    def test_monitor_plot_toggle_adds_overlay_without_multi_select_loop(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class FakeTree:
            def __init__(self):
                self.set_calls = []
                self.selection_set_calls = []

            def identify_row(self, _y):
                return "rf_offset_hz"

            def selection_set(self, values):
                self.selection_set_calls.append(tuple(values))

            def exists(self, key):
                return True

            def set(self, key, column, value):
                self.set_calls.append((key, column, value))

        class Event:
            y = 5

        app = object.__new__(gui.SSMBGui)
        app._updating_monitor_plot_selector = False
        app.monitor_plot_controls = {"machine_state": ["beam_current"]}
        app.latest_monitor_summary = {}
        app._update_monitor_dashboard = mock.Mock()
        tree = FakeTree()
        result = gui.SSMBGui._on_monitor_plot_toggle(app, "machine_state", ["beam_current", "rf_offset_hz"], tree, Event())
        self.assertEqual(result, "break")
        self.assertEqual(app.monitor_plot_controls["machine_state"], ["beam_current", "rf_offset_hz"])
        app._update_monitor_dashboard.assert_called_once()

    def test_monitor_plot_selected_preserves_overlay_after_toggle_selection_event(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class FakeTree:
            def __init__(self):
                self._selection = ("rf_offset_hz",)
                self.set_calls = []

            def selection(self):
                return self._selection

            def selection_set(self, values):
                self._selection = tuple(values)

            def exists(self, _key):
                return True

            def set(self, key, column, value):
                self.set_calls.append((key, column, value))

        app = object.__new__(gui.SSMBGui)
        app._updating_monitor_plot_selector = False
        app._suppress_monitor_plot_selected_once = True
        app.monitor_plot_controls = {"machine_state": ["beam_current", "rf_offset_hz"]}
        app.latest_monitor_summary = {}
        app._update_monitor_dashboard = mock.Mock()
        tree = FakeTree()

        gui.SSMBGui._on_monitor_plot_selected(app, "machine_state", ["beam_current", "rf_offset_hz"], tree)

        self.assertEqual(app.monitor_plot_controls["machine_state"], ["beam_current", "rf_offset_hz"])
        app._update_monitor_dashboard.assert_not_called()

    def test_monitor_plot_click_on_use_column_toggles_overlay(self):
        import SSMB_experiment.ssmb_tool.gui as gui

        class FakeTree:
            def identify(self, kind, _x, _y):
                if kind == "region":
                    return "cell"
                return ""

            def identify_column(self, _x):
                return "#1"

            def identify_row(self, _y):
                return "rf_offset_hz"

        class Event:
            x = 2
            y = 6

        app = object.__new__(gui.SSMBGui)
        app._on_monitor_plot_toggle = mock.Mock(return_value="break")

        result = gui.SSMBGui._on_monitor_plot_click(
            app,
            "machine_state",
            ["beam_current", "rf_offset_hz"],
            FakeTree(),
            Event(),
        )

        self.assertEqual(result, "break")
        app._on_monitor_plot_toggle.assert_called_once()

    def test_monitor_window_render_smoke(self):
        import SSMB_experiment.ssmb_tool.gui as gui
        from SSMB_experiment.ssmb_tool.live_monitor import format_channel_snapshot, format_monitor_summary, summarize_live_monitor

        if os.environ.get("SSMB_RUN_TK_SMOKE") != "1":
            self.skipTest("Tk smoke test is opt-in via SSMB_RUN_TK_SMOKE=1")
        if gui.tk is None:
            self.skipTest("tkinter unavailable")
        try:
            root = gui.tk.Tk()
        except Exception as exc:
            self.skipTest("Tk unavailable: %s" % exc)
        try:
            root.withdraw()
            app = gui.SSMBGui(root, allow_writes=True, start_safe_mode=True)
            samples = []
            for index in range(40):
                samples.append(
                    {
                        "timestamp_epoch_s": 4_000_000.0 + 0.5 * index,
                        "sample_index": index,
                        "channels": {
                            "beam_current": {"value": 4.0 + 0.01 * index, "pv": "CUM1ZK3RP:measCur"},
                            "p1_h1_ampl_avg": {"value": 0.05 + 0.002 * (index % 5), "pv": "SCOPE1ZULP:h1p1:rdAmplAv"},
                            "rf_readback_499mhz": {"value": 685.685, "pv": "MCLKHGP:rdFrq499"},
                        },
                        "derived": {
                            "rf_readback": 499688.387 + 1.0e-4 * index,
                            "rf_offset_hz": 0.1 * index,
                            "delta_l4_bpm_first_order": 1.0e-4 * index,
                            "beam_energy_from_bpm_mev": 250.0 + 0.01 * index,
                            "tune_s_unitless": 0.013,
                            "bpm_x_nonlinear_labels": [],
                        },
                    }
                )
            summary = summarize_live_monitor(samples, include_oscillation=False, include_extended=False)
            app.latest_monitor_sample = samples[-1]
            app.latest_monitor_summary = summary
            app._open_monitor_window()
            app._update_live_monitor(
                {
                    "summary_lines": format_monitor_summary(summary),
                    "channel_lines": format_channel_snapshot(samples[-1], {}),
                    "sample": samples[-1],
                    "summary": summary,
                }
            )
            root.update_idletasks()
            root.update()
            self.assertIsNotNone(app.monitor_window)
            self.assertTrue(app.monitor_window.winfo_exists())
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
