
# Theory and interpretation guide for the SSMB bumper diagnostics

## 1. What the diagnostics are trying to answer

The Phase-II SSMB experiment wants to keep the RF frequency fixed while using a four-steerer bumper for orbit/path-length control.  This is necessary because turn-by-turn laser modulation requires the optical phase to stay synchronized.

The main question is not only whether the bump changes the orbit.  The SSMB-relevant question is whether the bump changes quantities that enter the microbunching suppression exponentially:

$$
D_x,
\quad D_x',
\quad D_y,
\quad D_y',
\quad H_x,
\quad H_y,
\quad \nu_x,
\quad \nu_y,
\quad \eta_0,
\quad R_{56}.
$$

You cannot directly measure dispersion in this setup, so the diagnostic viewer uses proxy observables:

- BPM centroid changes near U125;
- upstream/downstream orbit-angle proxies;
- bumper current strength proxies;
- tune shifts;
- QPD/profile changes in dispersive and non-dispersive regions;
- coherent-radiation signal changes.

## 2. U125 orbit-angle proxies

The four BPMs around U125 are ordered as

$$
\text{BPM3} \rightarrow \text{BPM4} \rightarrow \text{U125} \rightarrow \text{BPM5} \rightarrow \text{BPM6}.
$$

The simple two-BPM angle estimates are

$$
x'_{\mathrm{up}}
=
\frac{x_4-x_3}{s_4-s_3},
$$

$$
x'_{\mathrm{dn}}
=
\frac{x_6-x_5}{s_6-s_5}.
$$

The angle mismatch proxy is

$$
\Delta x'
=
x'_{\mathrm{dn}}-x'_{\mathrm{up}}.
$$

Similarly for the vertical plane:

$$
y'_{\mathrm{up}}
=
\frac{y_4-y_3}{s_4-s_3},
$$

$$
y'_{\mathrm{dn}}
=
\frac{y_6-y_5}{s_6-s_5},
$$

$$
\Delta y'
=
y'_{\mathrm{dn}}-y'_{\mathrm{up}}.
$$

With BPM readings in mm and distances in m, the result has units mm/m, which is numerically mrad.

The exact values used are

$$
L_{34}=0.8594\,\mathrm{m},
\qquad
L_{56}=0.9006\,\mathrm{m}.
$$

## 3. Why this matters for SSMB

Microbunching at the fundamental laser wavelength uses

$$
\lambda_L = 1064\,\mathrm{nm},
\qquad
k_L=\frac{2\pi}{\lambda_L}
=5.905\times10^6\,\mathrm{m}^{-1}.
$$

Longitudinal smearing reduces coherent power approximately as

$$
\frac{P}{P_0}
=
\exp\left[-(n k_L \sigma_z)^2\right].
$$

For the fundamental, $n=1$:

| rms longitudinal smearing $\sigma_z$ | coherent power factor $P/P_0$ |
|---:|---:|
| $50\,\mathrm{nm}$ | $0.92$ |
| $100\,\mathrm{nm}$ | $0.71$ |
| $150\,\mathrm{nm}$ | $0.46$ |
| $200\,\mathrm{nm}$ | $0.25$ |
| $300\,\mathrm{nm}$ | $0.043$ |
| $500\,\mathrm{nm}$ | $1.7\times10^{-4}$ |

Thus a sub-micron effect is already very large for SSMB.

## 4. TLC thresholds

The transverse-longitudinal coupling smearing can be estimated by

$$
\sigma_{z,\mathrm{TLC}}
=
2\sqrt{\epsilon_x H_x}\,\left|\sin(m\pi\nu_x)\right|,
$$

with

$$
H_x
=
\gamma_xD_x^2
+2\alpha_xD_xD_x'
+\beta_xD_x'^2.
$$

For the simple estimate

$$
\alpha_x=0,
\quad D_x'=0,
\quad \beta_x=2\,\mathrm{m},
\quad \epsilon_x=100\,\mathrm{nm\,rad},
$$

one gets

$$
\sigma_{z,\mathrm{TLC}}
=
2D_x\sqrt{\frac{\epsilon_x}{\beta_x}}.
$$

Numerically:

| $D_x$ at the modulator | $\sigma_{z,\mathrm{TLC}}$ | expected $P/P_0$ |
|---:|---:|---:|
| $0.1\,\mathrm{mm}$ | $45\,\mathrm{nm}$ | $0.93$ |
| $0.2\,\mathrm{mm}$ | $89\,\mathrm{nm}$ | $0.76$ |
| $0.3\,\mathrm{mm}$ | $134\,\mathrm{nm}$ | $0.53$ |
| $0.5\,\mathrm{mm}$ | $224\,\mathrm{nm}$ | $0.17$ |
| $1.0\,\mathrm{mm}$ | $447\,\mathrm{nm}$ | $0.001$ |

So a useful operational rule is:

$$
|\Delta D_x|_{\mathrm{U125}}
\sim 0.1\,\mathrm{mm}
\quad\Rightarrow\quad
\text{visible},
$$

