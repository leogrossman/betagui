# SSMB PoP-II CS-Studio diagnostics repo v4

This version is designed to fix the previous issue where formula traces did not show because their input PVs were not present in the trace property list. In every formula-based `.plt`, all PVs used by formulas are explicitly included as hidden dependency traces with display names starting with `dep:`.

## Files

1. `00_core_overview_10min.plt`  
   Compact operator dashboard. Shows coherent signal plus stacked centered diagnostics: mean U125 BPM X motion, upstream/downstream X angle proxy changes, angle-mismatch change, bumper ΣI² proxy, and tune shifts.

2. `01_u125_orbit_angle_detail_30min.plt`  
   Focused U125 orbit/angle view. Shows centered X deviations for BPMZ3/4/5/6 and before/after angle proxies.

3. `02_bumper_signal_machine_30min.plt`  
   Steerer currents, bumper path-length proxy, tune shifts, and coherent signal.

4. `03_qpd_profiles_signal_30min.plt`  
   QPD profile sizes and coherent signal.

5. `04_raw_sanity_check_no_formulas_10min.plt`  
   No formulas. Open this first if a formula plot shows no traces; it verifies raw PV connectivity.

## U125 BPM geometry used

- BPMZ3L2RP before U125: typical X ≈ -0.07 mm
- BPMZ4L2RP before U125: typical X ≈ -0.19 mm
- U125 center: s = 12.0000 m
- BPMZ5L2RP after U125: typical X ≈ -0.76 mm
- BPMZ6L2RP after U125: typical X ≈ -0.16 mm

Distances:

```text
L34 = 0.8594 m
L56 = 0.9006 m
```

The angle proxies use BPM differences in mm divided by distances in m, so the result is mrad:

```text
x'_up  = (BPM4_X - BPM3_X) / L34
x'_down = (BPM6_X - BPM5_X) / L56
```

Because these are not necessarily pure drifts, treat them as reproducible *orbit-angle proxies*, not exact physical angles unless transfer matrices are applied.

## Centering and scaling

The X BPM traces in `01_u125_orbit_angle_detail_30min.plt` are baseline-subtracted using the typical values you gave:

```text
BPM3: -0.07 mm
BPM4: -0.19 mm
BPM5: -0.76 mm
BPM6: -0.16 mm
```

This avoids a huge y-range caused by different absolute BPM offsets. The visible axis is ±0.25 mm, which should be much more useful for scan work.

## History / visible window

All PVs have a large live buffer:

```text
ring_size = 259200
```

The visible time windows are intentionally short:

- core/raw: last 10 minutes
- details: last 30 minutes

You can pan backward if the Data Browser has buffered or archived values, but the default view stays readable.

## Thresholds to watch

Worry if bumper scans produce:

```text
U125 centered BPM motion          > 0.1 mm visible, >0.3 mm serious
Angle-proxy change                > 0.05 mrad visible
Angle-mismatch change             > 0.05 mrad visible
Tune shift                        > 0.001 visible, >0.003-0.005 serious
Coherent signal loss              > normal shot-to-shot fluctuation
```

## If formulas still do not show

1. Open `04_raw_sanity_check_no_formulas_10min.plt` first.
2. Confirm raw BPM, steerer, and signal PVs connect.
3. In a formula plot, open Trace Properties and confirm that the hidden `dep:` PVs are listed.
4. If your CS-Studio build uses a different formula syntax, keep the raw file for online scanning and recreate formulas in the Data Browser GUI using the same expressions from this README.
