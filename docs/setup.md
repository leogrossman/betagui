# Setup

This page is for a fresh checkout on a development machine.

## Requirements

- Ubuntu or similar Linux environment
- Python 3.9
- `pyenv`
- Tk support for Python if the GUI will be used
- EPICS CLI tools for live or twin work:
  `cainfo`, `caget`, `camonitor`, `caput`

## pyenv

Install Python 3.9 if needed:

```bash
pyenv install 3.9.0
```

Create the project environment:

```bash
pyenv virtualenv 3.9.0 betagui
```

From the repo root:

```bash
pyenv local betagui
```

This repo already includes [.python-version](../.python-version).

## Python Packages

```bash
python3 -m pip install --upgrade pip
python3 -m pip install numpy matplotlib pyepics
```

`tkinter` must also be available for the GUI launchers.

The standalone control-room files do not need other repo Python files at
runtime, but they still require this Python environment.

## Verify

```bash
python3 --version
python3 -m py_compile control_room/betagui.py control_room/betagui_cli.py development/betagui.py
python3 -m unittest tests.smoke_test_import tests.test_control_room_entrypoints tests.test_measure_cli tests.test_output_regression tests.test_mock_measurement tests.test_matrix_io
```

## First Runs

Development:

```bash
python3 development/betagui.py
```

Control-room preflight:

```bash
python3 control_room/betagui.py --safe
python3 control_room/betagui_cli.py --safe
```

## Digital Twin

The bundled container image is at:

```text
support/digital_twin/pyat-as-twin-softioc.sif
```

Start it with:

```bash
apptainer run support/digital_twin/pyat-as-twin-softioc.sif
```

Then use:

```bash
python3 scripts/run_digital_twin_demo.py
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```
