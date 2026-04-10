# Development Quick Start

This page is for maintenance, offline work, and digital-twin testing.

## Main Files

- [betagui.py](development/betagui.py)
  development launcher with mock and twin support
- [testing_workflow.md](docs/testing_workflow.md)
- [porting_notes.md](docs/porting_notes.md)
- [feature_parity.md](docs/feature_parity.md)

## Common Commands

Run the mock GUI:

```bash
python3 development/betagui.py
```

Run the mock headless measurement:

```bash
python3 scripts/run_mock.py --headless
```

Run the tests:

```bash
python3 -m unittest tests.test_matrix_io tests.test_mock_measurement tests.test_output_regression tests.test_measure_cli tests.smoke_test_import
```

Run the digital twin helper:

```bash
python3 scripts/run_digital_twin_demo.py
```

Environment setup:

- [docs/setup.md](docs/setup.md)
