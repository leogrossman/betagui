# SSMB Theory And Motivation

## Why This Tool Exists

The existing `betagui` tool is centered on RF-sweep chromaticity measurement
and sextupole response. That is useful operationally, but it is not enough for
MLS SSMB studies in the low-alpha regime.

For SSMB, the more important variable is the synchronous off-momentum state:

```text
δ = (p - p0) / p0
```

and in RF scans specifically:

```text
δs(fRF)
```

The present tool is therefore built around logging the machine state required to
reconstruct `δs` and eventually the nonlinear momentum compaction series.

## Exact Synchronous Timing Condition

The synchronous particle satisfies:

```text
Trev(δs) = h / fRF
```

with:

```text
Trev(δ) = C(δ) / (β(δ) c)
```

and nonlinear momentum compaction written as:

```text
C(δ) = C0 (1 + α0 δ + α1 δ^2 + α2 δ^3 + ...)
```

using the exact relativistic velocity:

```text
β(δ) = ((1 + δ) β0 γ0) / sqrt(1 + (1 + δ)^2 β0^2 γ0^2)
```

This is the long-term fitting backbone for reconstructing higher-order
momentum-compaction structure from MLS data.

## First-Order Measurable: Slip Factor

For narrow scans, the measured first-order quantity is:

```text
η = α0 - 1/γ^2
```

with:

```text
ΔfRF / fRF ≈ -η δs
```

so:

```text
η ≈ -(ΔfRF / fRF) / δs
```

and then:

```text
α0 = η + 1/γ^2
```

This matters at MLS energy because `1/γ^2` is not negligible compared with
low-alpha operation.

## Why The Existing Qs-Based α0 Is Only A Proxy

The old tool uses synchrotron tune and cavity voltage to infer an `α0`-like
value. That is useful as a compact operational proxy, but it is still a
small-amplitude longitudinal approximation. It does not by itself recover the
nonlinear momentum compaction landscape that matters for stable microbunching.

## How δs Should Be Reconstructed

The practical first method is dispersive BPM orbit reconstruction:

```text
xi - xi,ref = Dxi δs
```

and with multiple BPMs:

```text
δs = sum_i wi Dxi (xi - xi,ref) / sum_i wi Dxi^2
```

The Stage 1 analysis scaffold implements this first-order least-squares form.

The higher-order extension is:

```text
xi - xi,ref = D1,i δs + D2,i δs^2 + D3,i δs^3 + ...
```

That is not yet fitted automatically, but the logger is designed to capture the
machine data needed for it later.

## Global vs Local Quantities

Keep these distinct:

- global `α0`, `α1`, `α2`, ...
- local `Dx`, `Dx'`, `Hx`
- local transport quantities such as `R56`, `T566`

Do not confuse `R56` with `α0`:

- `α0` is global normalized momentum compaction
- `R56` is a local/section path-length sensitivity

## Undulator And L4 Interpretation

RF scans change `δs`, and therefore change the dispersive closed orbit. If the
L4 bump changes local position and angle at the undulator, then an observed
signal change can mix:

- true longitudinal timing / phase-slip effects
- beam-laser overlap changes from orbit geometry

This is why the logger captures:

- RF
- tunes
- optics mode
- orbit-correction state
- BPM candidates around U125 and L4
- sextupole and octupole settings

today, even before the radiation monitor is integrated.
