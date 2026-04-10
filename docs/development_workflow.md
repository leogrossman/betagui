# Development Workflow

This document separates day-to-day development from the clean control-room use
case.

## Two Entry Points

### Control-Room Entry Point

Use:

- [betagui.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui.py)
- [betagui_safe.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui_safe.py)
- [betagui_cli.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui_cli.py)
- [betagui_cli_safe.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui_cli_safe.py)

Purpose:

- legacy PV profile only
- live EPICS only
- minimal command-line surface
- clean handoff file for operators and testers
- CLI fallback if the GUI fails or a display session is unavailable

Run:

```bash
python3 control_room/betagui_safe.py
python3 control_room/betagui.py
python3 control_room/betagui_cli_safe.py
python3 control_room/betagui_cli.py
```

### Development Entry Point

Use:

- [betagui.py](https://github.com/leogrossman/betagui/blob/main/development/betagui.py)

Purpose:

- mock mode
- digital twin mode
- profile switching
- general development and debugging

Run:

```bash
python3 development/betagui.py
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

## Recommended Developer Loop

1. read the legacy notes and parity docs
2. run mock tests locally
3. run the mock GUI
4. run the digital twin if the change touches EPICS-facing behavior
5. only then try the control-room launcher in read-only live mode

## Test Commands

```bash
python3 -m unittest tests.test_matrix_io tests.test_mock_measurement tests.test_output_regression tests.test_measure_cli tests.smoke_test_import
python3 scripts/run_mock.py --headless
python3 scripts/quick_diag.py
python3 scripts/run_digital_twin_demo.py
```

## Digital Twin Workflow

Start the twin:

```bash
apptainer run support/digital_twin/pyat-as-twin-softioc.sif
```

Then in another terminal:

```bash
python3 scripts/run_digital_twin_demo.py
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

Use `--allow-writes` only when intentionally exercising write paths against the
twin.

## GitLab-Friendly Documentation Layout

This `docs/` directory is already organized so it can be used directly in GitLab
repository browsing. If you want a more wiki-like landing page, use [index.md](index.md)
as the root document and link to the other pages from there.
