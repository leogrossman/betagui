# Control-Room Quick Start

This is the shortest path for operators and testers.

The GUI file embeds the default response matrices, so it can be copied by
itself into the control room. It still needs the normal runtime Python
packages installed.

## Main Files

- [betagui.py](control_room/betagui.py)
  main GUI entrypoint for the legacy machine profile, write-capable by default
- [betagui_cli.py](control_room/betagui_cli.py)
  minimal write-capable CLI for the core chromaticity measurement
- [machine_check.py](control_room/machine_check.py)
  baseline snapshot, compare, and restore helper
- [tools/collect_epics_inventory.py](control_room/tools/collect_epics_inventory.py)
  environment, command, and PV inventory collector
- [tools/step_test.py](control_room/tools/step_test.py)
  small step-by-step read-only runner
- [runtime_checklist.md](docs/runtime_checklist.md)
  short pre-run validation checklist
- [control_room_git_setup.md](docs/control_room_git_setup.md)
  copy-paste Git and deploy-key setup for the control-room machine
- [write_paths.md](docs/write_paths.md)
  explicit list of machine-writing code paths
- [control_room_test_plan.md](docs/control_room_test_plan.md)
  compact on-machine test sequence

## Start Read-Only First

Before anything else, capture a baseline snapshot:

```bash
python3 control_room/machine_check.py snapshot
python3 control_room/tools/collect_epics_inventory.py
python3 control_room/tools/step_test.py baseline
```

GUI:

```bash
python3 control_room/betagui.py --safe
```

Read-only means:

- live EPICS connection is allowed
- write paths are suppressed
- use this first to confirm startup and PV visibility
- the right-hand live PV readback pane should show current machine values
- runtime logs are still written under `./betagui_logs/`

CLI fallback:

```bash
python3 control_room/betagui_cli.py --safe
```

## Enable Live Writes Only When Intended

GUI:

```bash
python3 control_room/betagui.py
```

CLI:

```bash
python3 control_room/betagui_cli.py
```

## Logs

Both control-room entrypoints write a session log directory by default under
`./betagui_logs/`.

Each session contains:

- `session.log`: human-readable runtime log
- `events.jsonl`: structured PV/event log
- `measurements/`: raw measurement payloads with RF points, tune samples, and
  calculated results

Commit-friendly machine outputs are written under `./control_room_outputs/`.
That directory is intended to be pushed back from the control-room machine so
the results can be reviewed elsewhere.

## Read Before First Live Use

1. [runtime_checklist.md](docs/runtime_checklist.md)
2. [control_room_test_plan.md](docs/control_room_test_plan.md)
3. [feature_parity.md](docs/feature_parity.md)
4. [write_paths.md](docs/write_paths.md)
