# Laser Mirrors

Standalone control-room GUI for **laser-mirror steering, angle scans, recovery, and overlap studies** near the SSMB undulator interaction region.

This folder lives next to `SSMB_experiment/` on purpose. The goal is one `git pull` in the control room, with the mirror tool kept modular enough that it can evolve independently.

## What this tool is for

Carsten's measurement idea is:

- vary the **interaction angle** of the laser at the undulator
- hold the **interaction point in space** as fixed as possible with the second mirror
- observe a live response signal:
  - `P1`
  - `P3`
  - `QPD σx / σy`
  - `QPD center-x`
- build a 1D or 2D map of signal vs steering
- find a recommended best point
- move back to that point safely

The tool also includes:

- normal manual mirror control
- recovery / restore state handling
- controller-safe motion throttling
- explicit previews of the EPICS motor commands that would be sent
- graceful scan stop and hard emergency stop separation
- passive monitoring mode that reconstructs quasi-sweeps from externally moved mirrors
- controller pen-test diagnostics tab for cautious IOC stress probing
- an offline digital twin that runs on a normal laptop without EPICS

## Important safety model

The mirror controller/IOC has already shown instability in the past. This tool is intentionally conservative:

- default real mode is **read-only** unless `--write-mode` is used
- `--safe-mode` simulates motors and the selected signal
- all real moves are split into small EPICS `.VAL` ramps
- the tool waits for `.DMOV=1`
- the tool waits an additional settle time
- every planned write is logged
- last-command and recovery files are written before/while moving
- hard `STOP` is available, but it is treated as an emergency action

Recommended commissioning pattern:

1. start in read-only mode
2. check live readbacks and alarm fields
3. capture current RBV as reference
4. preview scan commands
5. only then enable `--write-mode`

## Confirmed motor PVs

These are the mirror motors currently used by the tool:

| Logical name | PV base | Meaning |
|---|---|---|
| `m1_vertical` | `MNF1C1L2RP` | Mirror 1 vertical |
| `m1_horizontal` | `MNF1C2L2RP` | Mirror 1 horizontal |
| `m2_vertical` | `MNF2C1L2RP` | Mirror 2 vertical |
| `m2_horizontal` | `MNF2C2L2RP` | Mirror 2 horizontal |

Useful motor-record fields used or inspected:

- `.VAL`
- `.RBV`
- `.DMOV`
- `.MOVN`
- `.STOP`
- `.DESC`
- `.EGU`
- `.STAT`
- `.SEVR`
- `.RTYP`
- `.HLM`
- `.LLM`
- `.VELO`
- `.ACCL`

## Confirmed signal PV presets

The tool ships with real control-room presets, not just placeholders:

| Preset key | Label | PV |
|---|---|---|
| `p1_h1_raw` | P1 raw | `SCOPE1ZULP:h1p1:rdAmpl` |
| `p1_h1_avg` | P1 avg | `SCOPE1ZULP:h1p1:rdAmplAv` |
| `p1_h1_std` | P1 std | `SCOPE1ZULP:h1p1:rdAmplDev` |
| `p3_h1_raw` | P3 raw | `SCOPE1ZULP:h1p3:rdAmpl` |
| `p3_h1_avg` | P3 avg | `SCOPE1ZULP:h1p3:rdAmplAv` |
| `qpd01_sigma_x` | QPD01 sigma X | `QPD01ZL2RP:rdSigmaX` |
| `qpd01_sigma_y` | QPD01 sigma Y | `QPD01ZL2RP:rdSigmaY` |
| `qpd01_center_x_avg` | QPD01 center X avg | `QPD01ZL2RP:rdCenterXav` |
| `qpd00_sigma_x` | QPD00 sigma X | `QPD00ZL4RP:rdSigmaX` |
| `qpd00_sigma_y` | QPD00 sigma Y | `QPD00ZL4RP:rdSigmaY` |
| `qpd00_center_x_avg` | QPD00 center X avg | `QPD00ZL4RP:rdCenterXav` |

These come from:

- your working V3/V4 prototypes under `simple/`
- `simple/inspo/SSMB/LiveEvaluation/`
- the confirmed `SSMB_experiment` inventory

## Geometry and experiment assumptions

The current transform uses:

- mirror 1 to mirror 2 distance: `2285 mm`
- mirror 2 to undulator center distance: `6010 mm`
- horizontal calibration: `2.75 µrad / step`
- vertical calibration: `1.89 µrad / step`

The operating model is:

```text
desired undulator offset + desired interaction angle
→ mirror 1 / mirror 2 angular changes
→ step changes via calibration
→ absolute EPICS motor targets around a captured reference RBV
```

