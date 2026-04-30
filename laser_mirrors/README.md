# Laser Mirrors

Standalone control-room-style tool for scanning the **laser interaction angle at the undulator while keeping the hit point fixed** as well as possible with the second mirror.

This folder is intended as a small self-contained project inside the broader SSMB work area. It reuses the old mirror geometry/calibration ideas, but rewrites the control logic into a clearer, testable, modular structure.

## Goal

Carsten's idea is:

- vary the horizontal and/or vertical interaction angle at the undulator
- use the two mirror pair to keep the same spatial point in the interaction region
- record `P1` first-harmonic response during that scan
- eventually reproduce an angle/overlap map similar in spirit to **Figure 7 in `see Fig07 - TUP70.pdf`**
- later use the same framework to search for the best overlap / maximum modulation condition

This is meant to improve overlap finding and to make the effect of interaction angle explicit instead of changing many things at once.

## Geometry used

Current values from the supervisor note and legacy calibration:

- mirror separation: `2285 mm`
- mirror 2 to undulator center: `6010 mm`
- horizontal motor step scale: `2.75 µrad / step`
- vertical motor step scale: `1.89 µrad / step`

The old control scripts already encode the central transform:

- desired offset + desired angle at the undulator
- convert to mirror 1 / mirror 2 angles
- convert angle changes into motor steps

The new implementation keeps that logic, but isolates it into `laser_mirrors_app/geometry.py`.

## What is implemented now

- new standalone GUI launcher: `laser_mirrors_gui.py`
- modular package:
  - `laser_mirrors_app/config.py`
  - `laser_mirrors_app/geometry.py`
  - `laser_mirrors_app/hardware.py`
  - `laser_mirrors_app/scan.py`
  - `laser_mirrors_app/gui.py`
- safe mode:
  - no real motor moves
  - simulated P1 map
  - useful for laptop development and UI debugging
- legacy mirror-state integration:
  - reads and writes the old `MirrorControl/mirror_state.ini` style file
  - restores both:
    - `last_known` actual mirror state
    - `last_set` last requested GUI setpoint
  - saves state on scan completion, explicit button press, and clean app close
- live `P1` runtime panel:
  - instantaneous readback
  - rolling average
  - rolling standard deviation
  - sample count
  - timestamp of last successful update
- debug logging:
  - every planned move is printed before being sent
  - command batches are saved during scans
  - raw motor step readbacks are printed on backend connect for debugging offset resets
- live visuals:
  - simple mirror / beam schematic
  - 2D scan map of `P1` vs target angle `(x, y)`
  - running `P1` trace during the scan
  - rolling live `P1`-vs-time trace in the overview page
- manual control:
  - move to the currently requested undulator target immediately
  - direct relative nudge of any mirror axis in steps
  - return to the saved state or the automatic pre-move recovery state
- smarter scan modes:
  - `two_mirror_target`
  - `mirror1_primary`
  - `mirror2_primary`
  - the primary modes interpret the scan center/span as direct mirror-angle scans and solve the other mirror analytically to hold the interaction point
- scan export:
  - unique session directory
  - `config.json`
  - `commands.jsonl`
  - `measurements.csv`

## Important control concept

The UI is written around the variables at the **undulator**, not directly around the mirror motors:

- target offset at undulator: `(offset_x, offset_y)`
- target angle at undulator: `(angle_x, angle_y)`

The program converts those into:

- mirror 1 angle
- mirror 2 angle
- corresponding motor steps

That is the cleanest way to express the actual experiment intent.

## Current limitations

- real control currently assumes the legacy **New Focus Picomotor CmdLib** style backend is available
- the app can fall back to safe mode automatically if hardware connection fails
- no finished automatic optimizer yet
- no direct live EPICS integration for all mirror control variants yet
- the live geometry preview is still schematic, not a metrology-accurate drawing of the real optical table
- the primary-mirror scan modes solve the compensation analytically from the legacy geometry; they do not yet close a live loop on a beam-position or camera signal

## Why offsets need special care

You mentioned that motor offsets reset whenever a motor is started.

That means the operator must be able to:

