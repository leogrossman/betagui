# SSMB Tool Roadmap

## Stage 0: Passive Logging

Implemented now.

Goal:

- capture all immediately useful machine state without writing anything
- keep output simple enough to inspect at home the same day

Outputs:

- `metadata.json`
- `samples.jsonl`
- `samples.csv`
- `session.log`

## Stage 1: Offline Reconstruction

Implemented partially now.

Current:

- first-order `δs` reconstruction helper from BPM + dispersion
- slip-factor fit
- `α0` inference from `η`
- simple analysis report and plots

Still needed:

- automated use of real MLS dispersion maps
- robust nonlinear fitting for `α1`, `α2`

## Stage 2: Read-Only SSMB Monitor

Future.

Target:

- live read-only monitor oriented around `δs`, `η`, `α0` proxy, RF/tune state,
  bump/orbit context, and undulator-region diagnostics

## Stage 3: Explicit Write-Capable Scan Support

Not implemented.

Target:

- opt-in only
- scripted RF scans
- scripted bump scans
- explicit restore/snapshot discipline

## Out Of Scope For Today

- radiation monitor / scope integration
- fully automated machine control
- advanced GUI polish
- final nonlinear longitudinal model fitting
