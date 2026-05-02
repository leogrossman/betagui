# Theory and interpretation guide

This document explains the physics behind the SSMB PoP-II CS-Studio bumper diagnostics. It focuses on why BPM angle proxies, bumper current combinations, QPD/profile sizes, tunes, and coherent signal correlations are useful for identifying whether the four-steerer bumper perturbs SSMB conditions.

---

## 1. U125 angle from BPM pairs

The four BPMs around U125 are ordered as

$$
\mathrm{BPM3},\quad \mathrm{BPM4},\quad \mathrm{U125},\quad \mathrm{BPM5},\quad \mathrm{BPM6}.
$$

The upstream horizontal angle proxy is

$$
x'_{34}=\frac{x_4-x_3}{s_4-s_3}.
$$

The downstream horizontal angle proxy is

$$
x'_{56}=\frac{x_6-x_5}{s_6-s_5}.
$$

Using the lattice distances

$$
L_{34}=s_4-s_3=0.8594\,\mathrm{m},
$$

and

$$
L_{56}=s_6-s_5=0.9006\,\mathrm{m},
$$

we calculate

$$
x'_{34}=\frac{x_4-x_3}{0.8594\,\mathrm{m}},
$$

$$
x'_{56}=\frac{x_6-x_5}{0.9006\,\mathrm{m}}.
$$

If $x_i$ are in $\mathrm{mm}$ and the distances are in $\mathrm{m}$, the angle is in $\mathrm{mrad}$:

$$
1\,\mathrm{mm}/\mathrm{m}=1\,\mathrm{mrad}.
$$

The horizontal angle mismatch is

$$
\Delta x'=x'_{56}-x'_{34}.
$$

The same definitions are used vertically:

$$
y'_{34}=\frac{y_4-y_3}{0.8594\,\mathrm{m}},
$$

$$
y'_{56}=\frac{y_6-y_5}{0.9006\,\mathrm{m}},
$$

and

$$
\Delta y'=y'_{56}-y'_{34}.
$$

---

## 2. Why angle matters for SSMB

A changed trajectory through the laser modulator/radiator can have several effects:

1. it can change the laser-electron transverse overlap;
2. it can indicate the bumper is leaking orbit through the U125 section;
3. it can indicate changed local optics;
4. it can correlate with dispersion leakage and transverse-longitudinal coupling.

A practical warning level is

$$
|\Delta x'|,\ |\Delta y'| \gtrsim 50\,\mu\mathrm{rad}=0.05\,\mathrm{mrad}.
$$

This does not prove the bumper is harmful, but it is large enough that it should be correlated with coherent signal, tune, and QPD/profile changes.

---

## 3. Bumper path-length scaling

The path length of a trajectory with small transverse slope $x'(s)$ is

