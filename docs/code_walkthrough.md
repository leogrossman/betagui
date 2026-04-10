# `original/betagui.py` Code Walkthrough

## Overview

`original/betagui.py` is a single-file Tkinter application for MLS chromaticity work. It combines:

- GUI construction
- EPICS PV creation and access
- RF sweep based chromaticity measurement
- sextupole response-matrix measurement
- manual chromaticity correction through a loaded/measured matrix
- a secondary sextupole scan / polynomial-fit window
- ad hoc file save/load operations

The file is 1065 lines long and is tightly coupled to live machine access.

## Startup Behavior

At import time the script immediately:

- imports `Tkinter`, `tkFileDialog`, `matplotlib`, `numpy`, `scipy`, and `epics`
- configures matplotlib with LaTeX text rendering
- creates many EPICS PV objects
- performs `.get()` calls on RF, tune, sextupole, feedback, and orbit PVs
- creates a global `Tk()` root window

This means import is not safe in a headless or offline environment. The code assumes the control-room runtime environment is already present.

## Global State

Important globals near the top:

- `runD`: coarse stop flag checked by worker threads
- `Nharmonic`: harmonic number used in `cal_alpha0()`
- `frf0`: saved RF reference value from startup or `save_setting()`
- `ini_sext`: saved sextupole settings
- `ini_fdb`: saved feedback states
- `ini_orbit`: saved orbit mode readback
- `B`: inverse response matrix used for manual correction
- `bump_option`, `bump_dim`, `mat_status`, `flag2D3D`: matrix/correction mode state

The script uses globals heavily instead of passing state explicitly.

## PV Setup Section

The top section defines PV objects for:

- tune readback
- RF setpoint
- sextupole set currents
- orbit and feedback control
- optics mode
- lifetime/current/beam-size diagnostics

Several PV names imply write capability because they use `set*`, `cmd*`, or control-style names. The script later writes to many of them directly.

## `save_setting()`

Purpose:

- snapshot the current machine state into globals

Reads:

- sextupole set currents
- feedback states
- RF setpoint
- orbit readback

Writes:

- no EPICS writes
- only updates Python globals

This is the state later used by the reset button.

## `bumppolyfit(X, p1, p2)`

Purpose:

- quadratic fit constrained to zero intercept

Used in:

- the sextupole polynomial scan window

Model:

- `p1 * x^2 + p2 * x`

## `set_all2ini(...)`

Purpose:

- restore the saved machine state

Machine actions:

- ramp RF back to `frf0`
- restore all saved sextupole currents
- restore feedback states
- restore orbit mode
- disable external phase modulation

This is a direct machine-state restore path.

## `set_frf_slowly(target_frf_in_Hz)`

Purpose:

- ramp the RF setpoint in 10 linear steps

Behavior:

- reads current RF
- linearly interpolates to the target
- writes each step with `0.2 s` delay

This helper is central to chromaticity measurement and reset.

## `set_Isextupole_slowly(...)`

Intended purpose:

- ramp a sextupole current slowly

Current state:

- broken / unusable

Problems:

- argument `sname` is treated as both PV name string and PV object
- local `pvSextupole` is never used
- `aself` is undefined
- no working caller in the main flow

This looks like abandoned code.

## `set_sext_degauss(...)`

Purpose:

- oscillate sextupole current around a target before settling to final value

Behavior:

- builds alternating sequence between `target-2` and `target+2`
- writes that sequence to each PV in `sextlist`
- then writes final target

Suspicious detail:

- it also unconditionally writes `pvS1P1` and `pvS1P2` at the end, even if those are not in `sextlist`

I did not find a live caller in the main runtime flow.

## `cal_alpha0()`

Purpose:

- estimate momentum compaction-like `alpha0`

Reads:

- 10 samples of synchrotron tune
- RF setpoint
- cavity voltage PV `PAHRP:setVoltCav`
- ramp/energy PV `ERMPCGP:rdRmp`

Formula:

- `alpha = (fs/frf)^2 * 2π * h * E / U`

Notes:

- units are not documented clearly
- comments and variable names disagree on Hz/kHz in several places

## `BPDM()`

Intended purpose:

- return BPM positions and orbit data

Actual current behavior:

- returns hard-coded BPM longitudinal positions
- returns an all-zero orbit vector

The waveform decode path is commented out, so orbit plotting in the GUI is presently synthetic.

## `set_all_sexts(delta_chrom)`

Purpose:

- apply manual chromaticity correction using matrix `B`

Behavior:

- computes `MI = B * delta_chrom`
- increments one or more sextupole families depending on `mat_status`

Modes:

- `mat_status` selects 2D/3D and P2/non-P2 combinations

This is the core machine write path for the manual correction buttons.

## `MeaChrom(...)`

Purpose:

- perform chromaticity measurement by sweeping RF and fitting tune response

High-level flow:

1. Disable measurement/correction buttons.
2. Turn off X/Y/S feedback and orbit correction by writing zeros.
3. Determine `alpha0` either dynamically or from GUI entry.
4. Compute RF scan range from user input and optics mode.
5. For each RF point:
   - ramp RF
   - wait
   - read tunes multiple times
   - remove extremes if enough samples
   - fit tune vs RF offset
   - update plots
