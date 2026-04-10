# Control-Room Test Plan

This is the compact first-use plan for testing on the real machine.

## 1. Environment Check

From the repo root:

```bash
python3 --version
python3 scripts/quick_diag.py
python3 control_room/machine_check.py snapshot
python3 control_room/tools/collect_epics_inventory.py
python3 control_room/tools/step_test.py baseline
```

Confirm:

- the correct Python environment is active
- `numpy`, `matplotlib`, `epics`, and `tkinter` import
- EPICS CLI tools are present
- the standalone control-room file can be run directly
- a baseline machine snapshot was saved before any test
- inventory and baseline outputs were saved under `control_room_outputs/`

## 2. PV Sanity Check

Check a few critical PVs before starting the GUI:

```bash
python3 control_room/machine_check.py status
cainfo MCLKHGP:setFrq
cainfo TUNEZRP:measX
cainfo TUNEZRP:measY
cainfo S1P2RP:setCur
```

If dynamic `alpha0` will be used, also check:

```bash
cainfo TUNEZRP:measZ
cainfo PAHRP:setVoltCav
cainfo ERMPCGP:rdRmp
```

## 3. Read-Only GUI Start

Start the clean control-room GUI without writes:

```bash
python3 control_room/betagui.py --safe
```

Confirm:

- the GUI starts
- status messages do not show missing critical PVs
- the embedded default matrix loads
- the live PV readback pane shows sensible values for RF, tune, feedback, and sextupoles

Do not try write-capable actions yet.

## 4. Read-Only CLI Fallback Check

Run the safe CLI preflight:

```bash
python3 control_room/betagui_cli.py --safe
python3 control_room/tools/step_test.py safe-cli
```

## 5. First Write-Capable GUI Test

Only after the read-only check:

```bash
python3 control_room/betagui.py
```

Recommended first actions:

1. save current settings
2. measure `alpha0` only if the required PVs are confirmed
3. run a small chromaticity measurement

Use conservative inputs first.

Confirm afterward:

- RF returns to the starting value
- feedback/orbit states are restored

## 6. CLI Fallback Measurement

If the GUI is unavailable or unstable, use:

```bash
python3 control_room/betagui_cli.py
```

For a manual `alpha0` test:

```bash
python3 control_room/betagui_cli.py --alpha0 0.03
```

Optional save:

```bash
python3 control_room/betagui_cli.py --output xi.txt
```

## 7. Matrix And Correction Workflow

Only after a successful small chromaticity test:

1. measure the response matrix
2. verify the displayed matrix is sensible
3. try small manual `dXi` correction steps
4. verify reset returns to the saved machine state

After each live test block:

```bash
python3 control_room/machine_check.py compare --snapshot SNAPSHOT_JSON
```

## 8. Secondary Scan Workflow

Only after the main workflow is confirmed:

1. open `sext scan`
2. test the polynomial response path first
3. only then test scan-table execution

This path is restored in Python 3, but it contains explicit repairs for broken
legacy code, so it deserves extra operator review.

## Stop Conditions

Stop immediately if:

- critical PVs are missing
- RF does not return to the initial value
- feedback/orbit states do not restore
- the GUI or CLI reports unclear write-path errors

Then fall back to:

- [runtime_checklist.md](runtime_checklist.md)
- [testing_workflow.md](testing_workflow.md)
- [feature_parity.md](feature_parity.md)

If the machine state needs to be restored from the baseline snapshot:

```bash
python3 control_room/machine_check.py restore --snapshot SNAPSHOT_JSON
python3 control_room/machine_check.py restore --snapshot SNAPSHOT_JSON --apply
```

Use the dry run first. Only then use `--apply`.
