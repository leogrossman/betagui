# SSMB

This folder is the separate SSMB tool area. Treat it as a small standalone
workspace inside the larger repo.

Normal control-room use:

```bash
cd SSMB
python3 ssmb_gui.py
```

Write-capable RF sweep mode:

```bash
cd SSMB
python3 ssmb_gui.py --allow-writes
```

## Today’s Measurements

Use the GUI presets and labels for these three jobs:

1. Low-alpha full passive log
   Run one read-only session with the machine in low-alpha mode to capture RF,
   tunes, BPMs, magnet currents, beam-size proxies, and related machine state
   for later `δs(fRF)` and `α` analysis.

2. Bump OFF / bump ON passive comparison
   Run one read-only session with the bump externally set to OFF, then one with
   the bump externally set to ON. The script does not switch the bump. It only
   logs the state so you can compare the old synchrotron-tune-based `α0` proxy
   and the off-momentum orbit response later.

3. RF sweep with logging
   After the passive logs look sane, run one RF sweep while logging everything.
   Do this once with bump OFF and once with bump ON if time allows. The RF
   sweep tab uses direct `Hz` offsets and shows the exact RF PV values before
   any write. Writes only run if you started the GUI with `--allow-writes` and
   then confirm the popup.

Recommended order:

1. `low_alpha`
2. `bump_off`
3. `bump_on`
4. `rf_sweep_bump_off`
5. `rf_sweep_bump_on`

Local runtime data stays under:

```text
SSMB/.ssmb_local/
```

That directory is gitignored, so normal `git pull` will not touch your local
SSMB logs.

Relevant contents:

- `ssmb_gui.py`
  single operator-facing GUI entrypoint
- `ssmb_tool/`
  internal implementation
- `MLS_lattice/`
  lattice exports and briefing material
