# Control-Room Deployment Guide

## Start read-only

```bash
python3 run_gui.py
```

Confirm:

- all four motor records connect
- `.RTYP = motor`
- `.EGU = steps`
- `.SEVR = NO_ALARM`
- `.DMOV = 1`

## Run diagnostics

In the Overview tab, click:

```text
Full motor diagnostics
Export diagnostics
```

Save the TXT/JSON output with the run log.

## Select signal source

Use the Signal dropdown:

```text
simulated_p1
p1_h1p1_raw
p1_h1p2_raw
p1_h1p3_raw
p1_h1p1_avg
qpd00_sigma_x
qpd00_sigma_y
qpd01_sigma_x
qpd01_sigma_y
```

Then click `Use preset` or manually enter a PV and click `Connect`.

The live trace and all 2D maps plot the selected signal.

## Enable real writes

```bash
python3 run_gui.py --write-mode
```

Recommended first settings:

```text
Max steps per put: 5 to 10
Delay between puts: 0.5 to 1.0 s
Settle after DMOV: 0.5 to 2.0 s
Max delta from reference: small, e.g. 50 steps
```

## Before a scan

1. Capture current RBV as reference.
2. Preview scan.
3. Start scan.
4. Read the preflight popup carefully.
5. Only press Approve if all `.VAL` targets and ramp layers are sensible.

## Stop behavior

Use `Request stop after point` for normal stopping.

Use `STOP all` only as a hard stop. If the controller crashes when STOP is pressed, avoid using STOP from the scan tab and diagnose IOC/driver behavior with controls staff.
