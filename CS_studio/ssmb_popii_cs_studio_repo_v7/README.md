# SSMB PoP-II CS-Studio diagnostics repo v7

This version is scaled from your exported CS-Studio data (`cs-studiov5.zip`) instead of guessed ranges.

## Open order

1. `04_raw_sanity_check_10min.plt` — confirms raw PV connectivity.
2. `00_compact_dashboard_10min.plt` — main scan dashboard, compact and stacked.
3. `01_u125_orbit_angles_30min.plt` — detailed U125 BPM/angle diagnostics.
4. `02_bumper_steerers_akc_30min.plt` — steerer deviations and AKC/MNF controls.
5. `03_signal_qpd_machine_30min.plt` — signal, beam profile/QPD, RF/cavity/machine state.

All formula input PVs are included as hidden `dep:` traces so CS-Studio has the values available.

## U125 BPM map

| Short label | PV | Position | Color |
|---|---|---|---|
| BPM3 X/Y | `BPMZ3L2RP:rdX/Y` | before U125 | orange/green |
| BPM4 X/Y | `BPMZ4L2RP:rdX/Y` | before U125 | red/dark green |
| BPM5 X/Y | `BPMZ5L2RP:rdX/Y` | after U125 | purple/cyan |
| BPM6 X/Y | `BPMZ6L2RP:rdX/Y` | after U125 | brown/blue |

Geometry used:

- BPM3: 8.1872 m
- BPM4: 9.0466 m
- U125 center: 12.0000 m
- BPM5: 14.9534 m
- BPM6: 15.8540 m

Therefore:

```text
L34 = 0.8594 m
L56 = 0.9006 m
```

## Data-derived baseline values

These are medians from your export and are subtracted in deviation/stacked plots:

| Quantity | baseline |
|---|---:|
| BPM3 X | -0.0694 mm |
| BPM4 X | -0.1746 mm |
| BPM5 X | -0.7574 mm |
| BPM6 X | -0.1691 mm |
| BPM3 Y | -0.1427 mm |
| BPM4 Y | -0.1669 mm |
| BPM5 Y | -0.0526 mm |
| BPM6 Y | -0.0292 mm |

## How to read stacked plots

A trace called `2.5 + 10·Δx′ mismatch [mrad]` means:

```text
plotted_value = 2.5 + 10 * physical_value
```

So a vertical change of 0.1 on that curve corresponds to:

```text
0.1 / 10 = 0.01 mrad = 10 µrad
```

## Why this is more zoomed in

From your exports, typical short-window rms values were only a few micrometres for BPM positions:

- BPM3 X std ≈ 0.0028 mm
- BPM4 X std ≈ 0.0055 mm
- BPM5 X std ≈ 0.0075 mm
- BPM6 X std ≈ 0.0028 mm

So this version plots `10·Δx` or `20·mean ΔX` instead of raw millimetres.

## Important thresholds

Worry if you see sustained changes roughly above:

| Diagnostic | visible | serious |
|---|---:|---:|
| U125 X orbit center | 0.05–0.1 mm | >0.2 mm |
| U125 X/Y angle change | 0.02–0.05 mrad | >0.05–0.1 mrad |
| X angle mismatch | 0.02–0.05 mrad | >0.05 mrad |
| QPD/profile size | 1–3 % | >3–5 % |
| tune shift proxy | ~1e-3 | >3e-3 |
| coherent signal | 10–30 % | >50 % |

## Main files

### `00_compact_dashboard_10min.plt`

Main scan dashboard. It shows coherent signal plus stacked proxies:

- mean U125 X orbit deviation,
- X center mismatch,
- upstream/downstream X angle changes,
- X angle mismatch,
- Y angle mismatch,
- bumper common current deviation,
- tune X/Y proxies.

### `01_u125_orbit_angles_30min.plt`

Detailed orbit/angle view. Uses separate axes for:

- X BPM deviations: `offset + 10 Δx`,
- Y BPM deviations: `offset + 10 Δy`,
- X/Y angle deviations: `offset + 10 Δangle`,
- optional extrapolated U125 center proxies.

### `02_bumper_steerers_akc_30min.plt`

Shows steerer *deviations* rather than raw currents, because the raw currents have different offsets. Formula traces are:

- individual `10000 ΔI`,
- common-mode current change,
- left-right imbalance,
- outer-inner balance,
- quadratic bump strength proxy.

It also includes AKC/MNF original PVs. Some are hidden by default to avoid clutter.

### `03_signal_qpd_machine_30min.plt`

Shows coherent signal, QPD/profile size deviations, and machine context.

### `04_raw_sanity_check_10min.plt`

Raw PVs only. Use this first if formula traces do not appear.
