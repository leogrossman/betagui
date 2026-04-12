# SSMB_experiment

`SSMB_experiment` is a control-room-safe copy of the `SSMB` tooling with extra
instrumentation for RF sweep studies.

Use it when you want:

- richer logging than the standard `SSMB/` workflow
- live derived quantities during an RF sweep
- bundled MLS lattice context for the current SSMB study
- a safer rollback path because the original `SSMB/` tree stays untouched

The fallback remains the original `SSMB/` folder.

Recovered from the bump-correction notebook, the present L4 bump uses four
horizontal corrector dipoles rather than the main ring dipoles:

- `HS1P2K3RP:setCur`
- `HS3P1L4RP:setCur`
- `HS3P2L4RP:setCur`
- `HS1P1K1RP:setCur`

Those correctors appear to be integrated as local corrector windings inside
sextupole packages. The same notebook also uses these controller PVs:

- `AKC10VP`
- `AKC11VP`
- `AKC12VP`
- `AKC13VP`
- `MCLKHGP:ctrl:enable`

and averages these BPMs for bump feedback:

- `BPMZ1K1RP:rdX`
- `BPMZ1L2RP:rdX`
- `BPMZ1K3RP:rdX`
- `BPMZ1L4RP:rdX`

## What This Adds

Compared with the baseline `SSMB/` tool, this experiment copy adds:

- a read-only live monitor tab and pop-out window for pre-experiment viewing
- preference for the bundled `ssmb_250mev` lattice export
- live first-order `δ_s` reconstruction from the L4 BPM set
- live slip-factor and BPM-based `α₀` estimates during RF sweeps
- first-order spread proxies from `QPD00ZL4RP`
- SSMB-oriented RF sweep presets tuned for low-risk control-room use
- local bundled lattice images and exports for quick reference

Primary L4 BPM set used for first-order momentum reconstruction:

- `BPMZ3L4RP`
- `BPMZ4L4RP`
- `BPMZ5L4RP`
- `BPMZ6L4RP`

`BPMZ7L4RP` is intentionally not part of the primary estimator.

Verified profile/beam-screen monitor names:

- `QPD00ZL4RP` (`QPD00`, alias noted as `qpdz0rp`) in L4
- `QPD01ZL2RP` (`QPD01`, alias noted from the control-room screen) in L2

Confirmed from copied control-room scripts:

- both QPD devices behave like synchrotron-radiation camera / profile monitors
- direct channels seen in scripts include `rdSigmaX` and `rdSigmaY`
- archived averaged channels seen in old logs include:
  - `QPD00ZL4RP:rdSigmaYav`
  - `QPD01ZL2RP:rdSigmaYav`

## Runtime Layout

Local runtime output stays under:

```text
SSMB_experiment/.ssmb_local/
```

That includes logs, sweep sessions, and a local Matplotlib cache. It is meant
to be machine-local runtime state, not source-controlled content.

Session directories are timestamped and unique. Runtime logs live under the
gitignored `.ssmb_local/` tree, so a normal `git pull` should not overwrite
captured data.

## Control-Room Startup

In the control room, prefer the machine's local Python and the checked-out repo
directly. Do not rely on `pyenv` there unless you explicitly need it as a
fallback.

Recommended standard startup:

```bash
cd SSMB_experiment
export MPLCONFIGDIR="$PWD/.ssmb_local/mplconfig"
python3 ssmb_experiment_gui.py
```

Safer passive / read-only startup:

```bash
cd SSMB_experiment
export MPLCONFIGDIR="$PWD/.ssmb_local/mplconfig"
python3 ssmb_experiment_gui.py --safe-mode
```

Notes:

- the standard launch starts with `Safe / read-only mode` enabled
- to actually write RF commands, you must first turn off `Safe / read-only mode`
  inside the GUI
- `--safe-mode` is kept as a compatibility flag and behaves the same as the
  standard launch
- if you ever want the GUI to open with writes immediately available, use:
  `python3 ssmb_experiment_gui.py --unsafe-start`
- passive logging does not write any PVs
- RF sweep writes stay blocked until:
  - `Safe / read-only mode` is turned off
  - the write confirmation popup is accepted
- the confirmation dialog shows the exact planned RF PV writes before anything
  is sent
- even in standard write-capable startup, the `Safe / read-only mode` checkbox in
  the GUI can be used at any time to block writes again

## Environment Notes

This tool was validated against Python `3.9.0`, matching the original
`betagui` development environment. If the control-room machine already has a
working local `python3`, use that first.

