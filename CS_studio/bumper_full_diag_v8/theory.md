# Theory and interpretation guide

## Why the bumper can matter

A path-length correction of one SSMB laser period is

$$
\Delta C = \lambda_L = 1064\,\mathrm{nm}.
$$

This is only

$$
\frac{\Delta C}{C_0} \approx \frac{1.064\times10^{-6}}{48} \approx 2.2\times10^{-8},
$$

but it is a full optical phase turn:

$$
\Delta\phi_L = \frac{2\pi}{\lambda_L}\Delta C = 2\pi.
$$

The problem is not the intended path-length shift itself, but the fact that creating it geometrically can require mm-scale orbit excursions and sub-mrad corrector kicks.

## Two-BPM angle proxies

For two BPMs before the undulator:

$$
x'_\mathrm{up} \approx \frac{x_4-x_3}{s_4-s_3}.
$$

For two BPMs after:

$$
x'_\mathrm{dn} \approx \frac{x_6-x_5}{s_6-s_5}.
$$

The mismatch is

$$
\Delta x' = x'_\mathrm{dn}-x'_\mathrm{up}.
$$

With BPMs in mm and distances in m, this is directly in mrad.

## Extrapolated center consistency

A simple upstream extrapolation to the U125 center is

$$
x_{0,\mathrm{up}} = x_4 + x'_\mathrm{up}(s_0-s_4).
$$

A downstream extrapolation is

$$
x_{0,\mathrm{dn}} = x_5 + x'_\mathrm{dn}(s_0-s_5).
$$

Their difference is a consistency check:

$$
\Delta x_0 = x_{0,\mathrm{dn}}-x_{0,\mathrm{up}}.
$$

If this changes with the bumper, the local U125 trajectory is changing.

## TLC sensitivity

The transverse-longitudinal coupling smearing is roughly

$$
\sigma_{z,\mathrm{TLC}}
=2\sqrt{\epsilon_x H_x}\,|\sin(m\pi\nu_x)|,
$$

where

$$
H_x = \gamma_x D_x^2 + 2\alpha_xD_xD'_x + \beta_xD_x'^2.
$$

If $D'_x=0$ and $\alpha_x=0$,

$$
\sigma_{z,\mathrm{TLC}} = 2D_x\sqrt{\frac{\epsilon_x}{\beta_x}}.
$$

For

$$
\epsilon_x=100\,\mathrm{nm\,rad},\qquad \beta_x=2\,\mathrm{m},
$$

we get

$$
\sigma_{z,\mathrm{TLC}}\approx 4.47\times10^{-4}D_x.
$$

Thus:

| $D_x$ | $\sigma_z$ | SSMB effect |
|---:|---:|---|
| $0.1\,\mathrm{mm}$ | $45\,\mathrm{nm}$ | visible |
| $0.3\,\mathrm{mm}$ | $134\,\mathrm{nm}$ | serious |
| $1.0\,\mathrm{mm}$ | $447\,\mathrm{nm}$ | nearly catastrophic |

The coherent power penalty is approximately

$$
\frac{P}{P_0}=\exp[-(k_L\sigma_z)^2],
\qquad
k_L=\frac{2\pi}{1064\,\mathrm{nm}}.
$$

## What to look for experimentally

The strongest bumper-effect signature is:

1. coherent signal changes with bumper setting;
2. U125 BPM angle/center diagnostics also change;
3. tune monitor or QPD size changes correlate with the same setting.

That combination suggests the bumper is changing SSMB-relevant lattice conditions, not just path length.
