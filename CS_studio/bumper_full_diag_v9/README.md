# SSMB PoP-II CS-Studio diagnostics repo v9

This repository contains a CS-Studio / Data Browser diagnostic setup for the SSMB PoP-II four-steerer bumper studies at the MLS. The goal is to monitor whether the bumper behaves like a clean path-length actuator, or whether it also perturbs SSMB-relevant optics quantities such as dispersion, trajectory angle, tune, transverse-longitudinal coupling, and coherent radiation power.

The most important operational idea is:

$$
\boxed{\text{The bumper is not just orbit control; it can act as an SSMB optics perturbation.}}
$$

---

## Open order

1. `04_raw_sanity_no_formulas_10min.plt`  
   Confirms the raw PV names connect and archive/live data are visible.

2. `99_formula_test_open_first.plt`  
   Minimal formula test using only BPMZ3/BPMZ4. If this does not work, the issue is formula syntax support or exact PV names, not the dashboard.

3. `00_core_overview_10min.plt`  
   Compact operational view. Use this during scans to see the main correlations.

4. `01_u125_bpm_angle_detail_30min.plt`  
   Detailed U125 BPM $x/y$ position and angle proxies.

5. `02_bumper_steerers_akc_machine_30min.plt`  
   Bumper/steerer combinations and AKC/MNF/Q1/U125 machine knobs.

6. `03_signal_qpd_tune_rf_30min.plt`  
   Signal, QPD/profile sizes, tunes, RF, and cavity diagnostics.

---

## What this dashboard is testing

This is not only an orbit monitor. It is designed to reveal whether the bumper changes SSMB-sensitive lattice quantities:

$$
D_x,\quad D_x',\quad D_y,\quad D_y',\quad H_x,\quad H_y,\quad \nu_x,\quad \nu_y,\quad R_{56},\quad \eta_0.
$$

The coherent radiation can be very sensitive because a longitudinal smearing $\sigma_z$ suppresses the coherent power approximately as

$$
\frac{P}{P_0}\approx \exp\left[-(k_L\sigma_z)^2\right].
$$

For the SSMB laser wavelength

$$
\lambda_L = 1064\,\mathrm{nm},
$$

we have

$$
k_L=\frac{2\pi}{\lambda_L}\approx5.9\times10^6\,\mathrm{m^{-1}}.
$$

This means longitudinal smearing of order $100\text{--}200\,\mathrm{nm}$ is already a large effect.

---

## Formula implementation

This version uses the formula XML style copied from the working CS-Studio example:

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

Raw input PVs are also included as hidden `dep ...` traces so CS-Studio logs/retrieves them. This matters because formula traces only work reliably if the input PVs are available to the plot.

---

## U125 BPM map

| BPM | Role | Typical color family | Typical horizontal baseline |
|---|---|---|---:|
| `BPMZ3L2RP` | before U125, upstream BPM 1 | blue/cyan | $-0.07\,\mathrm{mm}$ |
| `BPMZ4L2RP` | before U125, upstream BPM 2 | green/purple | $-0.19\,\mathrm{mm}$ |
| `BPMZ5L2RP` | after U125, downstream BPM 1 | orange/brown | $-0.76\,\mathrm{mm}$ |
| `BPMZ6L2RP` | after U125, downstream BPM 2 | red/pink | $-0.16\,\mathrm{mm}$ |

Longitudinal distances used in the angle formulas:

$$
L_{34}=0.8594\,\mathrm{m},
\qquad
L_{56}=0.9006\,\mathrm{m}.
$$

With BPM values in $\mathrm{mm}$ and distances in $\mathrm{m}$, the result is directly in $\mathrm{mrad}$ because

$$
1\,\mathrm{mm}/\mathrm{m}=1\,\mathrm{mrad}.
$$

---

## Core view trace decoding

`00_core_overview_10min.plt` uses a stacked display. Labels include the offset and scaling.

| Color | Trace label | Meaning | Scale |
|---|---|---|---|
| black | coherent signal avg h1p1 | SSMB coherent radiation / scope amplitude | direct signal scale |
| blue | `1.0 + 20*mean dX` | mean centered U125 horizontal orbit | $1$ vertical unit $=0.05\,\mathrm{mm}$ |
| green | `2.4 + 5*dXangle upstream` | BPM3$\rightarrow$BPM4 horizontal angle change | $1$ vertical unit $=0.2\,\mathrm{mrad}$ |
| orange | `3.8 + 5*dXangle downstream` | BPM5$\rightarrow$BPM6 horizontal angle change | same |
| red | `5.2 + 5*dXangle mismatch` | downstream minus upstream horizontal angle | same |
| purple | `6.6 + 5*Yangle upstream` | BPM3$\rightarrow$BPM4 vertical angle proxy | same |
| brown | `8.0 + 5*Yangle downstream` | BPM5$\rightarrow$BPM6 vertical angle proxy | same |
| magenta | `9.4 + 5*Yangle mismatch` | downstream minus upstream vertical angle | same |
| cyan | `10.7 + 0.02*sum I^2` | quadratic bumper strength proxy | relative / uncalibrated |

The offsets are only for visual stacking. The physical interpretation comes from the scaling factors.

---

## `01_u125_bpm_angle_detail_30min.plt`

Purpose: detailed trajectory diagnostics around U125.

