
# Theory and interpretation guide

## 1. U125 angle from BPM pairs

Before U125:

```math
x'_{34} = \frac{x_4-x_3}{s_4-s_3}
```

After U125:

```math
x'_{56} = \frac{x_6-x_5}{s_6-s_5}
```

With BPM values in mm and distances in m, the result is in mrad because

```math
1\,\mathrm{mm}/\mathrm{m}=1\,\mathrm{mrad}.
```

The angle mismatch proxy is

```math
\Delta x' = x'_{56}-x'_{34}.
```

The same is used for vertical:

```math
\Delta y' = y'_{56}-y'_{34}.
```

## 2. Why angle matters

A changed trajectory through the laser modulator/radiator can change laser-electron overlap and can indicate that the bumper is not a harmless path-length element.

As a practical alarm level:

```math
|\Delta x'|, |\Delta y'| \gtrsim 50\,\mu\mathrm{rad}=0.05\,\mathrm{mrad}
```

is already worth correlating with coherent signal.

## 3. Bumper strength proxy

The geometrical path-length increase scales like

```math
\Delta C \approx \frac12\int x'(s)^2\,ds.
```

Corrector kick scales with current:

```math
\theta_i \propto I_i.
```

Therefore a simple operational proxy is

```math
S_I = \sum_i I_i^2.
```

It is not a calibrated path length, but it should correlate with the intentional bumper strength.

## 4. TLC danger scale

The horizontal TLC smearing estimate is

```math
\sigma_{z,\mathrm{TLC}}=2\sqrt{\epsilon_x H_x}|\sin(m\pi\nu_x)|,
```

with

```math
H_x=\gamma_xD_x^2+2\alpha_xD_xD_x'+\beta_xD_x'^2.
```

For a simple estimate with `beta_x = 2 m`, `epsilon_x = 100 nm rad`, `D_x'=0`:

```math
\sigma_z \approx 2D_x\sqrt{\frac{\epsilon_x}{\beta_x}}.
```

Numerically:

| `D_x` at U125 | `sigma_z` | approximate `P/P0` at 1064 nm |
|---:|---:|---:|
| 0.1 mm | 45 nm | 0.93 |
| 0.3 mm | 134 nm | 0.53 |
| 0.5 mm | 224 nm | 0.17 |
| 1.0 mm | 447 nm | 0.001 |

So dispersion-like effects at only a few 0.1 mm can matter.

## 5. What to look for experimentally

The most suspicious pattern is:

1. bumper strength proxy changes,
2. U125 angle/position proxy changes,
3. tune or QPD/profile changes,
4. coherent signal changes systematically.

A polarity asymmetry between positive and negative bumper settings suggests nonlinear optics or sextupole feed-down.