6. Restore RF to `frf0`.
7. Restore feedback and orbit states.
8. Compute and annotate measured chromaticities.

Important observations:

- `delayMeasTune` is read from the GUI but never used
- `nmeasurements` is reduced in place inside the loop, so later RF points use fewer tune samples
- `BPDM()` returns zeros, so the orbit subplot is not a real orbit plot
- RF, feedback, and orbit writes happen inside this function

This is the main operational routine in the tool.

## `mainwindow.__init__`

Purpose:

- build the full GUI

Main UI regions:

- left input panel for chromaticity measurement parameters
- center matrix panel for measuring/loading/saving the response matrix
- lower correction panel for manual chromaticity bumps
- right side button column
- bottom matplotlib figure area

This method is large because most application behavior is implemented as nested functions inside it.

## Nested Function: `start_mea(...)`

Purpose:

- launch `MeaChrom()` in a background thread

Notes:

- GUI objects are passed straight into the worker
- plotting and widget updates occur from the worker thread, which is risky in Tkinter

## Nested Functions: `save_matrix()` and `load_matrix()`

Purpose:

- save/load matrix `B` to/from text files

File format:

- first row stores a mode marker (`0001`, `0002`, `0003`, `0004`)
- remaining rows store the matrix

Notes:

- loading a matrix enables manual correction buttons
- matrix save/load is purely file-based and does not directly change PVs

## Matrix Mode Controls

The GUI offers four bump options:

- `2D`
- `2D(P2)`
- `3D`
- `3D(P2)`

These determine:

- which sextupole families are stepped during matrix measurement
- which sextupole families are written during manual correction

The displayed sextupole label combinations are:

- `S1,S2`
- `S1P2,S2P2`
- `S1,S2,S3`
- `S1P2,S2P2,S3P2`

## Nested Function: `SetCor()`

Purpose:

- switch between using the full 3x3 correction matrix and a derived 2x2 matrix

Behavior:

- in 2D mode, it inverts `B`, takes the top-left 2x2 block, then inverts again
- stores the old `B` in `Bbuf`

Risks:

- no singular-matrix handling
- assumes `B` already contains a valid invertible matrix

## Nested Function: `start_bump(...)`

Purpose:

- measure the sextupole response matrix

High-level flow:

1. Disable matrix/correction controls.
2. Choose sextupole family groups from bump mode.
3. For each dimension:
   - step the selected sextupoles by `-1 A`
   - measure chromaticity
   - step back by `+1 A`
   - measure again
   - store the chromaticity difference
4. Form matrix `A`.
5. Compute `B = inv(A.T)`.
6. Display and enable correction controls.

Important notes:

- this routine calls `MeaChrom()`, so it also writes RF, feedback, and orbit states
- there is no guaranteed restoration of sextupole settings to the original baseline if the process is interrupted mid-run
- inversion errors are not handled

## Nested Function: `change_sext_cur(Nth)`

Purpose:

- manual `+/- xi_x`, `+/- xi_y`, `+/- xi_s` adjustment

Behavior:

- reads desired chromaticity increment from entry fields
- updates a GUI readout
- constructs `dchrom`
- calls `set_all_sexts(dchrom)`

This is a direct operator-triggered machine write path.

## Main Window Buttons

Buttons in the right-side column:

- `Save`: calls `save_setting()`
- `Quit`: exits Tk main loop
- `reset`: calls `set_all2ini(...)`
- `sext scan`: opens secondary window
- `Stop`: sets global stop flags

## `newWindow()`

Purpose:

- create the secondary sextupole scan window

It contains two distinct workflows:

- polynomial response measurement (`start_poly`)
- scan-table generation plus diagnostic logging (`gen_scan_tab`)

## Nested Function: `start_poly(...)`

Intended purpose:

- scan selected sextupole currents
- measure chromaticity response
- fit quadratic coefficients
- save raw data and coefficient matrix

Observed problems:

- references `setcur(...)`, which is not defined anywhere in the file
- uses `pvS2P2`, while the main matrix logic mostly uses split PVs `pvS2P2K` and `pvS2P2L`
- expression `bumpdataS[-float(paras[i][1].get())-1,:]` is almost certainly invalid
- indentation is inconsistent in the original source

This feature is not in a safely usable state.

## Nested Function: `gen_scan_tab()`

Purpose:

- derive candidate sextupole settings from a polynomial matrix and target chromaticity windows
- log diagnostics for those candidate settings

Current behavior:

- loads a coefficient matrix from disk
- enumerates candidate settings
- writes results to a timestamped directory
- reads diagnostics repeatedly and saves them to per-setting data files

Important note:

- the sextupole write commands inside this function are commented out
- so this section currently logs diagnostics for the current machine state rather than applying each candidate setting

Likely bugs:

- `ndd` is taken from row 2 instead of row 3
- `Sc` and `Sd` use the minimum value for both endpoints, so those axes never scan

## Program Entry Point

At the bottom:

- `root = Tk()` is executed at import time
- `main()` creates `mainwindow(root)` and runs `root.mainloop()`

For a Python 3 port intended to work offline, this should be made lazy so import does not require Tk, display access, or EPICS connectivity.
