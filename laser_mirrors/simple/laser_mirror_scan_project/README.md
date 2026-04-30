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
- capture current `.RBV` as reference
- return to reference
- STOP all motors
- Carsten-style angle scan:
  - vary horizontal and/or vertical interaction angle
  - hold horizontal/vertical offset fixed
  - convert undulator target to two-mirror motor step targets
- horizontal-only fixed vertical angle scan
- vertical-only fixed horizontal angle scan
- 2D angle scan with live P1 map
- legacy mirror-2 spiral scan
- live 2D mirror-2 spiral map showing P1 vs mirror 2 step position
- schematic two-plane ray drawing
- logging, CSV output, config JSON output
- unit tests for geometry and scan planning

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
