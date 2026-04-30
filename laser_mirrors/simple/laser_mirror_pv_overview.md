# SSMB Laser Mirror PV Overview and Implementation Notes

This document summarizes the EPICS/PV findings and a roadmap for adding features to the laser mirror scan tool.

## Confirmed mirror motor PVs

From the EDM panels and safe PV inspection, the laser mirror motors are EPICS motor records:

| Logical name | PV base | EDM description | Axis meaning |
|---|---:|---|---|
| `m1_vertical` | `MNF1C1L2RP` | Mirror 1 vertical | mirror 1 vertical motor |
| `m1_horizontal` | `MNF1C2L2RP` | Mirror 1 horizontal | mirror 1 horizontal motor |
| `m2_vertical` | `MNF2C1L2RP` | Mirror 2 vertical | mirror 2 vertical motor |
| `m2_horizontal` | `MNF2C2L2RP` | Mirror 2 horizontal | mirror 2 horizontal motor |

The inspection confirmed at least for mirror 2:

- `RTYP = motor`
- `EGU = steps`
- `Access = read, write`
- `.VAL`, `.RBV`, `.DMOV`, `.MOVN`, `.STOP`, `.DESC`, `.EGU`, `.STAT`, `.SEVR` exist.

The EDM panels show the same structure for mirror 1.

## Standard EPICS motor fields to use

For each base PV, e.g. `MNF2C2L2RP`:

| Field | Meaning | Use in program |
|---|---|---|
| `.VAL` | commanded setpoint | write target step position |
| `.RBV` | readback value | read actual step position |
| `.DMOV` | done moving | wait until `1` before measuring |
| `.MOVN` | moving | live status indicator |
| `.STOP` | stop command | write `1` for emergency stop |
| `.DESC` | description | label in GUI |
| `.EGU` | engineering units | expected `steps` |
| `.STAT` | alarm status | log/display |
| `.SEVR` | alarm severity | log/display |
| `.RTYP` | record type | expected `motor` |

## Important conclusion

The old `.NET / New Focus CmdLib` path is no longer needed for this program if the control-room EPICS motor records are the official interface.

The control chain should be:

```text
Python GUI
→ pyepics PV.put() / PV.get()
→ EPICS motor record
→ motor driver / IOC
→ physical mirror motor
```

## Current single-file GUI

`laser_angle_scan_gui.py` implements:

- read-only mode by default
- explicit `--write-mode` required for real motor writes
- `--safe-mode` for offline simulation
- live motor status table
- captured reference step positions
- Carsten-style angle scan:
  - target horizontal/vertical interaction angle
  - held horizontal/vertical offset
  - two-mirror compensation using legacy geometry
- live schematic mirror/beam view
- live P1 map and trace
- CSV + log + config JSON output

## Geometry assumptions

Current values copied from legacy code:

| Quantity | Value |
|---|---:|
| mirror separation | `2285 mm` |
| mirror 2 to undulator center | `6010 mm` |
| horizontal scale | `2.75 µrad / step` |
| vertical scale | `1.89 µrad / step` |

The transform is:

```text
desired undulator offset + desired undulator angle
→ mirror 1 angular delta + mirror 2 angular delta
→ motor step delta
→ absolute EPICS motor .VAL = captured reference + delta
```

## Things to verify experimentally

Before serious scans:

1. Confirm sign convention for all four motors.
2. Confirm horizontal/vertical mapping:
   - `C1 = vertical`
   - `C2 = horizontal`
3. Confirm the old `µrad/step` values still match the EPICS motor records.
4. Confirm whether `.VAL` and `.RBV` are absolute step coordinates or resettable relative positions.
5. Confirm that `.DMOV = 1` reliably indicates no motion before reading P1.
6. Confirm an appropriate P1 PV name.

## Candidate P1 / live evaluation PVs

From the uploaded `LiveEvaluation` project, the SSMB live analysis code uses PV construction around:

```text
SCOPE1ZULP:h1p1:rdAmpl
SCOPE1ZULP:h1p2:rdAmpl
SCOPE1ZULP:h1p3:rdAmpl
SCOPE1ZULP:h1p1:rdAmplAv
SCOPE1ZULP:h1p1:rdAmplDev
SCOPE1ZULP:h1p1:rdTurnNr
SCOPE1ZULP:h1p1:rdPeakNr
```

The exact P1 PV for this scan should be confirmed on the control-room machine or from the live analysis panel.

## Future features to add

### 1. Proper P1 integration

Add a dropdown for candidate harmonic PVs:

```text
SCOPE1ZULP:h1p1:rdAmpl
SCOPE1ZULP:h1p2:rdAmpl
SCOPE1ZULP:h1p3:rdAmpl
```

and averaged variants:

```text
SCOPE1ZULP:h1p1:rdAmplAv
...
```

### 2. Optimizer

After coarse grid scan:

1. choose best point
2. run smaller local grid around best point
3. optionally fit a 2D Gaussian/parabola
4. suggest final motor positions

### 3. More scan modes

- mirror 2 only, like old `mirrorsSpiral.py`
- full two-mirror angle scan
- one mirror primary, solve the other to hold offset
- rectangular spiral
- adaptive hill climb

### 4. Safety layer

Add configurable soft limits around captured reference:

```text
max horizontal step delta
max vertical step delta
max absolute motor command
```

Before every scan, preview all commands and reject out-of-range targets.

### 5. Better live visualization

- overlay planned path
- show current point number
- use true optical table distances in the schematic
- display mirror angular deltas and motor step targets
- display RBV vs target error

### 6. Persistent configuration

Use a JSON config file:

```text
laser_angle_scan_config.json
```

containing:

- motor PV bases
- P1 PV
- geometry calibration
- scan defaults
- soft limits
- last reference state

### 7. Use EDM/Phoebus panels as PV source

Search panel files for additional useful PVs:

```bash
grep -R "SCOPE1ZULP" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
grep -R "MNF1C" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
grep -R "MNF2C" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
```

Keep searches targeted and non-invasive.

## Minimal safe run procedure

1. Start read-only:

```bash
python3 laser_angle_scan_gui.py
```

2. Check PV status:
   - all four motors connected
   - `RTYP = motor`
   - `EGU = steps`
   - `DMOV = 1`
   - `SEVR = NO_ALARM`

3. Press `Capture current RBV as reference`.

4. Press `Preview plan`.

5. Inspect planned motor commands.

6. Start write-enabled only when ready:

```bash
python3 laser_angle_scan_gui.py --write-mode
```

7. Use small spans and few points first.