The GUI currently treats:

- `Offset X / Y [mm]` as the held interaction-point offset
- `Center X / Y [µrad]` and `Span X / Y [µrad]` as the scan coordinates

### Solve modes

The angle scan supports three solve modes:

- `two_mirror_target`
  - interpret the scan directly as undulator-space angle targets
  - both mirrors are solved from geometry
- `mirror1_primary`
  - treat the scan angle as a direct mirror-1 steering variable
  - solve mirror 2 analytically to hold the offset
- `mirror2_primary`
  - treat the scan angle as a direct mirror-2 steering variable
  - solve mirror 1 analytically to hold the offset

This is the key place where the tool now goes beyond the simple early scripts.

### Which one does Carsten really want?

Carsten's wording was:

> vary one mirror angle and keep the same point in space with the other mirror.

That means the most literal implementation is **not** `two_mirror_target`.
The most literal implementation is one of the **primary** modes:

- `mirror1_primary`
  - mirror 1 is the driving mirror
  - mirror 2 is solved analytically to counter-steer and hold the interaction point
- `mirror2_primary`
  - mirror 2 is the driving mirror
  - mirror 1 is solved analytically to counter-steer and hold the interaction point

So the real commissioning question is:

- which mirror do we want to use as the deliberately scanned mirror?
- which mirror is mechanically/operationally better suited to be the compensator?

The GUI defaults to `mirror1_primary`, but this is still a commissioning choice, not
an established physics truth.

## UI overview

### `Overview`

- machine and safety config
- signal preset selection
- live signal readout
- motor status table
- capture current RBV as reference
- return to startup reference
- save/restore motor state
- live schematic of the optical steering path

### `Manual control`

- direct motor nudges
- direct absolute motor moves
- hard emergency stop
- uses the same ramped `.VAL` path as scans

### `Angle scan`

- horizontal-only
- vertical-only
- full 2D scan
- command preview popup
- live 2D colored signal map
- live signal-vs-point trace
- best-point recommendation
- move-to-best-point button

### `Mirror 2 spiral`

- legacy-style mirror-2 scan
- useful for comparison with the older mirror scripts

### `Passive monitor`

- logs the selected signal plus all four motor RBVs at every poll
- reconstructs passive parameter-space maps from observed motion
- useful when an external tool or manual operation is moving the mirrors
- lets you study a sweep without trusting this GUI to send motor commands

### `Controller pen test`

- intentionally experimental and conservative
- ramps one motor around the current reference in tiny back-and-forth steps
- returns toward the reference repeatedly
- logs signal and motor alarm/state fields
- meant to help diagnose controller/IOC crash sensitivity without making large moves

### `Debug / Logs`

- live UI diagnostics
- planned command logging
- exported motor diagnostic snapshots

## Recovery and restore behavior

There are several state files on purpose:

### 1. Legacy setpoint file

Path:

```text
src_materials/MirrorControl/mirror_state.ini
```

Purpose:

- preserve compatibility with the old `MirrorControlWindow` concept
- restore previous UI setpoints / believed undulator state

### 2. Motor recovery JSON

Path:

```text
laser_mirror_motor_state.json
```

Purpose:

- save current real motor RBVs
- save captured reference
- make it easy to recover after a UI crash

### 3. Last-command JSON

Path:

```text
laser_mirror_last_command.json
```

Purpose:

- record the exact command plan that was last being executed
- inspect what `.VAL` sequence the tool intended to send

If the GUI crashes, the intended workflow is:

1. restart the GUI in read-only mode
2. inspect live `.RBV`
3. inspect `laser_mirror_motor_state.json`
4. inspect `laser_mirror_last_command.json`
5. decide whether to:
   - capture current RBV as the new reference
   - return to the saved motor state
   - return to the startup reference

## Current standard defaults

These defaults are intentionally conservative:

- `safe_mode = False`
- `write_mode = False`
- signal preset: `P1 avg`
- angle spans: `50 µrad`
- `7 x 7` points
- `1.0 s` dwell
- `5` samples per point
- `mirror1_primary` solve mode
- motion throttle:
  - `max_step_per_put = 8`
  - `inter_put_delay_s = 0.35`
  - `settle_s = 0.8`

Those are deliberately slower and gentler than a “fast” scan. You can relax them later after you confirm that the controller stays stable.

## Control-room run instructions

From the control-room terminal:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_mirrors_gui.py
```

Dry-run / no hardware writes:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_mirrors_gui.py --safe-mode
```