- enter the current believed undulator offset/angle state
- re-establish the current mirror reference after a restart
- not blindly trust old step counters after power cycling

This is why the GUI has:

- editable startup offset/angle fields
- `Apply as current reference`
- `Save mirror state now`
- manual nudge controls
- `Return to recovery state`
- safe mode and explicit command preview

## Control-room operating model

The new tool now separates three distinct concepts:

1. `last_known`
- what the program believes the actual mirror state currently is
- restored from `mirror_state.ini`
- updated after every scan point and saved again on exit

2. `last_set`
- the last requested undulator offset/angle the operator typed into the UI
- also restored on startup
- useful when the hardware was restarted and the operator wants to resume the previous setpoint

3. raw controller step readback
- queried from the active motor backend on connect
- written to the debug pane
- important because step counters can reset and the physical meaning then has to be re-established by the operator

For control-room deployment, the recommended pattern is:

- start in safe mode first if unsure
- confirm the raw motor readbacks and current believed state
- set or restore the current undulator offset/angle
- press `Apply as current reference`
- only then start real scans

## Feature roadmap

| Feature | Status | Notes |
|---|---|---|
| Safe offline development mode | Implemented | For laptop work and UI debugging |
| Geometry transform: undulator target -> mirror angles | Implemented | Based on legacy calculator |
| Angle scan with logging | Implemented | Grid scan in `(angle_x, angle_y)` |
| Live beam/mirror animation | Basic | Schematic preview, not yet a surveyed mechanical drawing |
| Live P1 color map during scan | Implemented | Canvas-based |
| Debug print of motor commands | Implemented | Command batch logging |
| Real Picomotor backend wrapper | Partial | Loads legacy cmdlib if environment supports it |
| Real EPICS P1 backend | Partial | Optional, user must provide PV |
| Automatic best-point finder | Not yet | Could maximize or minimize depending on objective |
| Smarter compensation mode | Implemented | `mirror1_primary` / `mirror2_primary` analytical hold-point modes |
| Figure-7-style dedicated analysis view | Not yet | Planned follow-up |
| Direct integration with SSMB logger / P1 harmonic toolchain | Not yet | Planned follow-up |
| Legacy mirror-state file compatibility | Implemented | Reads/writes `mirror_state.ini` |
| Continuous P1 averaging panel | Implemented | Rolling live summary on the overview page |
| Clean stop and save on exit | Implemented | Stops scan, saves state/config, then closes |
| Manual direct mirror control | Implemented | Target move, relative nudges, saved-state restore |

## Source material used

Main references in this folder:

- `src_materials/see Fig07 - TUP70.pdf`
- `src_materials/WEPMO02.pdf`
- `src_materials/MirrorControl/`
- `src_materials/laser_setup/`
- `src_materials/mirrorsSpiral.py`

The source materials are intentionally kept under `src_materials/` so the working code path stays uncluttered.

## Run

From this folder:

```bash
python3 laser_mirrors_gui.py --safe-mode
```

Without `--safe-mode`, the app will try to use the configured backend and will fall back to safe mode if connection fails.

## Control-room run instructions

On the control-room machine:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_mirrors_gui.py
```

For a dry run without moving hardware:

```bash
cd /path/to/betagui/laser_mirrors
python3 laser_mirrors_gui.py --safe-mode
```

Important runtime files:

- JSON config:
  - `laser_mirrors_config.json`
- legacy state file:
  - `src_materials/MirrorControl/mirror_state.ini`
- automatic recovery snapshot:
  - `src_materials/MirrorControl/mirror_state.recovery.ini`
- scan output root:
  - system temp dir under `laser_mirror_runs/`

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Next recommended development steps

1. Confirm the real `P1` PV and wire it as the default EPICS backend.
2. Decide whether the control-room motor path should be:
   - legacy Picomotor CmdLib
   - EPICS
   - or a wrapper around another existing local control tool.
3. Add a true optimizer:
   - coarse grid
   - local refinement
   - best-point suggestion
4. Add the dedicated Figure-7-style analysis and export plots.
5. Add optional camera / beam-position readback overlays if a direct overlap proxy becomes available.
