# CS_studio in betagui

This folder now contains both the older hand-edited CS-Studio Data Browser views and a new generated path.

## Keep these as historical working references

- `orignal--leo_20260502_SSMB_PoPII_scanshots.plt`
- `bumper_full_diag_v9/`

## Recommended current path

- generated package: `bumper_full_diag_v10_generated/`
- generator source: `phoebusgen/ssmb_views.py`
- CLI entrypoint: `generate_ssmb_cs_plots.py`

## Regenerate after edits

```bash
cd /path/to/betagui
python3 CS_studio/generate_ssmb_cs_plots.py
```

## Why v10 exists

`v9` proved the XML formula + hidden dependency approach works, but it is hard to maintain by hand and the scaling logic had become difficult to read. The generated `v10` package keeps the same proven formula style while making it easier to:

- add PVs such as `Q1P1L2RP:setCur`;
- preserve the working originals;
- keep axis scaling and labels consistent;
- regenerate all `.plt` files and docs from one source of truth.