Main quantities:

$$
x'_{34}=\frac{x_4-x_3}{L_{34}},
\qquad
x'_{56}=\frac{x_6-x_5}{L_{56}},
$$

and

$$
\Delta x'=x'_{56}-x'_{34}.
$$

Similarly,

$$
y'_{34}=\frac{y_4-y_3}{L_{34}},
\qquad
 y'_{56}=\frac{y_6-y_5}{L_{56}},
$$

and

$$
\Delta y'=y'_{56}-y'_{34}.
$$

Interpretation:

| Observation | Likely meaning |
|---|---|
| $x'_{34}$ and $x'_{56}$ change together | global trajectory/bump response |
| $\Delta x'$ changes | through-U125 trajectory distortion |
| $\Delta y'$ changes | vertical trajectory/coupling issue |
| centered BPMs shift but angles do not | mostly position/overlap shift |
| angle changes correlate with coherent signal | possible TLC or laser-overlap sensitivity |

Alarm scale:

$$
|\Delta x'|,\ |\Delta y'| \gtrsim 0.05\,\mathrm{mrad}=50\,\mu\mathrm{rad}.
$$

---

## `02_bumper_steerers_akc_machine_30min.plt`

Purpose: monitor the bumper actuator and relevant machine knobs.

Typical derived bumper proxies:

$$
S_{|I|}=\sum_i |I_i|,
$$

$$
S_{I^2}=\sum_i I_i^2,
$$

where $I_i$ are the four steerer currents.

The quadratic proxy $S_{I^2}$ is useful because geometric path-length increase scales as

$$
\Delta C \approx \frac{1}{2}\int x'(s)^2\,ds,
$$

and the local angle scales approximately with steerer current,

$$
x'\propto\theta_i\propto I_i.
$$

Therefore

$$
\Delta C \propto \sum_i I_i^2
$$

as an operational first-order proxy. This is not an absolute calibrated path length unless calibrated against a model or measurement.

Interpretation:

| Observation | Meaning |
|---|---|
| $S_{I^2}$ changes smoothly during scan | intentional path-length scan proxy |
| current imbalance grows | bump closure or symmetry may be poor |
| steerer changes correlate with tune shift | sextupole feed-down / optics change |
| steerer changes correlate with coherent signal but BPM angles do not | possibly path-length phase effect |
| steerer changes correlate with BPM angles and signal | likely optics/TLC effect |

---

## `03_signal_qpd_tune_rf_30min.plt`

Purpose: monitor final SSMB signal and independent machine/beam-quality indicators.

Important groups:

- coherent signal / scope channels;
- QPD or profile sizes;
- horizontal and vertical tunes;
- RF frequency and cavity voltage;
- AKC/MNF/Q1/U125 machine knobs.

Interpretation:

| Observation | Likely meaning |
|---|---|
| coherent signal loss with stable RF | optics-driven effect likely |
| coherent signal loss with tune shift | sextupole feed-down / beta beating likely |
| profile size changes mostly in dispersive region | dispersion or energy-spread related |
| profile size changes also in non-dispersive region | beta/emittance/coupling effect |
| RF/cavity changes during scan | longitudinal conditions not isolated |

---

## Important thresholds

Worry for SSMB if you see:

| Quantity | Visible | Serious |
|---|---:|---:|
| U125 orbit change | $>0.1\,\mathrm{mm}$ | $>0.2\,\mathrm{mm}$ |
| U125 angle change or mismatch | $>0.05\,\mathrm{mrad}$ | $>0.1\,\mathrm{mrad}$ |
| tune shift | $>10^{-3}$ | $>5\times10^{-3}$ |
| coherent signal systematic loss | $10\text{--}30\%$ | $>50\%$ |
| profile size change in dispersive region | $>3\%$ | $>5\%$ |

---

## Why the focus is angle and dispersion proxies

The bumper path-length change itself is intentional. The danger is that a millimetre-scale orbit bump and sub-mrad steerer kicks can produce dispersion leakage and sextupole feed-down.

A bumper designed to create

$$
\Delta C\sim\lambda_L=1.064\,\mu\mathrm{m}
$$

can naturally require

$$
x\sim1\text{--}3\,\mathrm{mm},
\qquad
\theta\sim0.2\text{--}1\,\mathrm{mrad}.
$$

Those are not huge for normal orbit control, but they are large on the SSMB sensitivity scale. If the bump induces dispersion-like motion of only a few $0.1\,\mathrm{mm}$ at the modulator/radiator, transverse-longitudinal coupling can significantly reduce the coherent radiation.

---

## Quick experimental logic

The most suspicious sequence is:

1. bumper strength proxy changes;
2. U125 position/angle proxy changes;
3. tune or QPD/profile changes;
4. coherent signal changes systematically.

The most convincing pattern is a correlation:

$$
P_{\mathrm{coh}}\downarrow
\quad\Longleftrightarrow\quad
|\Delta x'|,\ |\Delta y'|,\ |\Delta\nu|,\ \text{or profile size}\uparrow.
$$

A polarity asymmetry between positive and negative bumper settings suggests nonlinear optics, sextupole feed-down, or imperfect closure.

---

## Final takeaway

$$
\boxed{
\text{If the bumper changes the U125 angle, tune, or profile size, it is not a pure path-length knob.}
}
$$

