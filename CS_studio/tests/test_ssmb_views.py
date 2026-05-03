import tempfile
import unittest
from pathlib import Path

from CS_studio.phoebusgen.ssmb_views import load_export_stats, render_package


class ExportStatsTests(unittest.TestCase):
    def test_load_export_stats_parses_value_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '00.txt'
            path.write_text(
                '# Time\tBPMZ3L2RP:rdX Value\tQ1P1L2RP:setCur Value\n'
                '2026-01-01 00:00:00.000\t-0.07\t21.4\n'
                '2026-01-01 00:00:01.000\t-0.06\t21.5\n'
            )
            stats = load_export_stats(Path(tmp))
            self.assertEqual(len(stats.values['BPMZ3L2RP:rdX']), 2)
            self.assertAlmostEqual(stats.median('Q1P1L2RP:setCur'), 21.45)

    def test_render_package_writes_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            export_dir = base / 'exports'
            export_dir.mkdir()
            export_dir.joinpath('00.txt').write_text(
                '# Time\tBPMZ3L2RP:rdX Value\tBPMZ4L2RP:rdX Value\tBPMZ5L2RP:rdX Value\tBPMZ6L2RP:rdX Value\t'
                'BPMZ3L2RP:rdY Value\tBPMZ4L2RP:rdY Value\tBPMZ5L2RP:rdY Value\tBPMZ6L2RP:rdY Value\t'
                'HS1P2K3RP:setCur Value\tHS3P1L4RP:setCur Value\tHS3P2L4RP:setCur Value\tHS1P1K1RP:setCur Value\t'
                'SCOPE1ZULP:h1p1:rdAmplAv Value\tQPD01ZL2RP:rdSigmaXav Value\tQPD01ZL2RP:rdSigmaYav Value\t'
                'QPD00ZL4RP:rdSigmaXav Value\tQPD00ZL4RP:rdSigmaYav Value\tQ1P1L2RP:setCur Value\t'
                'MCLKHGP:rdFrq499 Value\tPAHRP:NRVD:rdVoltCav Value\tTUNEZRP:measX Value\tTUNEZRP:measY Value\tTUNEZRP:measZ Value\t'
                'SCOPE1ZULP:rdAvLength Value\tWFGEN2C1CP:setVolt Value\tWFGEN2C1CP:stOut Value\tERMPCGP:rdRmp Value\tCUM1ZK3RP:rdCur Value\n'
                '2026-01-01 00:00:00.000\t-0.07\t-0.19\t-0.76\t-0.16\t-0.14\t-0.17\t-0.05\t-0.03\t0.06\t0.23\t-0.09\t-0.016\t0.005\t380\t117\t535\t115\t21.4\t687.462\t1.0\t1000\t1500\t40\t500\t2.0\t1.0\t250\t0.6\n'
            )
            out = base / 'out'
            render_package(export_dir, out)
            self.assertTrue((out / '01_core_operator_overview_10min.plt').exists())
            self.assertTrue((out / 'README.md').exists())
            self.assertIn('Q1P1L2RP:setCur', (out / '03_bumper_alpha0_machine_30min.plt').read_text())
            self.assertIn('AKC12VP', (out / '03_bumper_alpha0_machine_30min.plt').read_text())
            self.assertIn('WFGEN2C1CP:setVolt', (out / '04_signal_qpd_rf_laser_30min.plt').read_text())


if __name__ == '__main__':
    unittest.main()
