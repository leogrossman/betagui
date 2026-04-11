# SSMB

This folder contains SSMB-specific work kept separate from the main `betagui`
control-room tool.

## Contents

- `MLS_lattice/`
  lattice exports, element tables, and briefing material used as machine
  reference context
- `ssmb_tool/`
  new separate SSMB development tool focused on passive logging and later
  off-momentum / momentum-compaction reconstruction

## First Command

From the repo root:

```bash
python3 -m SSMB.ssmb_tool log-now --duration 60 --sample-hz 1
```

Then read:

- `ssmb_tool/README.md`
- `ssmb_tool/THEORY.md`
- `ssmb_tool/ROADMAP.md`
