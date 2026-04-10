# Control-Room Quick Start

This is the shortest path for operators and testers.

## Main Files

- [betagui.py](control_room/betagui.py)
  main GUI entrypoint for the legacy machine profile, write-capable by default
- [betagui_safe.py](control_room/betagui_safe.py)
  read-only GUI preflight launcher
- [betagui_cli.py](control_room/betagui_cli.py)
  minimal write-capable CLI for the core chromaticity measurement
- [betagui_cli_safe.py](control_room/betagui_cli_safe.py)
  read-only CLI preflight
- [runtime_checklist.md](docs/runtime_checklist.md)
  short pre-run validation checklist
- [write_paths.md](docs/write_paths.md)
  explicit list of machine-writing code paths
- [control_room_test_plan.md](docs/control_room_test_plan.md)
  compact on-machine test sequence

## Start Read-Only First

GUI:

```bash
python3 control_room/betagui_safe.py
```

Read-only means:

- live EPICS connection is allowed
- write paths are suppressed
- use this first to confirm startup and PV visibility

CLI fallback:

```bash
python3 control_room/betagui_cli_safe.py
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
