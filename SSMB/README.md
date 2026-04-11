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
