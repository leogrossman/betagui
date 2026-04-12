# Setup

This page is for a fresh checkout on a development machine.

## Requirements

- Ubuntu or similar Linux environment
- Python 3.9
- `pyenv`
- Tk support for Python if the GUI will be used
- EPICS CLI tools for live or twin work:
  `cainfo`, `caget`, `camonitor`, `caput`

For the current development environment in this repo:

- pyenv env name: `betagui`
- Python version: `3.9.0`
- package pins are in [requirements-dev.txt](../requirements-dev.txt)

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

## macOS Notes

If you want the GUI on macOS, make sure the pyenv build has Tk support.

Typical Homebrew prerequisites:

```bash
brew install pyenv pyenv-virtualenv tcl-tk
```

Then build Python 3.9.0 with the Homebrew Tcl/Tk available in your shell
environment before creating the `betagui` virtualenv.

## Python Packages

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-dev.txt
```

`tkinter` must also be available for the GUI launchers.

The standalone control-room files do not need other repo Python files at
runtime, but they still require this Python environment.

## Verify

```bash
python3 --version
pyenv version-name
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
python3 control_room/machine_check.py snapshot
python3 control_room/tools/collect_epics_inventory.py
python3 control_room/tools/step_test.py baseline
python3 control_room/betagui.py --safe
python3 control_room/betagui_cli.py --safe
```

If you want to bring control-room outputs back by git push later, keep the run
artifacts under `control_room_outputs/`. The transient runtime logs under
`.betagui_local/logs/` remain local by default.

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
