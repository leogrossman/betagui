# Theory and interpretation for generated CS-Studio v10

## Why these plots exist

The question is not only whether the four-steerer bumper changes the path length, but whether it also perturbs the beam position and angle through the undulator region, changes the effective overlap with the laser, or leaks into optics-sensitive quantities while Q1 is scanned.

## U125 angle proxies

```text
x'_34 = (x4 - x3) / 0.8594
x'_56 = (x6 - x5) / 0.9006
Δx'  = x'_56 - x'_34
```

and analogously for `y`.

## Inferred U125 center from BPM pairs

```text
x_U125,up = x4 + x'_34 * (2.9534000000000002)
x_U125,dn = x5 + x'_56 * (-2.9534000000000002)
```

The plots show both extrapolations and their consistency. If the consistency remains near zero, the straight-line picture through U125 is relatively stable. If it grows during scans, the beam line through the undulator is distorting.

## Why Q1P1L2RP:setCur matters

`Q1P1L2RP:setCur` is the global quadrupole / alpha0 scan knob. It must be visible alongside bumper currents, not hidden in the background.

## Bumper strength proxy

```text
ΣI² = I1² + I2² + I3² + I4²
```

is used as an operational proxy because path-length effects scale approximately with squared kick / slope. v10 mostly shows changes of this quantity relative to the good-overlap baseline.

## QPD interpretation

The exported absolute QPD sigma values are large:

- QPD L2 sigma X baseline: 377.641
- QPD L2 sigma Y baseline: 116.896
- QPD L4 sigma X baseline: 535.834
- QPD L4 sigma Y baseline: 115.113

To keep subtle optics changes visible, v10 shows percentage deviations from those baselines instead of raw values.

## Practical checklist

During a scan ask:

1. Did P1 move while ΔQ1 changed as intended?
2. Did Δx′, Δy′, or U125 consistency move at the same time?
3. Did ΣI² or steerer balance drift unexpectedly?
4. Did the QPD sigma deviations move by several percent?
5. Did RF or shot-window / laser-setting proxies move too?

If yes to 2–5, the signal change is not a clean one-variable Q1/alpha0 effect.