If you ever need the older repo-style fallback, the validated `pyenv`
interpreter was:

- `~/.pyenv/versions/betagui/bin/python`

## Recommended Measurement Flow

Suggested control-room order:

1. start the live monitor and inspect machine state before the experiment
2. `low_alpha`
3. `bump_off`
4. `bump_on`
5. `rf_sweep_bump_off`
6. `rf_sweep_bump_on`

Use the monitor tab when you want read-only live feedback without saving a
session yet. Use logging or RF sweep mode only when you want a recorded
measurement.

## Live Monitor

The `Live Monitor` tab is read-only and can be used even when the RF sweep is
being driven elsewhere.

It gives you:

- live preview of the same core PVs without writing or saving
- a full current channel snapshot for the configured logging profile
- live detection of whether the 4-corrector L4 bump is active
- live `δ_s` estimate from the L4 BPM set
- live BPM-based beam-energy estimate
- live QPD00-based first-order `σ_δ` and `σ_E` proxies
- live tune readout and synchrotron-monitor readout
- automatic RF-motion detection
- automatic live `η`, BPM-based `α₀`, and tune-vs-`δ` slope estimates once RF
  motion is detected
- a pop-out clickable lattice/device window with live values for lattice devices,
  QPD monitors, and recovered bump hardware

The pop-out monitor window is useful if you want the live readout on a second
screen while using the logger or sweep tabs.

What you can estimate without RF sweep:

- tunes and synchrotron monitor
- beam current
- bump state and corrector state
- L4 BPM orbit offsets
- first-order `δ_s` relative to the monitor baseline
- BPM-based beam energy shift
- QPD00-based first-order momentum-spread proxy

What becomes available once RF moves:

- slip factor `η`
- BPM-based `α₀`
- tune slopes versus `δ_s` as chromaticity cross-checks

Use the GUI presets and labels for three main jobs:

1. Low-alpha full passive log
   Capture RF, tunes, BPMs, magnet currents, and beam-size proxies for later
   `δ_s(f_RF)` and `α` analysis.

2. Bump OFF / bump ON passive comparison
   Run passive sessions with the bump externally configured OFF and ON. The
   script only logs the state; it does not switch the bump itself.

3. RF sweep with rich logging
   Run one RF sweep with bump OFF, and one with bump ON if time allows.
   Writes only happen if `Safe / read-only mode` is off and you confirm the
   planned PV commands.

## RF Sweep Preset

The built-in SSMB RF-sweep preset is:

- `-20 Hz` to `+20 Hz`
- `11` points
- `5` samples per point
- `1.2 s` settle
- `0.25 s` spacing
- raw BPM waveform disabled by default

This is deliberately conservative to reduce PV load while still giving useful
statistics at each RF point.

## Live Derived Quantities

During a sweep, the run log summarizes:

- `δ_s` from the L4 BPM set
- BPM-based beam energy
- corrected legacy `α₀`
- running `η`
- running BPM-based `α₀`

The GUI also keeps a live `BPM Nonlinearity Watch` panel:

- green: `|x| < 3 mm`
- yellow: `3 mm <= |x| < 4 mm`
- red: `|x| >= 4 mm`

That warning never stops the logger or sweep. It only flags that a BPM may be
entering a nonlinear orbit-response regime during the RF scan.

Those values are intended as live operator guidance, not the final publication
analysis. The final numbers should still come from offline fitting.

## Key Files

- `ssmb_experiment_gui.py`
  operator-facing GUI entrypoint
- `ssmb_tool/`
  experiment implementation
- `ssmb_tool/THEORY.md`
  theory notes and analysis motivation
- `MLS_lattice/`
  bundled lattice exports and plots
- `tests/`
  experiment-specific regression and smoke tests

## Testing

Run the self-contained `SSMB_experiment` tests:

```bash
cd /path/to/betagui
python3 -m pytest SSMB_experiment/tests
```

To also verify the original SSMB path still behaves:

```bash
cd /path/to/betagui
python3 -m pytest \
  tests/test_ssmb_analysis.py \
  tests/test_ssmb_gui_import.py \
  tests/test_ssmb_stage0.py \
  tests/test_ssmb_sweep.py
```

If the control-room machine does not have the needed packages on its default
`python3`, then fall back to the validated `pyenv` interpreter.

## Rollback

If the experiment path misbehaves in the control room, switch back immediately:

```bash
cd ../SSMB
python3 ssmb_gui.py --allow-writes
```

No changes to the original `SSMB/` folder are required for that rollback.
