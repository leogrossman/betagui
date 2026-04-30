# SSMB Laser Mirror Scan GUI

EPICS-native control-room tool for laser mirror scans.

This project replaces the old `.NET / New Focus CmdLib` path with direct EPICS motor-record access.

## Confirmed motor PVs

| Logical name | PV base | Meaning |
|---|---|---|
| `m1_vertical` | `MNF1C1L2RP` | Mirror 1 vertical |
| `m1_horizontal` | `MNF1C2L2RP` | Mirror 1 horizontal |
| `m2_vertical` | `MNF2C1L2RP` | Mirror 2 vertical |
| `m2_horizontal` | `MNF2C2L2RP` | Mirror 2 horizontal |

These are EPICS motor records with `.VAL`, `.RBV`, `.DMOV`, `.MOVN`, `.STOP`, `.DESC`, `.EGU`, `.STAT`, `.SEVR`.

## Run

Read-only / preview mode:

```bash
python3 run_gui.py
```

Offline simulation:

```bash
python3 run_gui.py --safe-mode
```

Real motor writes:

```bash
python3 run_gui.py --write-mode
```

## Implemented

- EPICS motor backend using `pyepics`
- safe simulated backend
- read-only default mode
- explicit `--write-mode` for motor writes
- live motor status table
- manual motor control panel with slow ramped moves
- capture current `.RBV` as reference
- return to reference
- STOP all motors
- Carsten-style angle scan:
  - vary horizontal and/or vertical interaction angle
  - hold horizontal/vertical offset fixed
  - convert undulator target to two-mirror motor step targets
- horizontal-only fixed vertical angle scan
- vertical-only fixed horizontal angle scan
- 2D angle scan with live selected signal map
- legacy mirror-2 spiral scan
- live 2D mirror-2 spiral map showing selected signal vs mirror 2 step position
- schematic two-plane ray drawing
- logging, CSV output, config JSON output
- unit tests for geometry and scan planning

## Crash recovery and restore behavior

The GUI writes two top-level files in the working directory, outside the per-run folder:

```text
laser_mirror_recovery_state.json
laser_mirror_last_command.json
```

These are updated before and after write commands. If the GUI crashes, restart it, inspect these files, compare with live `.RBV`, then use `Capture RBV as reference` or `Return to reference` deliberately.

The program cannot guarantee physical recovery after a controller/IOC crash unless the EPICS motor record and hardware readback remain valid. The recovery files make the last intended and last observed state explicit.

## Output

Each run creates:

```text
laser_mirror_runs/<timestamp>/
    run.log
    config.json
    angle_scan.csv
    mirror2_spiral.csv
```

## Important operating model

The app treats the current motor `.RBV` values as a reference state.

For the angle scan:

```text
desired undulator offset/angle
→ mirror 1 / mirror 2 angular changes
→ step changes using legacy µrad/step calibration
→ absolute EPICS motor .VAL = captured reference + step change
```

## Preflight and waiting behavior

Before a real scan starts, the GUI opens a preflight popup listing all planned absolute motor `.VAL` commands:

```text
index, mode, angle_h, angle_v, M1H, M1V, M2H, M2V, max_delta_from_reference, estimated ramp layers
```

A scan only starts after pressing `Approve and run`.

During moves, the program:

1. splits large moves into ramp layers,
2. writes one small `.VAL` target per motor,
3. waits for `.DMOV = 1` for each motor,
4. waits an additional settle time,
5. only then reads the selected signal PV.

The normal scan stop button is **not** a hard motor stop. It requests stop after the current ramp/point. The separate `STOP all` button writes `.STOP=1` and should be treated as an emergency/hard stop.

## Motion throttling

The default motion throttle is conservative:

```text
max_step_per_put = 50 steps
inter_put_delay = 0.25 s
settle_s = 0.2 s
max_delta_from_reference = 500 steps
```

For commissioning, use even smaller values if controllers crash. The old spiral script used 6/8 step increments and 10 s dwell; that is much gentler than large angle scans.

## Not fully verified yet

The implementation is complete enough for controlled testing, but the following must be experimentally verified before serious operation:

1. Sign convention of all four motors.
2. Whether the old `µrad/step` calibration still matches the EPICS motor records.
3. Whether `mirror2_horizontal_sign = -1` and `mirror2_vertical_sign = +1` are correct for the EPICS PVs.
4. Whether `.RBV` is stable and persistent enough to use as reference.
5. Whether `.DMOV=1` reliably means the optical motion has settled.
6. The correct P1 PV name.
7. Soft limits around reference before large scans.

## Animation / diagram status

The current drawing is a schematic steering model:

```text
Laser input → M1 → M2 → undulator center
```

It uses the measured distances:

- M1 to M2: 2285 mm
- M2 to undulator: 6010 mm

It is not a full optical-table CAD drawing. The uploaded PoP II layout documents show many additional optics, including Pockels cell PC4, polarizing beam splitter cube, half-wave plate, telescope lenses, photodiodes and power meters. Those components are listed in `TODO.md` as future schematic layers.

## Tests

```bash
python3 -m unittest discover -s tests -v
```


## Why 50 µm / 50-step changes may have failed

Changing only a GUI "limit" does not necessarily change the actual scan amplitude. In this code the scan commands are derived from:

```text
angle span [µrad]
held offset [mm]
geometry calibration [µrad/step]
reference step positions
```

So if you changed a "50 µm" limit but left the 2D angle sweep span at 200 µrad or 400 µrad, the generated motor step targets may still have been large. Use the preflight popup to inspect the actual `.VAL` commands.

Also, `50 µm` is a beam/optical displacement unit, while the motor PVs use `steps`. The conversion depends on mirror geometry and calibration. Do not assume `50 µm = 50 steps`.

## Why pressing stop may crash the controller

There are two different stop concepts:

1. Graceful scan stop: finish the current ramp/point, then stop issuing new commands.
2. Motor record hard stop: write `.STOP=1`.

If the underlying Picomotor/IOC is already busy, sending `.STOP` during rapid command traffic can stress or crash the controller/IOC. For commissioning, prefer graceful stop. Use hard `STOP all` only when needed.


## Control-room diagnostics

The Overview tab now has:

```text
Full motor diagnostics
Export diagnostics
```

This reads a targeted set of motor-record fields for each mirror PV, including readback, motion status, limits, velocity/acceleration-like fields, alarm state, and raw motor status fields when available. It writes both JSON and TXT files into the session directory.

The diagnostic reads are intentionally targeted. They do not use wildcard PV scans and do not write to hardware.
