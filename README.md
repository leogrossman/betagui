# betagui

Python 3.9 port of a legacy MLS control-room chromaticity tool.

## Control Room

Use the standalone files in [control_room/](control_room):

- [control_room/betagui.py](control_room/betagui.py): main GUI
- [control_room/betagui_cli.py](control_room/betagui_cli.py): minimal CLI fallback

The GUI file embeds the default legacy response matrices, so it can be copied
on its own into the control room. It still needs the normal runtime Python
packages installed.

Recommended first run:

```bash
python3 control_room/betagui.py --safe
python3 control_room/betagui_cli.py --safe
python3 control_room/betagui.py
```

`--safe` means live EPICS reads are allowed but machine writes are suppressed.
Without `--safe`, both files behave like the legacy script and are write-capable
by default.

Before first machine use, read:

- [CONTROL_ROOM.md](CONTROL_ROOM.md)
- [docs/control_room_test_plan.md](docs/control_room_test_plan.md)
- [docs/runtime_checklist.md](docs/runtime_checklist.md)
- [docs/write_paths.md](docs/write_paths.md)

## What It Does

- measures chromaticity by RF sweep and tune readback
- measures sextupole response matrices
- applies manual chromaticity corrections
- resets saved machine settings
- includes the legacy secondary sextupole scan workflow

The untouched Python 2 original is kept in [original/](original).

## Feature Parity

| Feature | Legacy tool | Python 3 control-room files |
| --- | --- | --- |
| RF-sweep chromaticity measurement | Yes | Yes |
| Dynamic `alpha0` | Yes | Yes |
| Response-matrix measurement | Yes | Yes |
| Matrix load/save | Yes | Yes |
| Manual sextupole correction | Yes | Yes |
| Reset to saved state | Yes | Yes |
| Secondary sextupole scan window | Yes | Yes |
| Standalone single-file control-room launchers | No | Yes |
| Read-only preflight mode via `--safe` | No | Yes |
| Barebones CLI fallback | No | Yes |

More detail: [docs/feature_parity.md](docs/feature_parity.md)

## Development And Digital Twin

The development launcher is [development/betagui.py](development/betagui.py).
Use it for mock mode, tests, and the digital twin.

The digital twin is for integration testing, not for the final control-room
launchers. It uses a separate PV profile because it does not expose the full
legacy PV namespace.

Download the Apptainer image locally:

```bash
apptainer pull support/digital_twin/pyat-as-twin-softioc.sif oras://registry.hzdr.de/digital-twins-for-accelerators/containers/pyat-softioc-digital-twin:v0-1-3-mls.2469803
```

`support/digital_twin/*.sif` is gitignored because the image is too large for
GitHub, so other repo users need to download it locally.

Run it:

```bash
apptainer run support/digital_twin/pyat-as-twin-softioc.sif
```

Then test against it:

```bash
python3 scripts/run_digital_twin_demo.py
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

For the current twin, set `alpha0` manually instead of using dynamic `alpha0`.
More detail: [docs/testing_workflow.md](docs/testing_workflow.md)

## Setup

Development environment setup, including `pyenv`, is in [docs/setup.md](docs/setup.md).

Control-room runtime needs:

- Python 3.9
- `numpy`
- `matplotlib`
- `pyepics`
- `tkinter` for the GUI variants

## Output Checks

What matters most operationally:

- matrix-file compatibility with the legacy reference files
- stable chromaticity output in offline regression tests

Reference files:

- [original/SUwithoutorbitbumpResMat.txt](original/SUwithoutorbitbumpResMat.txt)
- [original/SUwithoutorbitbumpResMat2D.txt](original/SUwithoutorbitbumpResMat2D.txt)
- [tests/data/mock_chromaticity_expected.txt](tests/data/mock_chromaticity_expected.txt)

## Docs

Repository docs index: [docs/index.md](docs/index.md)  
GitHub Pages: <https://leogrossman.github.io/betagui/>

## TODO

- validate the standalone `--safe` preflight on the real machine
- validate the standalone write-capable launchers on the real machine
- confirm chromaticity values against control-room expectations
- confirm the restored secondary scan workflow with operators
- restore live BPM orbit plotting if a reliable PV source is available