$$
C=\int \sqrt{1+x'(s)^2}\,ds.
$$

For $|x'|\ll1$,

$$
\sqrt{1+x'^2}\approx1+\frac{1}{2}x'^2.
$$

Thus the path-length increase caused by a horizontal bump is approximately

$$
\Delta C\approx\frac{1}{2}\int x'(s)^2\,ds.
$$

For a sinusoidal model

$$
x(s)=a\sin\left(\frac{2\pi s}{L}\right),
$$

we have

$$
x'(s)=\frac{2\pi a}{L}\cos\left(\frac{2\pi s}{L}\right).
$$

Therefore

$$
\Delta C
=\frac{1}{2}\int_0^L
\left(\frac{2\pi a}{L}\right)^2
\cos^2\left(\frac{2\pi s}{L}\right)ds.
$$

Since

$$
\int_0^L\cos^2\left(\frac{2\pi s}{L}\right)ds=\frac{L}{2},
$$

we obtain

$$
\Delta C=\frac{\pi^2a^2}{L}.
$$

Solving for amplitude gives

$$
a=\sqrt{\frac{\Delta C\,L}{\pi^2}}.
$$

For one optical period,

$$
\Delta C=\lambda_L=1064\,\mathrm{nm}=1.064\times10^{-6}\,\mathrm{m}.
$$

Example amplitudes are:

| Effective bump length $L$ | Required amplitude $a$ |
|---:|---:|
| $3\,\mathrm{m}$ | $0.57\,\mathrm{mm}$ |
| $6\,\mathrm{m}$ | $0.80\,\mathrm{mm}$ |
| $12\,\mathrm{m}$ | $1.14\,\mathrm{mm}$ |
| $24\,\mathrm{m}$ | $1.61\,\mathrm{mm}$ |

A real four-steerer bump is not exactly sinusoidal, so a practical order-of-magnitude estimate is

$$
a\sim1\text{--}3\,\mathrm{mm}.
$$

The corresponding kick scale is typically

$$
\theta\sim0.2\text{--}1\,\mathrm{mrad}.
$$

---

## 4. Bumper strength proxy from currents

The corrector kick is approximately proportional to current:

$$
\theta_i\propto I_i.
$$

Since path length scales quadratically with trajectory angle,

$$
\Delta C\propto\theta^2,
$$

an operational bumper-strength proxy is

$$
S_I=\sum_i I_i^2.
$$

This is not an absolute path-length calibration. It is a convenient quantity to correlate with orbit, tune, QPD/profile size, and coherent signal.

Another useful current proxy is

$$
S_{|I|}=\sum_i |I_i|,
$$

which measures total steering effort. Imbalance proxies can reveal whether the bump is symmetric or leaking.

---

## 5. SSMB longitudinal map and bunching

The laser modulator imposes an energy modulation

$$
\delta^+=\delta^-+A\sin(k_L z),
$$

where

$$
k_L=\frac{2\pi}{\lambda_L}.
$$

After one turn, phase slippage gives

$$
z^+=z^-+R_{56}\delta^+.
$$

For the storage ring,

$$
R_{56}=-\eta_0C_0.
$$

The combined one-turn map is

$$
z^+=z^-+R_{56}A\sin(k_L z).
$$

The first-harmonic bunching factor has the approximate CHG-like form

$$
b_1\approx J_1(k_LR_{56}A).
$$

The first maximum of $J_1^2$ occurs near

$$
k_LR_{56}A\approx1.84.
$$

The first zero occurs near

$$
k_LR_{56}A\approx3.83.
$$

This is the mathematical origin of overbunching. Increasing $A$, $R_{56}$, or the effective number of turns can push the system past the optimum compression point.

---

## 6. Numerical SSMB scale

The SSMB laser wavelength is

$$
\lambda_L=1064\,\mathrm{nm}.
$$

Therefore

$$
k_L=\frac{2\pi}{1.064\times10^{-6}\,\mathrm{m}}
\approx5.9\times10^6\,\mathrm{m^{-1}}.
$$

The coherent power suppression from longitudinal smearing is approximately

$$
\frac{P}{P_0}\approx\exp\left[-(k_L\sigma_z)^2\right].
$$

For example:

| Longitudinal smearing $\sigma_z$ | Approximate $P/P_0$ at $1064\,\mathrm{nm}$ |
|---:|---:|
| $50\,\mathrm{nm}$ | $0.92$ |
| $100\,\mathrm{nm}$ | $0.71$ |
| $150\,\mathrm{nm}$ | $0.46$ |
| $200\,\mathrm{nm}$ | $0.25$ |
| $300\,\mathrm{nm}$ | $0.043$ |
| $500\,\mathrm{nm}$ | $1.7\times10^{-4}$ |

Thus $100\text{--}200\,\mathrm{nm}$ of effective longitudinal smearing is already important.

---

## 7. Transverse-longitudinal coupling danger scale

The horizontal TLC smearing estimate is

$$
\sigma_{z,\mathrm{TLC}}
=2\sqrt{\epsilon_xH_x}\,|\sin(m\pi\nu_x)|,
$$

where

$$
H_x=\gamma_xD_x^2+2\alpha_xD_xD_x'+\beta_xD_x'^2,
$$

and

$$
\gamma_x=\frac{1+
\alpha_x^2}{\beta_x}.
$$

For a simple estimate, take

$$
\alpha_x=0,
\qquad
D_x'=0,
\qquad
|\sin(m\pi\nu_x)|=1.
$$

Then

$$
H_x=\frac{D_x^2}{\beta_x},
$$

so

$$
\sigma_{z,\mathrm{TLC}}
=2D_x\sqrt{\frac{\epsilon_x}{\beta_x}}.
$$

Using

$$
\epsilon_x=100\,\mathrm{nm\,rad}=10^{-7}\,\mathrm{m\,rad},
$$

and

$$
\beta_x=2\,\mathrm{m},
$$

we get

$$
\sqrt{\frac{\epsilon_x}{\beta_x}}
=\sqrt{\frac{10^{-7}}{2}}
=2.236\times10^{-4}.
$$

Therefore

$$
\sigma_{z,\mathrm{TLC}}
=4.472\times10^{-4}D_x,
$$

with $D_x$ in metres.

Numerically:

| $D_x$ at U125 | $\sigma_{z,\mathrm{TLC}}$ | Approximate $P/P_0$ at $1064\,\mathrm{nm}$ |
|---:|---:|---:|
| $0.1\,\mathrm{mm}$ | $45\,\mathrm{nm}$ | $0.93$ |
| $0.3\,\mathrm{mm}$ | $134\,\mathrm{nm}$ | $0.53$ |
| $0.5\,\mathrm{mm}$ | $224\,\mathrm{nm}$ | $0.17$ |
| $1.0\,\mathrm{mm}$ | $447\,\mathrm{nm}$ | $0.001$ |

This is why dispersion-like effects of only a few $0.1\,\mathrm{mm}$ can matter.

---

## 8. Why a bump can create dispersion-like effects

A corrector kick depends on beam rigidity:

$$
\theta(\delta)=\frac{\int B\,dl}{B\rho(1+\delta)}.
$$

For small $\delta$,

$$
\theta(\delta)\approx\theta_0(1-\delta).
$$

Therefore

$$
\frac{\partial\theta}{\partial\delta}\approx-\theta_0.
$$

The bump orbit therefore has an energy dependence. In a simple order-of-magnitude sense,

$$
D_{\mathrm{bump}}(s)=\frac{\partial x_{\mathrm{bump}}(s)}{\partial\delta}
\sim -x_{\mathrm{bump}}(s).
$$

Thus a millimetre-scale bump can naturally produce millimetre-scale dispersion-like leakage unless the lattice and bump closure suppress it.

This is the main reason the bumper is potentially dangerous for SSMB.

---

## 9. Sextupole feed-down and tune shifts

If the closed orbit is displaced in a sextupole by $x_0$, the sextupole produces an effective quadrupole error:

$$
\Delta k_1=k_2x_0.
$$

Integrated over a sextupole,

$$
\Delta k_1L=(k_2L)x_0.
$$

The approximate tune shift is

$$
\Delta\nu_x\approx\frac{1}{4\pi}\sum_j\beta_{x,j}\Delta k_{1,j}L_j.
$$

For representative values

$$
k_2L=10\,\mathrm{m^{-2}},
\qquad
x_0=1\,\mathrm{mm},
\qquad
\beta_x=5\,\mathrm{m},
$$

we get

$$
\Delta k_1L=10\cdot10^{-3}=0.01\,\mathrm{m^{-1}},
$$

and

$$
\Delta\nu_x\approx\frac{5\cdot0.01}{4\pi}\approx0.004.
$$

Thus millimetre-level orbit in sextupoles can plausibly create tune shifts of order

$$
\Delta\nu\sim10^{-3}\text{--}10^{-2}.
$$

This matters because the TLC term contains

$$
\sin^2(m\pi\nu_x),
$$

so tune changes can alter the multi-turn microbunch survival.

---

## 10. What to look for experimentally

The most suspicious pattern is:

1. bumper strength proxy changes;
2. U125 angle/position proxy changes;
3. tune or QPD/profile changes;
4. coherent signal changes systematically.

A clean path-length-only effect would ideally show coherent signal variation correlated with bumper strength but minimal changes in U125 angle, tune, and profile sizes.

A likely optics/TLC effect shows

$$
P_{\mathrm{coh}}\downarrow
\quad\text{while}\quad
|\Delta x'|,\ |\Delta y'|,\ |\Delta\nu|,\ \text{or profile size}\uparrow.
$$

A polarity asymmetry between positive and negative bumper settings suggests nonlinear optics or sextupole feed-down.

---

## 11. Practical thresholds

Use these as first operational warning levels:

| Quantity | Mostly safe | Visible / suspicious | Serious |
|---|---:|---:|---:|
| U125 orbit change | $<0.05\,\mathrm{mm}$ | $0.1\,\mathrm{mm}$ | $>0.2\,\mathrm{mm}$ |
| U125 angle mismatch | $<0.03\,\mathrm{mrad}$ | $0.05\,\mathrm{mrad}$ | $>0.1\,\mathrm{mrad}$ |
| tune shift | $<5\times10^{-4}$ | $10^{-3}$ | $>5\times10^{-3}$ |
| coherent signal loss | within shot noise | $10\text{--}30\%$ | $>50\%$ |
| QPD/profile size change | $<1\%$ | $3\%$ | $>5\%$ |

---

## 12. Final interpretation

The bumper is intended to change the path length by about one optical period:

$$
\Delta C\sim\lambda_L=1.064\,\mu\mathrm{m}.
$$

That is a tiny relative circumference change,

$$
\frac{\Delta C}{C_0}\sim2.2\times10^{-8},
$$

but it corresponds to a full optical phase change:

$$
\Delta\phi_L=k_L\Delta C=2\pi.
$$

Generating this geometrically can require millimetre-scale orbit excursions and sub-mrad kicks. These are large enough to modify dispersion, tune, and TLC at the level SSMB cares about.

Therefore:

$$
\boxed{
\text{SSMB sensitivity scale}\approx\text{bumper perturbation scale.}
}
$$

