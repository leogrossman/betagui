# Control-Room Quick Start

This is the shortest path for operators and testers.

The files in [control_room/](control_room) are standalone plain Python source.
The GUI file embeds the default response matrices, so it can be copied by
itself into the control room. It still needs the normal runtime Python
packages installed.

## Main Files

- [betagui.py](control_room/betagui.py)
  main GUI entrypoint for the legacy machine profile, write-capable by default
- [betagui_cli.py](control_room/betagui_cli.py)
  minimal write-capable CLI for the core chromaticity measurement
- [runtime_checklist.md](docs/runtime_checklist.md)
  short pre-run validation checklist
- [write_paths.md](docs/write_paths.md)
  explicit list of machine-writing code paths
- [control_room_test_plan.md](docs/control_room_test_plan.md)
  compact on-machine test sequence

## Start Read-Only First

GUI:

```bash
python3 control_room/betagui.py --safe
```

Read-only means:

- live EPICS connection is allowed
- write paths are suppressed
- use this first to confirm startup and PV visibility

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

## Read Before First Live Use

1. [runtime_checklist.md](docs/runtime_checklist.md)
2. [control_room_test_plan.md](docs/control_room_test_plan.md)
3. [feature_parity.md](docs/feature_parity.md)
4. [write_paths.md](docs/write_paths.md)
