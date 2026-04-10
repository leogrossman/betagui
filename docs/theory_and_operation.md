# Theory And Operation

This document explains what the tool is for, how the main calculation works,
and how the different GUI paths relate to machine operation.

## Purpose Of The Script

The original `betagui.py` is a small MLS control-room GUI for chromaticity work.
It combines four operator tasks in one tool:

1. measure chromaticity by sweeping RF and observing tune changes
2. measure a sextupole response matrix
3. apply small chromaticity corrections through sextupole families
4. perform a secondary sextupole scan study and log candidate settings

The Python 3 port keeps that operational scope while separating machine access
from logic that can be tested offline.

## Main Physical Idea

Chromaticity describes how tune changes with relative momentum deviation. In the
legacy tool, momentum deviation is not measured directly. Instead, the script:

1. changes the RF frequency
2. infers the corresponding momentum offset using `alpha0`
3. measures tune-like readbacks for `x`, `y`, and `s`
4. fits tune readback versus RF offset
5. converts the fitted slope into `xi`

## Main Variables In The Legacy Script

- `frf0`: saved reference RF frequency
- `alpha0`: momentum compaction factor
- `Nharmonic = 80`: MLS harmonic number
- `Dmax`: machine dispersion scale selected from the optics table
- `B`: inverse response matrix used for sextupole correction

## RF Range Calculation

The GUI takes minimum and maximum orbit-displacement tolerances in millimeters.
The code converts those to an RF sweep range using:

```text
frf_max = frf0 + (-dx_min * alpha0 * frf0 / Dmax)
frf_min = frf0 - ( dx_max * alpha0 * frf0 / Dmax)
```

where:

- `dx_min`, `dx_max` are the requested displacement bounds in meters
- `alpha0` is the momentum compaction factor
- `Dmax` is selected from the optics-mode PV

This is kept close to the original code.

## Dynamic `alpha0` Calculation

When `alpha0` is set to `dynamic`, the code estimates it from synchrotron tune,
RF, cavity voltage, and beam energy:

```text
alpha0 =
    (fs * 1000)^2 / (frf * 1000)^2
    * 2 * pi * h * E / Ucav
```

with:

- `fs`: synchrotron tune-like frequency readback in kHz
- `frf`: RF frequency readback
- `h`: harmonic number
- `E`: beam energy in eV
- `Ucav`: cavity voltage in V

This formula is inherited from the legacy code. The Python 3 port keeps the same
structure and only adds error handling around missing PVs.

## Tune Averaging

At each RF point, the script reads the tune channels multiple times and averages
them. The Python 3 port trims one highest and one lowest sample when there are
enough points, which is the intended effect of the legacy code after repairing
its broken `np.delete(...)` usage.

## Polynomial Fit And Chromaticity Extraction

For each of the tune channels `x`, `y`, and `s`, the script fits a polynomial:

```text
Q(delta_frf) = poly(delta_frf)
```

The chromaticity-like result is then extracted from the slope near zero RF
offset:

```text
xi = - (dQ / dfrf) * frf0 * alpha0 / frev
```

where `frev` is the revolution frequency scale used by the legacy script.

In the Python 3 port, the slope is taken from the derivative of the fitted
polynomial at zero RF offset, which is the stable way to recover the same
intended result.

## Response Matrix Measurement

The matrix workflow perturbs one sextupole family group at a time, measures
chromaticity before and after the step, and builds a finite-difference matrix:

```text
A[i, :] = xi_after - xi_before
```

The correction matrix displayed in the GUI is then:

```text
B = inverse(transpose(A))
```

This is kept directly recognizable from the legacy code.

## Manual Sextupole Correction

The `+/-` correction buttons define a desired `dXi` vector and apply:

```text
dI = B * dXi
```

The resulting current increments are written to the sextupole family PVs using
the same family grouping logic as the legacy tool.

## Secondary Scan Window

The secondary `sext scan` window has two purposes.

### Polynomial Response Measurement

For each family group, the script scans current over a configured range and
measures:

- the family current settings
- `xi_x`
- `xi_y`
- `xi_s`

It then fits the model:

```text
dXi = p1 * dI^2 + p2 * dI
```

with zero intercept, matching the legacy helper `bumppolyfit(...)`.

### Scan-Table Generation

After a polynomial matrix is measured, the script scans a grid in the four
family variables:

- `S1`
- `S2P1`
- `S2P2`
- `S3`

For each grid point it computes predicted `dXi_x` and `dXi_y`, keeps the points
inside the requested ranges, and writes candidate sextupole settings to disk.

When writes are enabled, it can also step through those candidates and log the
same diagnostics that the legacy code intended to record.

## Machine State Changes

The important write paths are:

- RF setpoint ramping
- feedback disable / restore
- orbit mode changes
- sextupole current changes
- phase modulation reset

These are all documented in
[write_paths.md](write_paths.md).

## What The Tool Is Not

This is not a full accelerator application framework. It is intentionally still
a compact operator tool with simple modules around it. The repo adds offline and
digital-twin support for development, but the control-room path remains centered
on the legacy EPICS workflow.
