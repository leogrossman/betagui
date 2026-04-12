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

## Recommended Environment

This tool was validated against the repo-style `pyenv` environment:

- Python `3.9.0`
- `pyenv` env name: `betagui`

Recommended startup:

```bash
cd SSMB_experiment
export MPLCONFIGDIR="$PWD/.ssmb_local/mplconfig"
~/.pyenv/versions/betagui/bin/python ssmb_experiment_gui.py
```

Write-capable RF sweep mode:

```bash
cd SSMB_experiment
export MPLCONFIGDIR="$PWD/.ssmb_local/mplconfig"
~/.pyenv/versions/betagui/bin/python ssmb_experiment_gui.py --allow-writes
```

## Recommended Measurement Flow

Suggested control-room order:

1. `low_alpha`
2. `bump_off`
3. `bump_on`
4. `rf_sweep_bump_off`
5. `rf_sweep_bump_on`

Use the GUI presets and labels for three main jobs:

1. Low-alpha full passive log
   Capture RF, tunes, BPMs, magnet currents, and beam-size proxies for later
   `δ_s(f_RF)` and `α` analysis.

2. Bump OFF / bump ON passive comparison
   Run passive sessions with the bump externally configured OFF and ON. The
   script only logs the state; it does not switch the bump itself.

3. RF sweep with rich logging
   Run one RF sweep with bump OFF, and one with bump ON if time allows.
   Writes only happen if you start the GUI with `--allow-writes` and confirm.

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
~/.pyenv/versions/betagui/bin/python -m pytest SSMB_experiment/tests
```

To also verify the original SSMB path still behaves:

```bash
cd /path/to/betagui
~/.pyenv/versions/betagui/bin/python -m pytest \
  tests/test_ssmb_analysis.py \
  tests/test_ssmb_gui_import.py \
  tests/test_ssmb_stage0.py \
  tests/test_ssmb_sweep.py
```

## Rollback

If the experiment path misbehaves in the control room, switch back immediately:

```bash
cd ../SSMB
~/.pyenv/versions/betagui/bin/python ssmb_gui.py --allow-writes
```

No changes to the original `SSMB/` folder are required for that rollback.