Real motor writes enabled:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_mirrors_gui.py --write-mode
```

Recommended first real session:

```bash
python3 laser_mirrors_gui.py
```

Then:

1. confirm signal preset and live readback
2. inspect motor table alarms and RBVs
3. `Capture current RBV as reference`
4. `Preview commands`
5. restart with `--write-mode` only when the preview looks sensible

## Output

The output root is configurable in the GUI and saved in the config file.

By default it is:

```text
laser_mirror_runs/
```

Each scan creates a session directory with:

- `config.json`
- `plan.json`
- `commands.jsonl`
- `measurements.csv`
- `last_move_plan.json`
- `best_point.json` (when available)

There is also a diagnostics export button for motor snapshots.

Each GUI launch also creates an application-session directory with:

- `app.log`
- `passive_samples.jsonl`
- `passive_samples.csv`
- `session_summary.json`

That means even if mirrors are moved externally, the running GUI can still be used as a
passive logging/reconstruction tool.

## Tests

From the repo root:

```bash
python3 -m unittest discover -s laser_mirrors/tests -v
```

Digital twin on a laptop:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_optics_digital_twin.py --animate
```

This currently covers:

- geometry round-trips
- fixed-offset analytic solves
- scan-grid generation
- best-point selection
- legacy state save/load
- controller ramp splitting
- unsafe-target blocking
- safe-mode motor move updates

## Source material and references

### Actively used for this implementation

- `simple/laser_mirror_scan_project_v3/`
- `simple/laser_mirror_scan_project_v4/`
- `simple/inspo/SSMB/LiveEvaluation/`
- `src_materials/MirrorControl/`
- `src_materials/mirrorsSpiral.py`
- `src_materials/WEPMO02.pdf`
- `src_materials/see Fig07 - TUP70.pdf`
- `src_materials/laser_setup/`

### Useful PV / implementation inspiration that should be mined later

- `simple/inspo/SSMB/MirrorControl/`
- `simple/inspo/SSMB/StripTools/`
- `SSMB_experiment/ssmb_tool/inventory.py`
- `control_room/machine_check.py`

## What is not fully verified yet

Be honest before beam time:

| Item | Status |
|---|---|
| Motor sign convention of all four axes | Not fully verified |
| `µrad / step` calibration on the live controller | Not fully verified |
| Exact best default solve mode for Carsten's scan | Not fully verified |
| Whether `DMOV=1` is always a sufficient settle indicator | Not fully verified |
| Maximum safe command rate before IOC/controller stress | Not fully verified |
| Full optical-table schematic with every static optic | Not fully implemented |
| Automatic closed-loop “keep point fixed from measured camera signal” | Not implemented |
| Robust controller-specific root-cause diagnosis for the crashy IOC | Not solved yet |

## Feature / roadmap table

| Feature | Status | Notes |
|---|---|---|
| Real EPICS motor-record backend | Implemented | Uses `.VAL/.RBV/.DMOV/.STOP` |
| Read-only by default | Implemented | `--write-mode` required for real writes |
| Safe mode | Implemented | Simulated motors + simulated signal |
| Real signal presets | Implemented | P1, P3, QPD sigma and center |
| Manual control | Implemented | Nudge, absolute move, emergency stop |
| Save/restore current motor state | Implemented | JSON recovery file |
| Restore startup reference | Implemented | Based on captured RBV |
| Legacy `mirror_state.ini` compatibility | Implemented | For continuity with old tool |
| Horizontal / vertical / 2D sweep | Implemented | In angle-scan tab |
| Mirror 2 spiral | Implemented | Separate tab |
| Live 2D signal map | Implemented | Canvas-based |
| Live 1D signal trace | Implemented | In Overview |
| Passive quasi-sweep reconstruction | Implemented | Rebuilds signal maps from observed RBV motion |
| Best-point recommendation | Implemented | `max` or `min` objective |
| Move to best point | Implemented | Uses same safe motor path |
| Preflight command preview | Implemented | For manual moves and scans |
| Controller pen test | Implemented | Small back-and-forth stress probe around reference |
| Offline digital twin | Implemented | Runs on a laptop with no EPICS |
| Full optical CAD-style animation | Partial | Faithful ordered schematic, but not surveyed metrology |
| Measured feedback loop on beam/screen signal | Not yet | Future upgrade |
| Controller/IOC model and bug archaeology | Not yet | Needs controls follow-up |

## Notes for future extension into `SSMB_experiment`

The PV inventory and safe EPICS motor patterns here are good candidates to later reuse in `SSMB_experiment/`, especially:

- real P1 / P3 signal presets
- QPD sigma / center presets
- state / recovery / preview patterns
- command throttling and alarm lockout
- best-point recommendation logic

That reuse is intentionally not forced yet; this project stays a modular standalone tool first.
