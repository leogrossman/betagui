# Motor Controller Notes

This note collects the current working understanding of the laser-mirror motors,
their EPICS interface, and the controller-safety assumptions used by the
`laser_mirrors` GUI.

## Confirmed EPICS motor records

The current tool uses these four EPICS motor bases:

- `MNF1C1L2RP` — mirror 1 vertical
- `MNF1C2L2RP` — mirror 1 horizontal
- `MNF2C1L2RP` — mirror 2 vertical
- `MNF2C2L2RP` — mirror 2 horizontal

The GUI currently relies on the standard motor-record fields:

- `.VAL`
- `.RBV`
- `.DMOV`
- `.MOVN`
- `.STOP`
- `.STAT`
- `.SEVR`
- `.HLM`
- `.LLM`
- `.VELO`
- `.ACCL`

## Important legacy clue: closed-loop controller / encoder

The legacy source:

- `src_materials/MirrorControl/MirrorControlCmdLib.py`

contains explicit handling for controller serial numbers containing `8743`, with
comments indicating:

- controller type `8743`
- closed-loop encoder support
- closed-loop units set to encoder counts

That means the historical mirror-control stack appears to have known about
controller-side closed-loop encoder behavior.

## What the current EPICS GUI is using today

The current `laser_mirrors` GUI does **not** yet talk to a separate encoder PV
family directly. Instead it relies on the EPICS motor-record interface and
treats these as the operational truth:

- `.RBV` for achieved position
- `.DMOV` for done-moving status
- `.MOVN` for moving state

This is the conservative control-room assumption until a separate encoder PV
mapping is confirmed.

## Why moves are now intentionally serialized

To reduce controller / IOC stress, the tool now does the following:

1. validate every requested target against:
   - max delta from reference
   - max absolute move window
   - HLM / LLM
   - current alarm severity
2. ramp each motor in small `.VAL` layers
3. move **one motor at a time**
4. after each ramp layer:
   - wait for `.DMOV = 1`
   - inspect `.RBV`, `.VAL`, `.MOVN`, `.STAT`, `.SEVR`
   - wait extra settle time
5. only then proceed to the next ramp layer or next motor

So even when a scan point logically changes multiple motors, the actual command
path is serialized and checked after each layer.

## Failure behavior

If a motor does not behave as expected:

- the move raises a warning/error
- the GUI stays alive
- the scan worker stops gracefully
- partial session data is still written
- the operator gets a warning popup

This is intentionally different from “keep going no matter what”.

## What still needs confirmation in the control room

- whether `.RBV` reflects the true encoder-verified position in all cases
- whether `.DMOV = 1` is sufficient to trust optical settling
- whether `.VELO` / `.ACCL` are meaningful and stable on these records
- the exact point where controller overload/crash starts happening
- whether there is a separate encoder PV family that should be monitored in the GUI

## Practical commissioning advice

First tests should be small and gentle:

1. run read-only first
2. inspect `.RBV`, `.DMOV`, `.MOVN`, `.STAT`, `.SEVR`
3. capture reference
4. preview commands
5. only then enable write mode
6. use small 1D scans before any larger 2D raster

If the controller behaves unexpectedly:

- stop the scan
- inspect the debug log
- inspect the saved `commands.jsonl`
- inspect the saved `last_move_plan.json`
- consider recapturing the current RBV as a new reference before any recovery move
