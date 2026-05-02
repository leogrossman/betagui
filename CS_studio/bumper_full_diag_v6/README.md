
# SSMB PoP-II CS-Studio bumper diagnostics repo v6

This repo contains a cleaned set of CS-Studio/Data Browser `.plt` files for the Phase-II SSMB four-steerer bumper investigation.

## Open order

1. `05_raw_sanity_check_10min.plt` — confirm that raw PVs connect and update.
2. `00_core_overview_10min.plt` — compact live scan dashboard.
3. `01_u125_orbit_angles_30min.plt` — detailed U125 BPM/angle view, now with **X and Y** angles.
4. `02_bumper_steerers_akc_30min.plt` — bumper current combinations and AKC loop PVs.
5. `03_signal_qpd_machine_30min.plt` — coherent signal, QPD/profile monitors, RF/machine context.
6. `04_tune_rf_focused_30min.plt` — tune/RF/longitudinal focused diagnostics.

Visible windows are short (`10 min` or `30 min`) so the display is readable.  The hidden dependency PVs use a large live ring buffer (`ring_size = 259200`) so CS-Studio can keep much longer live history while only showing the recent window.

## Color code

| Color | Meaning |
|---|---|
| blue / cyan | coherent signal, scope, downstream/y-after optional |
| orange / red | horizontal U125 BPM/angle diagnostics |
| green / dark green | vertical U125 BPM/angle diagnostics |
| purple / brown | mismatch, bumper proxy, current balance |
| black / gray | tune, common mode, machine context |
| pink / olive | AKC loop/status PVs |

## U125 BPM geometry used

| BPM | Position `s` [m] | Role | PV X/Y |
|---|---:|---|---|
| BPMZ3L2RP | 8.1872 | upstream 1 | `BPMZ3L2RP:rdX`, `BPMZ3L2RP:rdY` |
| BPMZ4L2RP | 9.0466 | upstream 2 | `BPMZ4L2RP:rdX`, `BPMZ4L2RP:rdY` |
| U125 marker | 12.0000 | undulator center marker | — |
| BPMZ5L2RP | 14.9534 | downstream 1 | `BPMZ5L2RP:rdX`, `BPMZ5L2RP:rdY` |
| BPMZ6L2RP | 15.8540 | downstream 2 | `BPMZ6L2RP:rdX`, `BPMZ6L2RP:rdY` |

Distances:

```text
L34 = 0.8594 m
L56 = 0.9006 m
```

Given typical X values from the machine snapshot:

```text
BPM3 X ≈ -0.07 mm
BPM4 X ≈ -0.19 mm
BPM5 X ≈ -0.76 mm
BPM6 X ≈ -0.16 mm
```

The X views subtract these reference values so that you see deviations instead of absolute offsets.

## Formula naming convention

The labels like `1.0 + ...`, `2.2 + ...` are intentional vertical offsets for stacked plots.  Read them as follows:

| Display label | Actual physical quantity |
|---|---|
| `1.0 + 2·mean ΔX U125 BPMs` | common horizontal BPM movement around U125, scaled by 2 and shifted to y=1 |
| `2.2 + 5·Δx′ upstream` | upstream horizontal angle change, scaled by 5 and shifted to y=2.2 |
| `3.4 + 5·Δx′ downstream` | downstream horizontal angle change, scaled by 5 and shifted to y=3.4 |
| `4.6 + 5·Δ(x′dn−x′up)` | horizontal angle mismatch change, scaled by 5 and shifted to y=4.6 |
| `5.8 + 2·y′ upstream` | upstream vertical angle proxy, scaled by 2 and shifted to y=5.8 |
| `7.0 + 2·y′ downstream` | downstream vertical angle proxy, scaled by 2 and shifted to y=7.0 |
| `8.2 + 2·(y′dn−y′up)` | vertical angle mismatch proxy, scaled by 2 and shifted to y=8.2 |
| `9.4 + 0.02·ΣI²` | bumper path-length/current-strength proxy |
| `10.3 + 1000·Δνx` | horizontal tune change in milli-tune units |
| `11.0 + 1000·Δνy` | vertical tune change in milli-tune units |

The vertical offsets are only for visualization; the scaling factors are in the trace labels.

## Why hidden dependency PVs are included

CS-Studio formula traces often do not evaluate or archive correctly unless the input PVs are also in the plot's PV list.  Therefore, every formula-based file contains hidden traces named `dep: PVNAME`.  Do not delete them unless you also remove the formulas that depend on them.

## Important original PVs restored

The repo keeps the important original PVs from your plot, including:

- `AKC05VP`, `AKC06VP`
- `MNF1C1L2RP`, `MNF1C2L2RP`, `MNF2C2L2RP`, `MNF2C1L2RP`
- `U125IL2RP:BasePmGap.A`
- `PAHRP:NRVD:rdVoltCav`, `PAHRP:setVoltCav`
- `MCLKHGP:rdFrq499`, `MCLKHGP:setFrq499`
- `QPD00ZL4RP:*`, `QPD01ZL2RP:*`
- `SCOPE1ZULP:h1p1/h1p2/h1p3:*`
- four bumper steerers: `HS1P2K3RP:setCur`, `HS3P1L4RP:setCur`, `HS3P2L4RP:setCur`, `HS1P1K1RP:setCur`

Some are hidden by default to reduce clutter; enable them in trace properties if needed.
