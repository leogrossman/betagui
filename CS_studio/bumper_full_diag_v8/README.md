# SSMB PoP-II CS-Studio diagnostics repo v8

This version fixes the formula problem by using CS-Studio `<formula>` blocks with explicit `<input>` entries, matching the working syntax you tested.

## Open order

1. `04_raw_sanity_check_no_formulas_10min.plt` — verifies that raw PVs connect.
2. `00_core_overview_10min.plt` — compact formula dashboard.
3. `01_u125_orbit_angles_30min.plt` — detailed U125 BPM and angle diagnostics.
4. `02_bumper_steerers_akc_30min.plt` — bumper current deviations plus AKC/MNF original channels.
5. `03_signal_profiles_machine_30min.plt` — coherent signal, QPD/profile sizes, machine state.

## Important implementation note

Formula traces are **not** written as PV names like `=pv(...)`. They are written as:

```xml
<formula>
  <formula>1 + 20*(x3+0.0694)</formula>
  <input><pv>BPMZ3L2RP:rdX</pv><name>x3</name></input>
</formula>
```

This is the format that should make the CS-Studio trace properties show formula traces and input PVs.

## U125 BPM geometry

| Label | PV | Meaning |
|---|---|---|
| BPM3 | `BPMZ3L2RP` | first BPM before U125 |
| BPM4 | `BPMZ4L2RP` | second BPM before U125 |
| BPM5 | `BPMZ5L2RP` | first BPM after U125 |
| BPM6 | `BPMZ6L2RP` | second BPM after U125 |

Distances used:

- `L34 = 0.8594 m`
- `L56 = 0.9006 m`

Angle proxies, assuming BPMs in mm and distances in m:

```text
x'_up [mrad] = (BPM4_X - BPM3_X)/L34
x'_dn [mrad] = (BPM6_X - BPM5_X)/L56
Δx' = x'_dn - x'_up
```

Same for Y.

## 00 core overview color/offset map

Axis 0: coherent signal.

Stacked diagnostics axis:

| Offset | Color | Meaning |
|---:|---|---|
| 1 | blue | mean horizontal U125 BPM shift, scaled `20 × mm` |
| 2 | cyan | mean vertical U125 BPM shift, scaled `20 × mm` |
| 3 | purple | horizontal angle mismatch, scaled `5 × mrad` |
| 4 | olive | vertical angle mismatch, scaled `5 × mrad` |
| 5 | green | horizontal center consistency at U125, scaled `20 × mm` |
| 6 | orange | vertical center consistency at U125, scaled `20 × mm` |
| 7 | brown | bumper quadratic proxy, `Σ(ΔI)^2` scaled |
| 8 | black | horizontal tune monitor deviation proxy |
| 9 | gray | vertical tune monitor deviation proxy |

Because the traces are offset, look for **movement away from the integer baseline**, not the absolute y-value.

## 01 U125 orbit/angle view

Left axis: centered BPM deviations, with each BPM vertically offset. The scaling is `50 × Δmm`, so `0.02` on the plot corresponds to about `0.4 µm`? More usefully, a `1.0` vertical unit corresponds to `0.02 mm = 20 µm`.

Right axis: angle and center diagnostics:

| Offset | Color | Meaning |
|---:|---|---|
| 1 | green | upstream X angle change |
| 2 | orange | downstream X angle change |
| 3 | purple | X angle mismatch |
| 5 | cyan | upstream Y angle change |
| 6 | olive | downstream Y angle change |
| 7 | pink | Y angle mismatch |

A shift of `0.5` on these traces corresponds to `0.05 mrad = 50 µrad` because scaling is `10 × mrad`.

## 02 bumper/AKC view

Left axis: steerer current deviations, not raw currents. This makes tiny changes visible despite the different DC offsets.

- Individual steerers: `10000 × ΔI`, so one vertical unit is `0.1 mA`.
- Common/pair formulas are also scaled to show small changes.

Right axis: original AKC/MNF channels. These are not all same scale, but included because they were in the original working plot. Enable/disable traces as needed.

## 03 signal/profile/machine view

- Axis 0: coherent signal channels.
- Axis 1: QPD size deviations, scaled and offset.
- Axis 2: machine state raw values such as beam current, RF cavity voltage, U125 gap, Q1.

## Practical thresholds

Worry if a bumper scan causes:

- U125 angle mismatch change `> 0.05 mrad = 50 µrad`.
- BPM center/consistency change `> 0.05--0.1 mm`.
- coherent signal systematic change `> 10--30%` beyond shot noise.
- tune monitor proxy changes correlated with steerer current.
- QPD dispersive-region size changes `> 1--3%`.
