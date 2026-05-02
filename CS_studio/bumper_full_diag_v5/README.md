
# SSMB PoP-II CS-Studio bumper diagnostics repo v5

Open order:

1. `04_raw_sanity_check_no_formulas_10min.plt` — verifies PV connectivity, no formulas.
2. `00_core_overview_10min.plt` — compact live scan dashboard.
3. `01_u125_orbit_angle_detail_30min.plt` — U125 BPM/angle details.
4. `02_bumper_machine_tune_detail_30min.plt` — steerers, tune shifts, RF/machine optional traces.
5. `03_qpd_signal_detail_30min.plt` — QPD/profile and coherent signal.
6. `theory.md` — equations, thresholds, interpretation.

Formula traces are now real `<formula>` entries with `<input>` PVs, matching the syntax from your modified file. The raw PV dependencies are also included as hidden traces in the same files so the Data Browser logs their values while showing only the derived diagnostics.

Visible time windows are short (`-10 minutes` or `-30 minutes`) but `ring_size` is large (`259200`) for long live history buffering.
