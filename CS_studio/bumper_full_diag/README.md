# SSMB PoP-II CS-Studio diagnostic mini repo

This folder splits the previously cluttered Data Browser view into focused `.plt` files.  Use `00_overview_core.plt` during scans and open the focused views only when something moves.

## Files

| File | Purpose |
|---|---|
| `00_overview_core.plt` | Compact must-watch overview: coherent signal, bumper proxies, U125 center/angle mismatch, tune shifts, QPD relative size differences, current. |
| `01_u125_orbit_angles.plt` | Detailed U125 trajectory reconstruction using BPMZ3L2RP, BPMZ4L2RP before U125 and BPMZ5L2RP, BPMZ6L2RP after U125. |
| `02_bumper_steerers.plt` | Four steerer currents and bumper strength proxies correlated with U125 trajectory and coherent signal. |
| `03_qpd_profiles.plt` | Beam-size/profile monitor diagnostics for dispersive/non-dispersive size changes. |
| `04_tunes_rf_machine.plt` | Tune, RF, cavity voltage and orbit-feedback/machine state checks. |
| `05_bpm_raw_l2_l4.plt` | Raw BPM orbit view for the U125 L2 region and L4 high-dispersion proxy region. |
| `06_scope_signal_laser.plt` | Scope/coherent signal and laser/trigger/averaging diagnostics. |

## Geometry used for U125 reconstruction

From the lattice files:

```text
BPMZ3L2RP: s = 8.1872 m
BPMZ4L2RP: s = 9.0466 m
U125:      s = 12.0000 m
BPMZ5L2RP: s = 14.9534 m
BPMZ6L2RP: s = 15.8540 m
```

Thus

```text
L34 = 0.8594 m
L56 = 0.9006 m
U125 - BPM4 = 2.9534 m
U125 - BPM5 = -2.9534 m
```

If BPM readbacks are in mm and distances are in m, the calculated slope is in mm/m = mrad.

## Important calculated traces

Upstream angle:

```text
(pv("BPMZ4L2RP:rdX") - pv("BPMZ3L2RP:rdX")) / 0.8594
```

Downstream angle:

```text
(pv("BPMZ6L2RP:rdX") - pv("BPMZ5L2RP:rdX")) / 0.9006
```

Angle mismatch:

```text
xprime_downstream - xprime_upstream
```

U125 center from upstream extrapolation:

```text
BPM4_X + xprime_upstream * 2.9534
```

U125 center from downstream extrapolation:

```text
BPM5_X + xprime_downstream * (-2.9534)
```

Bumper proxies:

```text
Σ|I| = abs(I1)+abs(I2)+abs(I3)+abs(I4)
ΣI² = I1²+I2²+I3²+I4²
ΣI  = I1+I2+I3+I4
```

## Recommended workflow

1. Open `00_overview_core.plt`.
2. During a bumper scan, watch coherent signal, ΣI², U125 center, U125 angle mismatch, and tune shifts.
3. If coherent signal changes, open:
   - `01_u125_orbit_angles.plt` if U125 trajectory changed,
   - `02_bumper_steerers.plt` if a steerer/current issue is suspected,
   - `03_qpd_profiles.plt` if beam size changes,
   - `04_tunes_rf_machine.plt` if tunes or machine settings drifted,
   - `05_bpm_raw_l2_l4.plt` if the BPM pattern suggests orbit/dispersion leakage.

## Practical SSMB warning thresholds

These are order-of-magnitude scan flags, not interlock limits.

| Indicator | Visible | Serious |
|---|---:|---:|
| U125 center motion | 0.05--0.1 mm | >0.2 mm |
| U125 angle mismatch | 0.02--0.05 mrad | >0.05 mrad |
| Tune shift | 1e-3 | >3e-3 to 5e-3 |
| QPD relative size change | 1--3 % | >3--5 % |
| Coherent-signal systematic loss | 10--30 % | >50 % |
| Bumper orbit through sextupoles | ~0.5 mm | >1 mm |

## Notes on y-ranges

The y-ranges are deliberately tighter than the old all-in-one file.  If a trace clips, that is useful during commissioning: it means that channel should be checked directly in the focused panel.  For long overnight checks, switch selected axes back to autoscale inside CS-Studio if needed.

## Caveat

The BPM-angle reconstruction is a drift-like two-BPM estimate.  If there are significant quadrupoles or nonlinear elements between the BPMs, replace it later with a transfer-matrix reconstruction:

```text
xprime1 = (x2 - M11*x1)/M12
```

For scan diagnostics, the simple two-BPM estimate is still very useful because it provides a reproducible local trajectory proxy.
