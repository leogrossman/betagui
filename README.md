# betagui

Python 3.9 port of a legacy MLS control-room chromaticity tool.

This repo is organized for two audiences:

- control-room users: run the legacy-profile tool
- developers: work with tests, mock mode, and the digital twin

## Control-Room Start

Main files:

- [control_room/betagui.py](control_room/betagui.py)
  normal control-room GUI, write-capable by default
- [control_room/betagui_safe.py](control_room/betagui_safe.py)
  read-only GUI preflight
- [control_room/betagui_cli.py](control_room/betagui_cli.py)
  normal control-room CLI fallback, write-capable by default
- [control_room/betagui_cli_safe.py](control_room/betagui_cli_safe.py)
  read-only CLI preflight

Use these in order:

```bash
python3 control_room/betagui_safe.py
python3 control_room/betagui_cli_safe.py
python3 control_room/betagui.py
python3 control_room/betagui_cli.py
```

Important:

- `*_safe.py` means live EPICS but no machine writes
- `betagui.py` and `betagui_cli.py` are the normal legacy-style launchers
- those normal launchers are write-capable by default, like the original script

Before first machine use:

- [CONTROL_ROOM.md](CONTROL_ROOM.md)
- [docs/runtime_checklist.md](docs/runtime_checklist.md)
- [docs/control_room_test_plan.md](docs/control_room_test_plan.md)
- [docs/write_paths.md](docs/write_paths.md)
- [docs/setup.md](docs/setup.md)

## Development Start

Development launcher:

- [development/betagui.py](development/betagui.py)

Run:

```bash
python3 development/betagui.py
```

Useful docs:

- [DEVELOPMENT.md](DEVELOPMENT.md)
- [docs/index.md](docs/index.md)
- [docs/testing_workflow.md](docs/testing_workflow.md)

## What The Tool Does

The tool:

- measures chromaticity by RF sweep and tune readback
- measures sextupole response matrices
- applies manual chromaticity corrections
- resets saved machine settings
- provides a secondary sextupole scan workflow

The original Python 2 source is preserved untouched in [original/](original).

## Feature Comparison

| Feature | Legacy tool | Python 3 port |
| --- | --- | --- |
| RF-sweep chromaticity measurement | Yes | Yes |
| Dynamic `alpha0` | Yes | Yes |
| Response-matrix measurement | Yes | Yes |
| Matrix load/save | Yes | Yes |
| Manual sextupole correction | Yes | Yes |
| Reset to saved state | Yes | Yes |
| Secondary sextupole scan window | Yes | Yes |
| Mock offline mode | No | Yes |
| Digital twin mode | No | Yes |
| Barebones CLI fallback | No | Yes |

Full parity notes:

- [docs/feature_parity.md](docs/feature_parity.md)

## Read-Only Mode

Read-only mode is for preflight checks:

- live EPICS connection is allowed
- write paths are suppressed
- use it to confirm imports, PV visibility, and GUI startup before real runs

Use:

```bash
python3 control_room/betagui_safe.py
python3 control_room/betagui_cli_safe.py
```

## Digital Twin

The digital twin is for development and integration testing, not for the final
control-room launchers.

⚠️ **Container not included (too large for GitHub). Download it first:**

```bash
apptainer pull support/digital_twin/pyat-as-twin-softioc.sif oras://registry.hzdr.de/digital-twins-for-accelerators/containers/pyat-softioc-digital-twin:v0-1-3-mls.2469803
```

Start the twin:

```bash
apptainer run support/digital_twin/pyat-as-twin-softioc.sif
```

Check the twin:

```bash
python3 scripts/run_digital_twin_demo.py
```

Run the development GUI against the twin:

```bash
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

Notes:

- the twin does not expose the full legacy PV namespace
- it uses a separate PV profile on purpose
- for the current twin, set `alpha0` manually instead of using dynamic `alpha0`

More:

- [docs/testing_workflow.md](docs/testing_workflow.md)

## Output Parity

Two output checks matter:

- matrix-file compatibility with the legacy text files
- stable chromaticity regression in mock mode

The files in [original/](original) are matrix references, not saved
chromaticity measurements.

Matrix compare example:

```bash
python3 scripts/compare_outputs.py original/SUwithoutorbitbumpResMat.txt original/SUwithoutorbitbumpResMat.txt --assert-max-abs 0
```

Chromaticity regression reference:

- [tests/data/mock_chromaticity_expected.txt](tests/data/mock_chromaticity_expected.txt)

## Repo Layout

- [control_room/](control_room): operator-facing launchers
- [development/](development): development launcher
- [src/](src): shared library code
- [original/](original): untouched legacy source and matrix files
- [support/](support): digital twin container and bundled reference packages
- [docs/](docs): operator, developer, and theory docs
- [tests/](tests): `unittest` suite
- [scripts/](scripts): helper scripts and diagnostics

## Docs

<https://leogrossman.github.io/betagui/>

- config: [mkdocs.yml](mkdocs.yml)
- workflow: [.github/workflows/pages.yml](.github/workflows/pages.yml)

## TODO

- validate `control_room/betagui_safe.py` on the real machine
- validate `control_room/betagui.py` on the real machine
- validate the CLI fallback on the real machine
- confirm the restored secondary scan workflow with operators
- restore live BPM orbit plotting if a reliable PV source is available
- enable GitHub Pages after the first push
