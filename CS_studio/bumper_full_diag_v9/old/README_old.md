
# SSMB PoP-II CS-Studio diagnostics repo v9

## Open order

1. `04_raw_sanity_no_formulas_10min.plt`  
   Confirms the raw PV names connect and archive/live data are visible.
2. `99_formula_test_open_first.plt`  
   Minimal formula test using only BPMZ3/BPMZ4. If this does not work, the issue is formula syntax support or exact PV names, not the dashboard.
3. `00_core_overview_10min.plt`  
   Compact operational view.
4. `01_u125_bpm_angle_detail_30min.plt`  
   Detailed U125 BPM X/Y position and angle proxies.
5. `02_bumper_steerers_akc_machine_30min.plt`  
   Bumper/steerer combinations and AKC/MNF/Q1/U125 machine knobs.
6. `03_signal_qpd_tune_rf_30min.plt`  
   Signal, QPD/profile sizes, tunes, RF, cavity.

## Formula implementation

This version uses the formula XML style copied from your working example:

```xml
<formula>
  <display_name>...</display_name>
  <visible>true</visible>
  <name>...</name>
  <axis>...</axis>
  <formula>x4-x3</formula>
  <input>
    <pv>BPMZ3L2RP:rdX</pv>
    <name>x3</name>
  </input>
  <input>
    <pv>BPMZ4L2RP:rdX</pv>
    <name>x4</name>
  </input>
</formula>
```

No `=...` pseudo-PV names and no `pv("...")` calls are used for derived traces.

Raw input PVs are also included as hidden `dep ...` traces so CS-Studio logs/retrieves them.

## U125 BPM map

| BPM | Role | Color in detail plot |
|---|---|---|
| `BPMZ3L2RP` | before U125, upstream BPM 1 | blue/cyan |
| `BPMZ4L2RP` | before U125, upstream BPM 2 | green/purple |
| `BPMZ5L2RP` | after U125, downstream BPM 1 | orange/brown |
| `BPMZ6L2RP` | after U125, downstream BPM 2 | red/pink |

Longitudinal distances used:

- `L34 = 0.8594 m`
- `L56 = 0.9006 m`

Typical horizontal baselines used for centered X plots:

- BPM3: `-0.07 mm`
- BPM4: `-0.19 mm`
- BPM5: `-0.76 mm`
- BPM6: `-0.16 mm`

## Core view trace decoding

`00_core_overview_10min.plt` uses a stacked axis. Labels include the offset and scaling:

| Color | Trace | Meaning |
|---|---|---|
| black | coherent signal avg h1p1 | SSMB signal / scope amplitude |
| blue | `1.0 + 20*mean dX` | mean centered U125 horizontal orbit. 1 vertical unit = 0.05 mm. |
| green | `2.4 + 5*dXangle upstream` | BPM3->BPM4 X angle change. 1 vertical unit = 0.2 mrad. |
| orange | `3.8 + 5*dXangle downstream` | BPM5->BPM6 X angle change. |
| red | `5.2 + 5*dXangle mismatch` | downstream minus upstream X angle change. |
| purple | `6.6 + 5*Yangle upstream` | BPM3->BPM4 Y angle proxy. |
| brown | `8.0 + 5*Yangle downstream` | BPM5->BPM6 Y angle proxy. |
| magenta | `9.4 + 5*Yangle mismatch` | downstream minus upstream Y angle. |
| cyan | `10.7 + 0.02*sum I^2` | quadratic bumper strength proxy. |

## Important thresholds

Worry for SSMB if you see:

- undulator orbit change: `> 0.1 mm`
- U125 angle change or mismatch: `> 0.05 mrad = 50 urad`
- tune shift: `> 1e-3` visible, `> 5e-3` serious
- coherent signal systematic loss: `> 10-30%` visible, `> 50%` serious
- profile size change in dispersive region: `> 3%` suspicious

## Why the focus is angle and dispersion proxies

The bumper path-length change itself is intentional. The danger is that a mm-scale orbit bump and sub-mrad steerer kicks can produce dispersion leakage and sextupole feed-down. This can create transverse-longitudinal coupling (TLC), reducing coherent power as

```math
P/P_0 \approx \exp[-(k_L\sigma_z)^2].
```

For 1064 nm, longitudinal smearing of 100--200 nm is already a large effect.
