# CS_studio Phoebus generator

This folder contains the long-term maintainable generator for the SSMB PoP-II CS-Studio
Data Browser views.

Main entrypoint:

```bash
python3 CS_studio/generate_ssmb_cs_plots.py
```

The generator reads exported control-room `.txt` files to estimate baseline values, then
builds a generated `bumper_full_diag_v10_generated/` package with:

- raw sanity view;
- formula smoke test;
- operator overview;
- U125 orbit/offset/angle detail;
- bumper/Q1/machine context;
- signal/QPD/RF/laser-context view;
- README, theory, and PV map.
