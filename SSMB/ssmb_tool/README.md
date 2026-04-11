# SSMB Tool

Separate MLS SSMB development tool, kept isolated from the main `betagui`
implementation so it can later be extracted into its own repository.

## Stage 0

Priority today is passive logging for later reconstruction of:

- synchronous off-momentum state `δs(fRF)`
- slip factor `η`
- inferred `α0`
- later nonlinear momentum compaction terms

Default behavior is fully read-only.

## Quick Start

From the repo root:

```bash
python3 -m SSMB.ssmb_tool log-now --duration 60 --sample-hz 1
```

Or use the separate GUI:

```bash
python3 -m SSMB.ssmb_tool gui
```

For an explicit write-capable RF sweep:

```bash
python3 -m SSMB.ssmb_tool rf-sweep \
  --center-rf-pv 499652.5 \
  --delta-min-hz -100 \
  --delta-max-hz 100 \
  --points 5 \
  --allow-writes
```

This creates a timestamped session directory under:

```text
./control_room_outputs/ssmb_stage0/
```

with:

- `metadata.json`
- `samples.jsonl`
- `samples.csv`
- `session.log`

## Outputs

`samples.jsonl` keeps the full read-only sample payload, including array-like
channels such as the legacy BPM buffer if available.

`samples.csv` contains flattened scalar data plus waveform summary columns.

The GUI shows a live inventory preview so you can inspect exactly what will be
logged before starting a session. Use the session label and note fields to tag
runs such as `bump_on` and `bump_off`.

## Analysis

Offline analysis scaffold:

```bash
python3 -m SSMB.ssmb_tool analyze control_room_outputs/ssmb_stage0/SESSION_DIR
```

If you already have a first-order dispersion map for selected BPMs:

```bash
python3 -m SSMB.ssmb_tool analyze SESSION_DIR --dispersion-json dispersion.json
```

## Control-Room Safety

- no writes are implemented in Stage 0
- missing PVs do not abort the session
- unverified optional experiment PVs stay disabled unless you pass them
- BPM candidate PVs are derived from the lattice export and may legitimately log
  `null` if the actual EPICS naming differs
- RF sweep execution is separate, opt-in, and previews exact RF PV values before
  any write
- RF sweep inputs are direct `Hz` offsets rather than the legacy chromaticity
  `mm` proxy inputs

## Main Files

- `log_now.py`: Stage 0 passive logger
- `analyze_session.py`: Stage 1 offline analysis scaffold
- `gui.py`: separate Stage 0 / RF sweep GUI
- `sweep.py`: explicit RF sweep with full logging
- `inventory.py`: machine/logging channel inventory
- `lattice.py`: lattice export loading and region selection
- `THEORY.md`: physics motivation and equations
- `ROADMAP.md`: staged implementation plan