$$
|\Delta D_x|_{\mathrm{U125}}
\sim 0.3\,\mathrm{mm}
\quad\Rightarrow\quad
\text{serious},
$$

$$
|\Delta D_x|_{\mathrm{U125}}
\sim 1\,\mathrm{mm}
\quad\Rightarrow\quad
\text{potentially catastrophic}.
$$

Since direct dispersion is not measured here, strong BPM-pattern changes near U125 are treated as warning proxies.

## 5. Bumper path-length scale

A geometric closed bump changes path length by

$$
\Delta C
\approx
\frac{1}{2}\int x'(s)^2\,ds.
$$

For a sinusoidal bump of amplitude $a$ over length $L$,

$$
x(s)=a\sin\left(\frac{2\pi s}{L}\right),
$$

$$
\Delta C=\frac{\pi^2a^2}{L}.
$$

Solving for one optical period,

$$
\Delta C=\lambda_L=1.064\,\mu\mathrm{m},
$$

$$
a=\sqrt{\frac{\Delta C L}{\pi^2}}.
$$

Typical results:

| effective bump length $L$ | amplitude $a$ for one $\lambda_L$ |
|---:|---:|
| $3\,\mathrm{m}$ | $0.57\,\mathrm{mm}$ |
| $6\,\mathrm{m}$ | $0.80\,\mathrm{mm}$ |
| $12\,\mathrm{m}$ | $1.14\,\mathrm{mm}$ |
| $24\,\mathrm{m}$ | $1.61\,\mathrm{mm}$ |

A real four-corrector bump can easily be in the

$$
a\sim 1\text{--}3\,\mathrm{mm}
$$

range, which is SSMB-relevant.

## 6. Steerer current proxies

The corrector kick is

$$
\theta=\frac{\int B\,dl}{B\rho}.
$$

For about $254\,\mathrm{MeV}$,

$$
B\rho\approx0.847\,\mathrm{Tm}.
$$

A $0.5\,\mathrm{mrad}$ kick needs

$$
\int B\,dl
\approx
0.847\cdot 5\times10^{-4}
=4.2\times10^{-4}\,\mathrm{Tm}.
$$

The viewer uses

$$
\Sigma I^2
=I_1^2+I_2^2+I_3^2+I_4^2
$$

as a path-length-strength proxy because geometric path length scales approximately as

$$
\Delta C\propto \theta^2\propto I^2.
$$

The viewer also includes balance proxies such as

$$
(I_1+I_4)-(I_2+I_3),
$$

and

$$
(I_1+I_2)-(I_3+I_4),
$$

which are useful for seeing whether the bump shape changes, not just its total strength.

## 7. Tune shifts and sextupole feed-down

A bumped orbit through sextupoles creates quadrupole feed-down:

$$
\Delta k_1 = k_2 x_0.
$$

The tune shift is roughly

$$
\Delta\nu_x
\approx
\frac{1}{4\pi}\sum_j \beta_{x,j}\Delta k_{1,j}L_j.
$$

For example, with

$$
k_2L=10\,\mathrm{m}^{-2},
\quad x_0=1\,\mathrm{mm},
\quad \beta_x=5\,\mathrm{m},
$$

$$
\Delta\nu_x
\approx
\frac{5\cdot 0.01}{4\pi}
\approx 0.004.
$$

Therefore tune changes of order

$$
\Delta\nu\sim10^{-3}\text{--}10^{-2}
$$

are a strong warning that the bumper is changing optics, not only path length.

## 8. What to look for experimentally

During a bumper scan, worry if you see the following correlations:

1. Coherent signal decreases while $\Sigma I^2$ increases.
2. Coherent signal changes when $x'$ or $y'$ mismatch changes.
3. Tune shifts by more than about $10^{-3}$.
4. QPD/profile sizes change mainly in dispersive regions.
5. Positive and negative bumper polarity produce asymmetric effects.

Most important thresholds:

| Indicator | visible | serious |
|---|---:|---:|
| local orbit shift near U125 | $0.05\text{--}0.1\,\mathrm{mm}$ | $>0.2\,\mathrm{mm}$ |
| angle change proxy | $20\text{--}50\,\mu\mathrm{rad}$ | $>50\,\mu\mathrm{rad}$ |
| tune shift | $10^{-3}$ | $>3\times10^{-3}$ |
| coherent signal loss | $10\text{--}30\%$ | $>50\%$ |
| QPD size change | $1\text{--}3\%$ | $>3\text{--}5\%$ |

## 9. Caveat about BPM angle proxies

The two-BPM formula is a straight-line approximation.  If there are strong quadrupoles between the BPMs and U125, the true angle should be reconstructed using transfer matrices:

$$
\begin{pmatrix}x_2\\x_2'\end{pmatrix}
=
M
\begin{pmatrix}x_1\\x_1'\end{pmatrix}.
$$

Then

$$
x_1'
=
\frac{x_2-M_{11}x_1}{M_{12}}.
$$

The present viewer uses the simple BPM-difference proxy because it is robust and directly available from PVs.  Treat it as a scan-correlated warning signal, not as a full lattice reconstruction.
