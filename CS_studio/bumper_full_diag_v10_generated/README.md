# SSMB PoP-II CS-Studio diagnostics v10 (generated)

This package is generated from `phoebusgen/ssmb_views.py` so the working PV list,
operator labels, and formula definitions stay consistent. The older working files remain
untouched:

- `../orignal--leo_20260502_SSMB_PoPII_scanshots.plt`
- `../bumper_full_diag_v9/`

## Open order in the control room

1. `00_raw_sanity_no_formulas_10min.plt`
2. `99_formula_smoke_test_open_first.plt`
3. `01_core_operator_overview_10min.plt`
4. `02_u125_orbit_offset_angle_30min.plt`
5. `03_bumper_alpha0_machine_30min.plt`
6. `04_signal_qpd_rf_laser_30min.plt`

## Key additions relative to v9

- generator-driven `.plt` files instead of hand-editing;
- explicit `Q1P1L2RP:setCur` tracking for alpha0 scans;
- inferred U125 center / consistency traces so you can see whether the undulator beam line stays sane;
- percent-deviation QPD traces so small optics changes do not flatten;
- shot-window and laser-setting proxies included as visible context:
  - `SCOPE1ZULP:rdAvLength`
  - `WFGEN2C1CP:setVolt`
  - `WFGEN2C1CP:stOut`

## Important caveats

- Exact shot-count PV is still unverified in this repo. `SCOPE1ZULP:rdAvLength` is used as a practical averaging / shot-window proxy.
- Exact polarization-plate / laser-power PV chain is still unverified. `WFGEN2C1CP:setVolt` and `WFGEN2C1CP:stOut` are kept as candidate laser-setting context PVs because they already appear in the working control-room views.
- Tune monitor values are treated as baseline-relative monitor counts, not as already-calibrated machine tune values.

## Baselines used for deviation plots

| Quantity | Baseline |
|---|---:|
| BPM3 X | -0.069500 mm |
| BPM4 X | -0.175000 mm |
| BPM5 X | -0.757800 mm |
| BPM6 X | -0.169200 mm |
| BPM3 Y | -0.142800 mm |
| BPM4 Y | -0.167000 mm |
| BPM5 Y | -0.052900 mm |
| BPM6 Y | -0.029000 mm |
| Q1 current | 21.423130 A |
| RF readback | 687.462000 |
| Energy ramp | 250.000000 |

## What each generated view is for

### `01_core_operator_overview_10min.plt`

Use this during the live scan. The black trace is the main `P1` signal. The stacked colored traces deliberately magnify small drifts:

- blue: mean U125 horizontal orbit drift;
- green: horizontal angle mismatch across U125;
- orange: vertical angle mismatch across U125;
- red: U125 horizontal consistency (downstream minus upstream extrapolation);
- pink: U125 vertical consistency;
- cyan: bumper-strength proxy `ΔΣI²`;
- brown: `ΔQ1`;
- olive: `QPD01 sigmaX` percentage change.

### `02_u125_orbit_offset_angle_30min.plt`

Use this when you need to answer: *is the beam position/angle near the undulator becoming too crazy while Q1 or the bumper changes?*

### `03_bumper_alpha0_machine_30min.plt`

Use this when scanning the global quads. It keeps `Q1P1L2RP:setCur`, the four bumper steerers, `AKC12VP`, and the `MNF*` controls in one place.

### `04_signal_qpd_rf_laser_30min.plt`

Use this when you want to compare signal changes against profile-size changes, RF drift, and the best currently known shot-window / laser-setting proxies.

## What to test first in the control room

1. Open `00_raw_sanity_no_formulas_10min.plt`.
2. Verify `P1`, BPMs, steerers, `Q1P1L2RP:setCur`, and QPD sigmas all update.
3. Open `99_formula_smoke_test_open_first.plt`.
4. If the formula trace works, move to `01_core_operator_overview_10min.plt`.
5. While changing `Q1P1L2RP:setCur`, watch whether `Δx′`, `Δy′`, and U125 consistency stay quiet.
6. If they do not, open `02_u125_orbit_offset_angle_30min.plt` and `03_bumper_alpha0_machine_30min.plt` side by side.

## Regenerate after edits

```bash
cd /path/to/betagui
python3 CS_studio/generate_ssmb_cs_plots.py
```
