# SSMB PoP-II Bumper Diagnostics Viewer

Files generated:

- `ssmb_popii_bumper_diagnostics_deploy.plt`: CS-Studio Data Browser viewer.
- This note explains the traces and the calculations.

## Time window and live buffer

The viewer is set to:

- display window: `-4 hours` to `now`;
- update period: `1 s`;
- scroll step: `30 s`;
- live ring buffer: `50000` samples per trace.

This makes the viewer useful for long bumper scans. If a PV is only archived for 10 minutes in the archiver, the `.plt` file cannot change the archiver retention. The larger `ring_size` only helps for live data while the Data Browser is open.

## U125 BPM geometry used

The viewer uses the positions from the uploaded lattice files:

| Element | s [m] | role |
|---|---:|---|
| `BPMZ3L2RP` | 8.1872 | first upstream BPM |
| `BPMZ4L2RP` | 9.0466 | second upstream BPM |
| `U125` | 12.0000 | undulator marker |
| `BPMZ5L2RP` | 14.9534 | first downstream BPM |
| `BPMZ6L2RP` | 15.8540 | second downstream BPM |

Distances:

```text
BPM4 - BPM3 = 0.8594 m
BPM6 - BPM5 = 0.9006 m
U125 - BPM4 = +2.9534 m
U125 - BPM5 = -2.9534 m
```

Assumption: BPM readbacks are in mm. Therefore `(x2-x1)/L[m]` has unit mm/m = mrad.

## Calculated angle traces

Horizontal upstream angle:

```text
(pv("BPMZ4L2RP:rdX") - pv("BPMZ3L2RP:rdX")) / 0.8594
```

Horizontal downstream angle:

```text
(pv("BPMZ6L2RP:rdX") - pv("BPMZ5L2RP:rdX")) / 0.9006
```

Horizontal mismatch:

```text
x'_downstream - x'_upstream
```

Same formulas are included for vertical.

### Interpretation thresholds

For SSMB, worry if the bumper changes these by roughly:

| Quantity | visible | serious |
|---|---:|---:|
| U125 orbit center | 0.05--0.1 mm | >0.2 mm |
| U125 angle | 20--50 µrad | >50 µrad |
| U125 angle mismatch | 20--50 µrad | >50 µrad |
| tune shift | 1e-3 | >3e-3--5e-3 |
| QPD/profile size change | 1--3% | >3--5% |
| coherent signal change | 10--30% | >50% |

## Extrapolated U125 center traces

From the upstream BPM pair:

```text
x_U125_up = x_BPM4 + x'_up * (12.0000 - 9.0466)
```

From the downstream BPM pair:

```text
x_U125_down = x_BPM5 + x'_down * (12.0000 - 14.9534)
```

The viewer plots:

- `U125 center X from upstream BPM3/4`
- `U125 center X from downstream BPM5/6`
- `U125 center X consistency downstream-upstream`

Same for `Y`.

The consistency signal is useful because if upstream and downstream extrapolations disagree during a bumper scan, the line through the undulator is changing, or the straight-line approximation is insufficient.

## Bumper-current diagnostics

Four steerer currents are included:

```text
HS1P2K3RP:setCur
HS3P1L4RP:setCur
HS3P2L4RP:setCur
HS1P1K1RP:setCur
```

The viewer adds:

```text
Σ|I| = abs(I1)+abs(I2)+abs(I3)+abs(I4)
```

and the path-length proxy

```text
ΣI² = I1²+I2²+I3²+I4²
```

This is not a calibrated path-length signal, but because a geometric path-length bump scales approximately as

```text
ΔC ∝ θ² ∝ I²
```

`ΣI²` is useful for correlations with coherent radiation, beam size, tune, and U125 trajectory.

## QPD/profile diagnostics

The viewer includes:

```text
QPD01ZL2RP:rdSigmaXav/Yav  # L2 / near U125
QPD00ZL4RP:rdSigmaXav/Yav  # L4 / RF-cavity region
```

Calculated traces:

```text
Δ sigma X = sigmaX_L2 - sigmaX_L4
Δ sigma Y = sigmaY_L2 - sigmaY_L4
```

Interpretation:

- size change mainly in dispersive regions: likely dispersion/energy-spread related;
- size change also in non-dispersive region: beta beating, emittance, or coupling;
- profile change correlated with bumper current or `ΣI²`: possible bumper optics effect.

## Tune diagnostics

Raw tune PVs:

```text
TUNEZRP:measX
TUNEZRP:measY
TUNEZRP:measZ
```

Calculated shifts use the model numbers from the uploaded low-emittance briefing:

```text
Δνx = TUNEZRP:measX - 0.1779253
Δνy = TUNEZRP:measY - 0.2200174
Δνs = TUNEZRP:measZ - 0.00073025
```

If your actual working point is different, edit these constants in the `.plt` file. A bumper-correlated tune shift at the `1e-3` level is already worth attention; several `1e-3` is significant for SSMB/TLC.

## Most useful correlation plots

Use the same viewer and toggle visible traces to inspect:

1. coherent signal vs. `ΣI²`;
2. coherent signal vs. U125 center X/Y;
3. coherent signal vs. U125 angle mismatch;
4. coherent signal vs. QPD L2 sigma X/Y;
5. coherent signal vs. tune shifts;
6. U125 angle mismatch vs. `ΣI²`;
7. QPD sigma changes vs. `ΣI²`.

The strongest warning signature is:

```text
bumper current ↑ → tune shift or U125 angle/center shift → QPD/profile change → coherent signal changes
```

This points to bumper-induced optics/TLC effects rather than only intentional path-length control.

## Caveat: straight-line angle approximation

The two-BPM angle estimates assume a drift-like relation between the BPM pair. There are magnets near the BPMs, so this is a diagnostic proxy, not a true lattice reconstruction. For precise analysis, use the transfer matrix:

```text
x2 = M11*x1 + M12*x1'
```

so that

```text
x1' = (x2 - M11*x1)/M12
```

The current viewer is still useful for online scans because it gives a stable, intuitive bumper-correlated trajectory proxy.
