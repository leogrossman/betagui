# Testing Workflow

## Purpose

This project now supports two offline testing modes:

- pure mock mode
- container-backed EPICS digital twin mode

Both are intended to let you test and review the port before touching a real machine.

There are now separate control-room and development entrypoints:

- [control_room/betagui.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui.py)
  for legacy-profile control-room GUI use, with `--safe` for read-only preflight
- [control_room/betagui_cli.py](https://github.com/leogrossman/betagui/blob/main/control_room/betagui_cli.py)
  for the most basic live legacy-profile chromaticity measurement from a terminal, with `--safe` for read-only preflight
- [development/betagui.py](https://github.com/leogrossman/betagui/blob/main/development/betagui.py)
  for development, mock mode, and digital twin work

## Mode A: Pure Mock Mode

## What It Uses

- [mock_epics.py](https://github.com/leogrossman/betagui/blob/main/src/mock_epics.py)
- [measurement_logic.py](https://github.com/leogrossman/betagui/blob/main/src/measurement_logic.py)
- [betagui_py3.py](https://github.com/leogrossman/betagui/blob/main/src/betagui_py3.py)

## Behavior

The mock model provides:

- fake PV objects with `.get()` and `.put()`
- RF setpoint behavior
- tune readback behavior
- sextupole current state
- feedback and orbit-mode state
- a simple first-order tune/chromaticity response model

The model is intentionally simple. It is meant to exercise:

- measurement flow
- matrix loading and application
- GUI wiring
- startup behavior

It is not a physics-accurate machine model.

## Run The Python 3 Port In Mock Mode

From the project root:

```bash
python3 development/betagui.py
```

Expected behavior:

- mock mode is selected by default
- no live EPICS connection is required
- no real machine PV writes occur
- the bundled legacy response matrix is loaded if present

## Useful Mock-Mode Checks

1. Start the GUI.
2. Press `Measure alpha0`.
3. Press `Measure the chromaticity`.
4. Confirm that:
   - the status area logs the steps
   - the matrix panel shows a loaded matrix
   - the correction buttons change mock sextupole state
   - plots update if `matplotlib` is available

## Mock-Mode Safety

- mock mode is fully in-memory
- write paths still exist logically, but they only update the mock model
- this makes it suitable for offline review and tests

## Chromaticity Regression Check

The most important numeric regression in this repo is the chromaticity result,
not just matrix-file I/O.

That is covered by:

- [tests/test_output_regression.py](https://github.com/leogrossman/betagui/blob/main/tests/test_output_regression.py)
- [tests/data/mock_chromaticity_expected.txt](https://github.com/leogrossman/betagui/blob/main/tests/data/mock_chromaticity_expected.txt)

This gives a stable offline reference for `xi_x`, `xi_y`, and `xi_s`.

## Mode B: Container-Backed Digital Twin

## Available Twin Images

Local container image:

- `support/digital_twin/pyat-as-twin-softioc.sif`

Remote ORAS image:

- `oras://registry.hzdr.de/digital-twins-for-accelerators/containers/pyat-softioc-digital-twin:v0-1-3-mls.2469803`

This workflow assumes the local `.sif` image is the one you want to run first.

## Start The Container

Manual start:

```bash
apptainer run support/digital_twin/pyat-as-twin-softioc.sif
```

The helper script can also do this for you, but only if you ask it explicitly:

```bash
python3 scripts/run_digital_twin_demo.py --start-container
```

Background start:

```bash
python3 scripts/run_digital_twin_demo.py --start-container --background
```

Important:

- container start is opt-in
- the helper script is read-only with respect to PVs
- it never calls `caput`

## Test EPICS Connectivity From The Host

After the twin is running, start with a small read-only check:

```bash
cainfo TUNEZRP:measX
caget TUNEZRP:measX
```

If those succeed, test a few more legacy PVs:

```bash
cainfo MCLKHGP:setFrq
cainfo S1P2RP:setCur
cainfo IGPF:X:FBCTRL
```

These checks are read-only.

## Compare Available PVs To `betagui.py`

The project already contains the extracted legacy PV list in:

- [pv_inventory.md](pv_inventory.md)

The helper script can probe every PV string found in the original source:

```bash
python3 scripts/run_digital_twin_demo.py --check-legacy-pvs
```

That does the following:

- parses PV names from [original/betagui.py](https://github.com/leogrossman/betagui/blob/main/original/betagui.py)
- runs `cainfo` on each one
- reports which ones appear reachable from the host

If you want values instead of metadata, use `caget` mode:

```bash
python3 scripts/run_digital_twin_demo.py --check-legacy-pvs --use-caget
```

You can also probe selected PVs:

```bash
python3 scripts/run_digital_twin_demo.py --pv TUNEZRP:measX --pv MCLKHGP:setFrq
```

## Run The Python 3 Port Against The Twin

Use the development entrypoint here, not the clean control-room launcher.

Read-only live mode:

```bash
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

This mode:

- tries to use real EPICS
- uses the explicit MLS digital-twin PV mapping instead of the legacy control-room mapping
- suppresses live writes by default
- disables the GUI actions that require write access

Write-capable live mode:

```bash
python3 development/betagui.py --live --allow-writes --pv-profile twin-mls --pv-prefix leo
```

Use this only when you actually want the ported tool to perform the same kind of writes as the legacy script.

## Why The Twin Needs A Separate PV Profile

The current twin does not publish the raw legacy PV names directly.

Examples:

- legacy RF read/write path: `MCLKHGP:setFrq`
- twin RF readback: `leo:MCLKHGP:rdFrq`
- legacy tune X: `TUNEZRP:measX`
- twin tune X: `leo:beam:twiss:x:tune`
- legacy tune Y: `TUNEZRP:measY`
- twin tune Y: `leo:beam:twiss:y:tune`

So the Python 3 port now supports an explicit profile switch:

- `--pv-profile legacy`
- `--pv-profile twin-mls --pv-prefix leo`

The default remains `legacy` so the control-room path is not broken by the twin integration work.

## Twin-Profile Limits

The current twin profile is usable, but it is not a one-to-one match with the legacy machine namespace.

Known limitations:

- no direct `TUNEZRP:*` channels
- no direct `ERMPCGP:rdRmp` in the tested twin namespace
- no direct `PAHRP:setVoltCav` in the tested twin namespace
- no verified synchrotron-tune PV equivalent for legacy `TUNEZRP:measZ`
- feedback/orbit control PVs used by the legacy tool are not part of the current twin profile mapping

Practical consequence:

- when testing against the twin, set `alpha0` manually in the GUI instead of relying on dynamic `alpha0`
- treat the twin run as a safe structural/integration test of startup, RF/tune/sextupole paths, and general measurement flow
- do not assume the twin currently reproduces every control-room side channel used by the original script

## Recommended Validation Order

1. Confirm the container starts.
2. Confirm host `cainfo` / `caget` can see a few known PVs.
3. Run `run_digital_twin_demo.py --check-legacy-pvs`.
4. Start `development/betagui.py --live` and confirm the GUI imports and starts without crashing.
5. Only after that, consider `--allow-writes`.
6. After twin validation, use `control_room/betagui.py --safe` first, then the normal `control_room/` launchers for actual legacy-profile control-room trials.

For the current MLS twin, step 4 should use:

```bash
python3 development/betagui.py --live --pv-profile twin-mls --pv-prefix leo
```

## What The Helper Script Does

See:

- [run_digital_twin_demo.py](https://github.com/leogrossman/betagui/blob/main/scripts/run_digital_twin_demo.py)

Default behavior is read-only:

- print environment information
- check command availability
- print suggested commands
- optionally probe PVs with `cainfo` or `caget`

Opt-in behavior:

- start the Apptainer image when `--start-container` is passed

## Secondary Scan Window

The Python 3 GUI now includes the legacy secondary `sext scan` window again.

What is available:

- polynomial response-matrix measurement
- scan-table candidate generation
- scan-table execution and diagnostic logging when writes are enabled

What to keep in mind:

- this path contains explicit repairs for broken legacy code
- those repairs are documented in [feature_parity.md](feature_parity.md)
- in live machine mode, this is a write-capable path and should be treated with the same care as the main correction workflow

## Known Limits

- the script cannot enumerate every PV published by the IOC unless the IOC provides a separate listing mechanism
- `--check-legacy-pvs` is therefore a targeted reachability check, not a full PV discovery tool
- the mock mode is intentionally plausible, not high-fidelity
- the current twin requires its own PV profile and does not fully expose the legacy auxiliary PV set

## Summary

Use mock mode first for rapid review and code understanding.

Use the digital twin second to answer:

- does EPICS connectivity work from the host?
- which legacy PV names are actually present?
- does the Python 3 port start cleanly against a realistic IOC environment?

Use the safe control-room launchers first, and the normal control-room
launchers only after that read-only preflight is successful.

If you need only the core measurement without the GUI, use:

```bash
python3 control_room/betagui_cli.py
```
