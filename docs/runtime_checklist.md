# Runtime Checklist

Use this short checklist before any future real-machine deployment.

## Environment

- Confirm the project uses the intended pyenv environment:
  `python3 --version`
- Confirm required imports:
  `numpy`, `matplotlib`, `epics`, `tkinter`
- Confirm EPICS CLI tools are available:
  `cainfo`, `caget`, `camonitor`, `caput`
- Confirm the standalone control-room file to be deployed is the intended one.

## Read-Only Validation

- Capture a baseline snapshot first:
  `python3 control_room/machine_check.py snapshot`
- Capture a machine inventory:
  `python3 control_room/tools/collect_epics_inventory.py`
- Start with:
  `python3 control_room/betagui.py --safe`
- Confirm the GUI starts without import or display errors.
- Confirm the status panel does not report missing critical PVs.
- Confirm expected legacy PVs are reachable with `cainfo`.
- Confirm a new session directory appears under `./.betagui_local/logs/`.
- Confirm `session.log` and `events.jsonl` are being written.
- Confirm the machine snapshot file path is saved somewhere convenient for later
  compare/restore.
- Confirm `control_room_outputs/` is receiving snapshot/inventory/test files
  that can be pushed back later.

## PV Sanity

- RF PV is present and readable.
- tune X and tune Y PVs are present and readable.
- synchrotron-tune PV is present if dynamic `alpha0` will be used.
- sextupole family PVs are present and readable.
- feedback and orbit-control PVs are present if legacy write behavior is expected.
- cavity-voltage and beam-energy PVs are present if dynamic `alpha0` will be used.

## Safety

- Review [write_paths.md](write_paths.md).
- Confirm saved initial settings are sensible before testing reset behavior.
- Confirm operator intent before switching from `--safe` to the default
  write-capable run.
- Preserve the session log directory from each test run for later analysis.

## First Live Functional Checks

- Measure `alpha0` only if the required PVs are confirmed.
- Run a small chromaticity measurement with conservative inputs.
- Confirm a raw measurement payload appears under `.betagui_local/logs/.../measurements/`.
- Verify RF returns to the initial value afterward.
- Verify feedback/orbit states are restored afterward.
- Only then consider matrix measurement or manual correction buttons.

## If Anything Is Unclear

- Stop and fall back to mock mode or the digital twin.
- Do not guess at missing PV mappings or machine-state semantics.
