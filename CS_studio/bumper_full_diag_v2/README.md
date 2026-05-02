
# SSMB PoP-II CS-Studio Data Browser diagnostics v2

This folder fixes the earlier trace problem by using the original Data Browser XML structure:
`<pvlist><pv>...</pv></pvlist>`.  The previous test files used a non-standard `<pvs>` tag, so CS-Studio could open the file but show no traces in the trace-property panel.

## Time/history settings

All files show a short live window so the plot is readable:

- core and raw fallback: `start = -10 minutes`, `end = now`
- detailed panels: `start = -30 minutes`, `end = now`

Each trace uses `ring_size = 86400`, so after the plot is opened it can retain a long live buffer.  Historical archive retrieval still depends on the IOC/archive setup; the visible screen remains 10--30 min unless you zoom/pan.

## BPM geometry used for U125

| Element | s [m] |
|---|---:|
| BPMZ3L2RP | 8.1872 |
| BPMZ4L2RP | 9.0466 |
| U125 center used | 12.0000 |
| BPMZ5L2RP | 14.9534 |
| BPMZ6L2RP | 15.8540 |

So:

```text
L34 = 0.8594 m
L56 = 0.9006 m
```

If the true optical interaction point is not exactly `s = 12.0000 m`, edit the constants in the formula PV names.

## Files

- `00_core_overview_10min.plt` — only the most important scan indicators.
- `01_u125_horizontal_angles_30min.plt` — horizontal BPMs, upstream/downstream angle, angle mismatch, extrapolated U125 center.
- `02_u125_vertical_angles_30min.plt` — same for vertical.
- `03_bumper_steerers_30min.plt` — four steerer currents plus `Σ|I|` and `ΣI²` bumper proxies.
- `04_qpd_profiles_30min.plt` — L2/L4 QPD sigma X/Y and relative size differences.
- `05_tunes_rf_machine_30min.plt` — tunes, tune shifts, current, optional RF/cavity traces.
- `06_scope_signal_laser_30min.plt` — scope/coherent-signal channels and trigger/laser auxiliary channels.
- `07_raw_u125_bpms_fallback_10min.plt` — raw BPM traces only, no math formulas. Use this first to verify that traces load.

## Formula PVs

The calculated traces use CS-Studio/Phoebus formula-style PV names beginning with `=` and using `pv("...")`.
If your local CS-Studio build does not support formula PVs in Data Browser, the raw panels will still work. In that case create calculated PVs in a Math/Calc widget with these expressions.

### Horizontal angles

```text
x_angle_up_mrad   = (pv("BPMZ4L2RP:rdX") - pv("BPMZ3L2RP:rdX")) / 0.8594
x_angle_down_mrad = (pv("BPMZ6L2RP:rdX") - pv("BPMZ5L2RP:rdX")) / 0.9006
x_angle_mismatch  = x_angle_down_mrad - x_angle_up_mrad
```

BPM units are assumed to be mm, distances in m, therefore mm/m = mrad.

### Vertical angles

```text
y_angle_up_mrad   = (pv("BPMZ4L2RP:rdY") - pv("BPMZ3L2RP:rdY")) / 0.8594
y_angle_down_mrad = (pv("BPMZ6L2RP:rdY") - pv("BPMZ5L2RP:rdY")) / 0.9006
y_angle_mismatch  = y_angle_down_mrad - y_angle_up_mrad
```

### U125 center extrapolation

```text
x_U_from_up   = pv("BPMZ3L2RP:rdX") + x_angle_up_mrad   * 3.8128
x_U_from_down = pv("BPMZ5L2RP:rdX") + x_angle_down_mrad * -2.9534
x_U_avg       = 0.5 * (x_U_from_up + x_U_from_down)
x_U_mismatch  = x_U_from_down - x_U_from_up
```

Same for Y.

### Bumper proxies

```text
sum_abs_I = abs(pv("HS1P2K3RP:setCur")) + abs(pv("HS3P1L4RP:setCur")) + abs(pv("HS1P1K1RP:setCur")) + abs(pv("HS3P2L4RP:setCur"))
sum_I2    = pv("HS1P2K3RP:setCur")^2 + pv("HS3P1L4RP:setCur")^2 + pv("HS1P1K1RP:setCur")^2 + pv("HS3P2L4RP:setCur")^2
```

## Suggested worry thresholds

| Observable | visible | serious |
|---|---:|---:|
| U125 center shift | 0.05--0.10 mm | >0.2 mm |
| U125 angle mismatch | 0.02--0.05 mrad | >0.05 mrad |
| high-dispersion BPM centroid motion | 0.05--0.3 mm | >0.3 mm |
| QPD/profile sigma change | 1--3% | >3--5% |
| tune shift | ~1e-3 | >3e-3--1e-2 |
| coherent signal change | 10--30% | >50% |

## Plot-readout workflow

1. Open `07_raw_u125_bpms_fallback_10min.plt` first. If this shows traces, the basic PV names and XML format are OK.
2. Open `00_core_overview_10min.plt` during scans.
3. If the core plot changes, open the relevant focused panel:
   - U125 angle/center → `01` or `02`
   - corrector-current dependence → `03`
   - beam-size/TLC proxy → `04`
   - tune/feed-down → `05`
   - scope/coherent signal → `06`

## Notes on y-scaling

I intentionally limited each file to mostly two or three visible axes.  This reduces tick clutter.  Some optional traces are present but hidden by default; enable them manually in the trace panel if needed.
