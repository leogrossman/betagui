# EPICS Write Paths In `original/betagui.py`

## Safety Notes

- The original script is not read-only by default.
- Several GUI actions immediately write to PVs.
- Some write paths also disable feedback and orbit correction.
- File save paths are not listed here unless they are part of a machine-state-changing workflow.

## Direct Write Helpers

### `set_frf_slowly(target_frf_in_Hz)`

Writes:

- `MCLKHGP:setFrq`

Used by:

- `set_all2ini()`
- `MeaChrom()`

Effect:

- ramps RF setpoint in 10 steps

## Restore / Reset Path

### `set_all2ini(dchrom_readout, bt1, bt2)`

Writes:

- `MCLKHGP:setFrq`
- `S1P1RP:setCur`
- `S1P2RP:setCur`
- `S2P1RP:setCur`
- `S2P2KRP:setCur`
- `S2P2LRP:setCur`
- `S3P1RP:setCur`
- `S3P2RP:setCur`
- `IGPF:X:FBCTRL`
- `IGPF:Y:FBCTRL`
- `IGPF:Z:FBCTRL`
- `ORBITCCP:selRunMode`
- `PAHRP:cmdExtPhasMod`

Trigger:

- main-window `reset` button

Effect:

- attempts to restore saved sextupole, RF, feedback, and orbit states

## Degauss Helper

### `set_sext_degauss(sextlist, target)`

Writes:

- every PV in `sextlist`
- always also `S1P1RP:setCur`
- always also `S1P2RP:setCur`

Trigger:

- no active caller found in main flow

Effect:

- applies oscillating current pattern then final target current

## Main Chromaticity Measurement

### `MeaChrom(bt_obj, bt_obj2, f_obj, fig, InputVar, bt_cor)`

Writes at measurement start:

- `IGPF:X:FBCTRL` -> `0`
- `IGPF:Y:FBCTRL` -> `0`
- `IGPF:Z:FBCTRL` -> `0`
- `ORBITCCP:selRunMode` -> `0`

Writes during scan:

- `MCLKHGP:setFrq` via `set_frf_slowly()`

Writes at measurement end:

- `MCLKHGP:setFrq` restored to `frf0`
- `IGPF:X:FBCTRL` restored from `ini_fdb`
- `IGPF:Y:FBCTRL` restored from `ini_fdb`
- `IGPF:Z:FBCTRL` restored from `ini_fdb`
- `ORBITCCP:selRunMode` restored from `ini_orbit`

Trigger:

- `Measure the chromaticity` button
- also indirectly called by matrix measurement and polynomial scan workflows

Effect:

- changes machine RF and disables/restores feedback/orbit correction around the scan

## Manual Chromaticity Correction

### `set_all_sexts(delta_chrom)`

Always writes:

- `S1P2RP:setCur`
- `S2P2KRP:setCur`
- `S2P2LRP:setCur`

Conditionally writes:

- `S1P1RP:setCur` when `mat_status` is `1` or `3`
- `S2P1RP:setCur` when `mat_status` is `1` or `3`
- `S3P1RP:setCur` when 3D matrix and `mat_status == 3`
- `S3P2RP:setCur` when 3D matrix

Trigger:

- manual `+/- xi_x`, `+/- xi_y`, `+/- xi_s` buttons via `change_sext_cur()`

Effect:

- increments sextupole set currents according to inverse response matrix `B`

## Response Matrix Measurement

### `start_bump(obj, obj2)`

Direct writes:

- selected sextupole groups stepped by `-1`
- then stepped by `+1`

Indirect writes through `MeaChrom()`:

- `IGPF:X:FBCTRL`
- `IGPF:Y:FBCTRL`
- `IGPF:Z:FBCTRL`
- `ORBITCCP:selRunMode`
- `MCLKHGP:setFrq`

Sextupole groups by mode:

- `2D`: `[S1P1,S1P2]`, `[S2P1,S2P2K,S2P2L]`
- `2D(P2)`: `[S1P2]`, `[S2P2K,S2P2L]`
- `3D`: adds `[S3P1,S3P2]`
- `3D(P2)`: adds `[S3P2]`

Trigger:

- `Measure matrix` button

Effect:

- perturbs sextupole currents and repeatedly runs full chromaticity measurement

Risk:

- no guaranteed full sextupole restore on interruption

## Secondary Window Polynomial Scan

### `start_poly(obj, obj2)`

Intended direct writes:

- sextupole currents through missing helper `setcur(...)`

Indirect writes through `MeaChrom()`:

- `IGPF:X:FBCTRL`
- `IGPF:Y:FBCTRL`
- `IGPF:Z:FBCTRL`
- `ORBITCCP:selRunMode`
- `MCLKHGP:setFrq`

Trigger:

- secondary window `Measure` button

Current status:

- incomplete / broken because `setcur(...)` is missing

## Secondary Window Scan Table

### `gen_scan_tab()`

Current EPICS write status:

- no active PV writes in the checked-in source

Reason:

- the sextupole write calls are commented out

Still reads:

- sextupole set currents
- energy/current diagnostics
- QPD readbacks
- tune readbacks
- orbit mode
- white-noise voltage

Trigger:

- secondary window `Scan` button

Effect:

- read-only diagnostic logging in current form, despite generating candidate sextupole settings
