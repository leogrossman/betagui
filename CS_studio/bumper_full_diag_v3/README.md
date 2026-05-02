# SSMB PoP-II CS-Studio diagnostics repo v3

This version is intentionally reduced to **three main `.plt` files** plus a raw sanity-check file.  The goal is to avoid too many tabs and too many y-axis ticks.

## Files

1. `00_compact_dashboard_10min.plt`  
   One stacked dashboard. Most traces are formula traces with vertical offsets. Use this during scans.

2. `01_u125_orbit_angle_30min.plt`  
   Focused U125 diagnostics: center extrapolation and upstream/downstream angle estimates using BPM3/BPM4 before U125 and BPM5/BPM6 after U125.

3. `02_bumper_signal_machine_30min.plt`  
   Bumper currents, coherent signal, tune deviations, and QPD L2-L4 size proxies.

4. `03_raw_sanity_check_10min.plt`  
   Raw PV fallback. Open this first if a formula plot shows no traces or formula traces do not evaluate.

## Important syntax note

Formula traces are written with a leading equals sign, e.g.

```text
=pv("BPMZ4L2RP:rdX")-pv("BPMZ3L2RP:rdX")
```

The raw dependency PVs are included as invisible traces in the formula files. If your CS-Studio version does not evaluate `pv("...")` formulas in Data Browser, use `03_raw_sanity_check_10min.plt` and create the formula channels as local calculated PVs/BOY formula widgets instead.

## Time history

The visible time windows are short:

- compact/raw: last 10 minutes;
- focused/detail: last 30 minutes.

The live ring buffer is set large (`864000`) so live data is not immediately thrown away. Long-term archiving still depends on your archiver, not the `.plt` file.

## U125 BPM geometry

From the lattice files:

```text
BPMZ3L2RP  s =  8.1872 m
BPMZ4L2RP  s =  9.0466 m
U125       s = 12.0000 m
BPMZ5L2RP  s = 14.9534 m
BPMZ6L2RP  s = 15.8540 m
```

Therefore:

```text
L34 = 0.8594 m
L56 = 0.9006 m
U125 - BPM4 = 2.9534 m
U125 - BPM5 = -2.9534 m
```

If BPM readbacks are in mm, then `(x2-x1)/L` is in mm/m = mrad.

## Main calculated quantities

Upstream horizontal angle:

```text
X'_up = (BPM4_X - BPM3_X)/0.8594
```

Downstream horizontal angle:

```text
X'_down = (BPM6_X - BPM5_X)/0.9006
```

Angle mismatch:

```text
ΔX' = X'_down - X'_up
```

U125 center extrapolated from upstream pair:

```text
X_U125_up = BPM4_X + X'_up * 2.9534
```

U125 center extrapolated from downstream pair:

```text
X_U125_down = BPM5_X + X'_down * (-2.9534)
```

Same formulas are used for Y.

## Thresholds to watch

- U125 center motion: `0.1 mm` visible, `0.2 mm` worrying.
- Angle mismatch: `0.05 mrad` visible/worrying.
- Tune shift: `1e-3` visible, `3e-3` serious.
- Dispersive/QPD size proxy changes: `1–3 %` visible, `>5 %` serious.
- Coherent signal: systematic `10–30 %` change is meaningful; `>50 %` loss is serious.

## How to use

1. Open `03_raw_sanity_check_10min.plt` first. Confirm raw traces appear.
2. Open `01_u125_orbit_angle_30min.plt`. Confirm formula traces evaluate.
3. Use `00_compact_dashboard_10min.plt` during live scans.
4. If the compact dashboard is confusing, use `01` and `02` separately.

## Why the stacked dashboard looks shifted

`00_compact_dashboard_10min.plt` intentionally adds offsets:

- `0 + signal ×5`
- `2 + U125 X center`
- `4 + U125 Y center`
- `6 + 10·ΔX'`
- `8 + 10·ΔY'`
- `10 + 0.02·ΣI²`
- `12 + 1000·Δνx`
- `14 + 1000·Δνy`

This lets many diagnostics fit on one y-axis with fewer ticks.
