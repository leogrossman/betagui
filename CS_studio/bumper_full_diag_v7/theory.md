# Theory and interpretation notes

## 1. U125 local angle proxies

With BPMs before and after the undulator:

$$
x'_\mathrm{up}pproxrac{x_4-x_3}{s_4-s_3},\qquad
x'_\mathrm{down}pproxrac{x_6-x_5}{s_6-s_5}.
$$

Same for $y$:

$$
y'_\mathrm{up}pproxrac{y_4-y_3}{s_4-s_3},\qquad
y'_\mathrm{down}pproxrac{y_6-y_5}{s_6-s_5}.
$$

Since BPM positions are in mm and longitudinal distances are in m, the angle is in mrad.

The mismatch is

$$
\Delta x'=x'_\mathrm{down}-x'_\mathrm{up},\qquad
\Delta y'=y'_\mathrm{down}-y'_\mathrm{up}.
$$

Large changes indicate that the bumper is not just changing path length; it changes the local trajectory through the modulator/radiator.

## 2. Why angle/orbit changes matter for SSMB

A trajectory change can change laser-electron overlap, undulator radiation acceptance, dispersion leakage, and transverse-longitudinal coupling (TLC). The TLC smearing scale is

$$
\sigma_{z,\mathrm{TLC}}=2\sqrt{\epsilon_x H_x}|\sin(m\pi
u_x)|,
$$

with

$$
H_x=\gamma_xD_x^2+2lpha_xD_xD_x'+eta_xD_x'^2.
$$

For a simple estimate with $D'_x=0$, $lpha_x=0$:

$$
\sigma_{z,\mathrm{TLC}}=2D_x\sqrt{rac{\epsilon_x}{eta_x}}.
$$

For $\epsilon_x=100\,\mathrm{nm\,rad}$ and $eta_x=2\,\mathrm{m}$:

$$
D_x=0.1\,\mathrm{mm}\Rightarrow\sigma_zpprox45\,\mathrm{nm},
$$

$$
D_x=0.3\,\mathrm{mm}\Rightarrow\sigma_zpprox134\,\mathrm{nm},
$$

$$
D_x=1\,\mathrm{mm}\Rightarrow\sigma_zpprox447\,\mathrm{nm}.
$$

The coherent power penalty is roughly

$$
rac{P}{P_0}=\exp[-(k_L\sigma_z)^2],\qquad k_L=rac{2\pi}{1064\,\mathrm{nm}}.
$$

Thus mm-scale dispersion leakage can strongly suppress SSMB.

## 3. Bumper current diagnostics

The intended geometric path length change scales approximately as

$$
\Delta Cpproxrac12\int x'(s)^2\,ds\propto	heta^2\propto I^2.
$$

This motivates the quadratic current proxy:

$$
\Sigma(\Delta I_i)^2.
$$

The pair-balance and left-right imbalance are not exact optics quantities, but they help identify whether the four-steerer pattern changes shape instead of only strength.

## 4. What to look for during a scan

The strongest evidence for bumper-induced SSMB-relevant optics changes is a correlated pattern:

$$
	ext{bumper proxy changes}\quad\Rightarrow\quad
\Delta x',\Delta y',	ext{ or QPD size changes}\quad\Rightarrow\quad
P_\mathrm{coh}	ext{ changes}.
$$

A polarity asymmetry between positive and negative bumper settings suggests sextupole feed-down or nonlinear optics.
