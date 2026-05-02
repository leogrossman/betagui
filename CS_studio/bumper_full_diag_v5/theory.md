
# Theory and diagnostic guide for the SSMB Phase-II bumper views

This note explains what the `.plt` files are meant to show and what numerical ranges should make you suspicious during a Phase-II SSMB bumper scan.

## 1. Why the bumper matters

The Phase-II laser must stay synchronized turn-by-turn. Therefore the RF frequency should remain fixed, and path-length/orbit correction is done by a closed four-steerer bump. The intended path-length change can be of order one laser period,

$$
\Delta C \sim \lambda_L = 1064\,\mathrm{nm}.
$$

For the MLS circumference,

$$
C_0 \approx 48\,\mathrm{m},
$$

this is only

$$
\frac{\Delta C}{C_0}
=\frac{1.064\times10^{-6}}{48}
\approx2.2\times10^{-8},
$$

but optically it is a full phase turn,

$$
\Delta\phi_L = k_L\Delta C = 2\pi .
$$

So the change is tiny as a circumference perturbation but large as an SSMB phase perturbation.

## 2. Path length from a closed bump

For small transverse slope,

$$
ds_{\mathrm{orbit}}
=\sqrt{1+x'(s)^2}\,ds
\approx\left(1+\frac{x'(s)^2}{2}\right)ds,
$$

so the extra path length is

$$
\Delta C_{\mathrm{bump}}
\approx\frac12\int x'(s)^2\,ds .
$$

For a sinusoidal bump,

$$
x(s)=a\sin\left(\frac{2\pi s}{L}\right),
$$

$$
x'(s)=\frac{2\pi a}{L}\cos\left(\frac{2\pi s}{L}\right),
$$

and therefore

$$
\Delta C
=\frac12\int_0^L
\left(\frac{2\pi a}{L}\right)^2
\cos^2\left(\frac{2\pi s}{L}\right)ds
=\frac{\pi^2a^2}{L}.
$$

Solving for bump amplitude,

$$
a=\sqrt{\frac{\Delta C L}{\pi^2}}.
$$

For \(\Delta C=1.064\,\mu\mathrm{m}\):

| Effective bump length | Required amplitude |
|---:|---:|
| \(3\,\mathrm{m}\) | \(0.57\,\mathrm{mm}\) |
| \(6\,\mathrm{m}\) | \(0.80\,\mathrm{mm}\) |
| \(12\,\mathrm{m}\) | \(1.14\,\mathrm{mm}\) |
| \(24\,\mathrm{m}\) | \(1.61\,\mathrm{mm}\) |

A realistic four-steerer bump can easily be in the range

$$
a\sim1\text{--}3\,\mathrm{mm},
\qquad
\theta\sim0.2\text{--}1\,\mathrm{mrad}.
$$

## 3. Undulator BPM angle proxies

The relevant BPM order is

$$
\mathrm{BPM3}\rightarrow\mathrm{BPM4}\rightarrow\mathrm{U125}\rightarrow\mathrm{BPM5}\rightarrow\mathrm{BPM6}.
$$

The positions used in the plots are

$$
s_3=8.1872\,\mathrm{m},\quad
s_4=9.0466\,\mathrm{m},\quad
s_U=12.0000\,\mathrm{m},
$$

$$
s_5=14.9534\,\mathrm{m},\quad
s_6=15.8540\,\mathrm{m}.
$$

Thus

$$
L_{34}=s_4-s_3=0.8594\,\mathrm{m},
$$

$$
L_{56}=s_6-s_5=0.9006\,\mathrm{m}.
$$

Assuming BPM readings are in mm, the simple drift-like angle proxy is in mrad:

$$
x'_{\mathrm{before}}
\approx\frac{x_4-x_3}{L_{34}},
$$

$$
x'_{\mathrm{after}}
\approx\frac{x_6-x_5}{L_{56}}.
$$

The mismatch is

$$
\Delta x'
=x'_{\mathrm{after}}-x'_{\mathrm{before}}.
$$

This is a proxy, not a full transfer-matrix reconstruction. It is still useful as a live diagnostic.

The centered plots subtract the typical values you gave:

$$
x_3\approx-0.07\,\mathrm{mm},\quad
x_4\approx-0.19\,\mathrm{mm},
$$

$$
x_5\approx-0.76\,\mathrm{mm},\quad
x_6\approx-0.16\,\mathrm{mm}.
$$

Corresponding typical angles:

$$
x'_{34,0}=\frac{-0.19-(-0.07)}{0.8594}
\approx -0.140\,\mathrm{mrad},
$$

$$
x'_{56,0}=\frac{-0.16-(-0.76)}{0.9006}
\approx0.666\,\mathrm{mrad}.
$$

The absolute values are not necessarily the issue. What matters during the scan is systematic change from baseline.

## 4. Numerical thresholds for SSMB sensitivity

### 4.1 Local orbit at the undulator

Watch for

$$
|\Delta x_U|\gtrsim0.1\,\mathrm{mm}.
$$

This can change laser-electron overlap and the effective modulation amplitude. A few \(0.1\,\mathrm{mm}\) is already concerning.

### 4.2 Angle proxy changes

Watch for

$$
|\Delta x'|\gtrsim50\,\mu\mathrm{rad}=0.05\,\mathrm{mrad}.
$$

This is especially important if it correlates with coherent power loss or tune shift.

### 4.3 Tune shifts

A bump through sextupoles gives quadrupole feed-down,

$$
\Delta k_1 = k_2 x_0.
$$

The tune shift estimate is

$$
\Delta\nu_x
\approx\frac{1}{4\pi}\sum_j\beta_{x,j}\Delta k_{1,j}L_j.
$$

For example, with

$$
k_2L=10\,\mathrm{m^{-2}},\quad
x_0=1\,\mathrm{mm},\quad
\beta_x=5\,\mathrm{m},
$$

one obtains

$$
\Delta\nu_x\approx\frac{5\cdot10\cdot10^{-3}}{4\pi}
\approx0.004.
$$

So these ranges are useful:

| Tune change | Interpretation |
|---:|---|
| \(<5\times10^{-4}\) | probably small |
| \(10^{-3}\) | visible optics change |
| \(3\times10^{-3}\text{--}10^{-2}\) | serious for SSMB/TLC interpretation |

### 4.4 Dispersion/TLC sensitivity

Even if you cannot directly measure dispersion during the scan, the dangerous mechanism is still transverse-longitudinal coupling. The horizontal TLC smearing scale is

$$
\sigma_{z,\mathrm{TLC}}
=2\sqrt{\epsilon_x H_x}\,|\sin(m\pi\nu_x)|,
$$

with

$$
H_x=
\gamma_xD_x^2
+2\alpha_xD_xD_x'
+\beta_xD_x'^2.
$$

For the simplified case

$$
\alpha_x=0,\quad D_x'=0,\quad \beta_x=2\,\mathrm{m},
$$

this becomes

$$
\sigma_{z,\mathrm{TLC}}
=2D_x\sqrt{\frac{\epsilon_x}{\beta_x}}.
$$

For

$$
\epsilon_x=100\,\mathrm{nm\,rad}=10^{-7}\,\mathrm{m\,rad},
$$

one gets

$$
\sigma_{z,\mathrm{TLC}}
=4.47\times10^{-4}D_x.
$$

The coherent power penalty is approximately

$$
\frac{P}{P_0}
=\exp\left[-(k_L\sigma_z)^2\right],
$$

where

$$
k_L=\frac{2\pi}{1064\,\mathrm{nm}}
=5.905\times10^6\,\mathrm{m^{-1}}.
$$

| Effective \(D_x\) at modulator | \(\sigma_{z,\mathrm{TLC}}\) | \(P/P_0\) |
|---:|---:|---:|
| \(0.05\,\mathrm{mm}\) | \(22\,\mathrm{nm}\) | 0.98 |
| \(0.10\,\mathrm{mm}\) | \(45\,\mathrm{nm}\) | 0.93 |
| \(0.30\,\mathrm{mm}\) | \(134\,\mathrm{nm}\) | 0.53 |
| \(0.50\,\mathrm{mm}\) | \(224\,\mathrm{nm}\) | 0.17 |
| \(1.00\,\mathrm{mm}\) | \(447\,\mathrm{nm}\) | 0.001 |

So the practical rule is:

$$
D_x\sim0.1\,\mathrm{mm}\quad\text{visible},
$$

$$
D_x\sim0.3\,\mathrm{mm}\quad\text{serious},
$$

$$
D_x\sim1\,\mathrm{mm}\quad\text{nearly catastrophic}.
$$

You may not directly measure \(D_x\), but a combination of high-D BPM motion, QPD size change in dispersive regions, tune shift, and coherent-signal change is a strong proxy.

## 5. How to use the `.plt` files

### `00_core_overview_10min.plt`

Use this during scans. It contains:

- coherent signal average;
- stacked U125 mean X movement;
- upstream and downstream angle-proxy changes;
- angle mismatch;
- vertical mean motion proxy;
- bumper strength proxy \(\sum I_i^2\);
- horizontal and vertical tune shifts.

The stacked axis is not physical units directly; the legend tells the scaling. It is meant to show correlations at a glance.

### `01_u125_orbit_angle_detail_30min.plt`

Use this when something changes in the core view. It shows:

- each U125 BPM X reading centered around its typical value;
- upstream/downstream angle-proxy change;
- angle mismatch;
- U125 center extrapolation proxy.

### `02_bumper_machine_tune_detail_30min.plt`

Use this to see whether the bump is acting like a clean path-length actuator or perturbing the lattice. Watch correlations between steerers and tune shifts.

### `03_qpd_signal_detail_30min.plt`

Use this to check beam-size/profiles against coherent signal. A size change in a dispersive location but not a non-dispersive one suggests energy/dispersion-like changes. Size changes everywhere suggest beta beating, emittance, or coupling changes.

### `04_raw_sanity_check_no_formulas_10min.plt`

Open this first if formulas fail. If this shows traces, PV connectivity is OK and any problem is formula syntax or the Data Browser version.

## 6. What combinations are most suspicious?

The strongest signatures of bumper-induced SSMB-relevant lattice changes are:

1. coherent power changes systematically with \(\sum I_i^2\);
2. coherent power changes together with U125 angle mismatch;
3. tune shifts by \(\gtrsim10^{-3}\) while the bumper is moved;
4. QPD/profile size changes in dispersive regions;
5. polarity asymmetry between positive and negative bump settings.

A particularly suspicious pattern is

$$
P_{\mathrm{coh}}\downarrow,
\qquad
\Delta x'_U\neq0,
\qquad
\Delta\nu_{x,y}\neq0.
$$

This suggests the bumper is not only changing path length, but also changing optics/TLC conditions.
