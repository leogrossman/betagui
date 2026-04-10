# Control-Room Inventory Reference

This directory contains a saved inventory snapshot copied from the control-room
machine on `2026-04-10`.

Purpose:

- reference for which legacy PVs were reachable at that time
- reference for command availability and environment on the machine
- input for later monitor/tool development without guessing machine channels

Files:

- `inventory.json`
- `inventory_summary.txt`

Working copies produced later on the control-room machine should stay under
`control_room/inventory/` or `control_room_outputs/` as local artifacts.

That working directory is intentionally gitignored so normal machine use does
not keep changing the repo.
