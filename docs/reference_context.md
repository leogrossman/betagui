# Reference Context From `support/mlsreflat-main/`

## Scope

This document records useful context from the MLS reference lattice package:

- [lattice.py](https://github.com/leogrossman/betagui/blob/main/support/mlsreflat-main/src/mlsreflat/storage_ring/lattice.py)
- [configurations.py](https://github.com/leogrossman/betagui/blob/main/support/mlsreflat-main/src/mlsreflat/storage_ring/configurations.py)
- storage-ring CSV data files under [data/](https://github.com/leogrossman/betagui/tree/main/support/mlsreflat-main/src/mlsreflat/storage_ring/data)
- [mls_storage_ring_power_supplies.json](https://github.com/leogrossman/betagui/blob/main/support/mlsreflat-main/src/mlsreflat/storage_ring/mls_storage_ring_power_supplies.json)

The purpose here is context only. I am not treating this package as authoritative for how `original/betagui.py` must behave. Any port should preserve the legacy tool’s logic unless a change is explicitly justified.

## High-Confidence Correspondences

## Harmonic Number

The reference lattice sets:

- `harmonic_number = 80`

This matches the legacy script’s:

- `Nharmonic = 80`

This is a strong correspondence and supports leaving that constant unchanged in the port unless you later confirm a machine-mode-specific reason to vary it.

## RF Scale

The reference lattice uses:

- `rf_frequency = 499_654_096.6666665`

The legacy GUI reads/writes:

- `MCLKHGP:setFrq`

The legacy comments are inconsistent about Hz vs kHz, but the reference RF value strongly suggests the legacy code is conceptually working in Hz-scale RF values near `499.654 MHz`, even if comments say otherwise.

This supports documenting unit ambiguity in the port rather than silently changing formulas.

## BPM Longitudinal Positions

The hard-coded BPM positions returned by `BPDM()` in the legacy script line up with monitor placements in the reference lattice. Examples:

- `1.2034`
- `2.1040`
- `4.2490`
- `5.2290`
- `6.2040`
- `8.1872`
- `9.0466`
- ...

These same numbers appear as drift/monitor placement distances in the reference lattice sections.

Practical conclusion:

- the `BPDM()` position list is not arbitrary
- it appears derived from the same MLS ring layout represented in the reference package

What does **not** follow from this:

- it does not prove the legacy BPM waveform decode is correct
- it does not justify changing `BPDM()` behavior without separate evidence

## Sextupole Family Names

The reference lattice and power-supply mapping align closely with the legacy GUI PV family names.

Legacy GUI families:

- `S1P1RP`
- `S1P2RP`
- `S2P1RP`
- `S2P2KRP`
- `S2P2LRP`
- `S3P1RP`
- `S3P2RP`

Reference power-supply family mapping:

- `S1P1RP` -> `S1M2K1RP`, `S1M1L2RP`, `S1M2L4RP`, `S1M1K1RP`
- `S1P2RP` -> `S1M2L2RP`, `S1M1K3RP`, `S1M2K3RP`, `S1M1L4RP`
- `S2P1RP` -> `S2M2K1RP`, `S2M1L2RP`, `S2M2L4RP`, `S2M1K1RP`
- `S2P2KRP` -> `S2M1K3RP`, `S2M2K3RP`
- `S2P2LRP` -> `S2M2L2RP`, `S2M1L4RP`
- `S3P1RP` -> `S3M2K1RP`, `S3M1L2RP`, `S3M2L4RP`, `S3M1K1RP`
- `S3P2RP` -> `S3M2L2RP`, `S3M1K3RP`, `S3M2K3RP`, `S3M1L4RP`

This is useful context for understanding the legacy GUI’s bump modes:

- `2D`
- `2D(P2)`
- `3D`
- `3D(P2)`

Interpretation:

- the legacy tool is operating on sextupole power-supply families, not individual lattice elements
- the split `S2P2K` / `S2P2L` channels in the GUI correspond to two different subfamilies in the reference model

## Legacy GUI Family Groupings vs Reference Lattice

The legacy tool groups sextupoles as:

- `S1`
- `S2`
- `S3`

with P1/P2 or split variants depending on mode.

The reference lattice reflects the same structure:

- `VS1P1`, `VS1P2`
- `VS2P1`, `VS2P2K`, `VS2P2L`
- `VS3P1`, `VS3P2`

This is a strong contextual match. It supports the idea that the legacy response-matrix and correction logic is family-based in the same sense as the reference lattice, even though the GUI does not model the full lattice explicitly.

## Reference Sextupole Strength Defaults

The base reference lattice currently sets:

- `VS1P1 = 45.8`
- `VS1P2 = 45.8`
- `VS2P1 = -47.6`
- `VS2P2K = -64.2`
- `VS2P2L = -64.2`
- `VS3P1 = 0.0`
- `VS3P2 = 0.0`

The code comment there says:

- “This needs to be updated!”

So these values are useful only as rough context. They should not be used to overwrite or “correct” the legacy tool’s live machine assumptions.

## Lattice Configurations

The reference package exposes configuration functions:

- `injection()`
- `low_alpha()`
- `low_emittance()`
- `ssmb()`

backed by CSV files:

- `mls_storage_ring_injection.csv`
- `mls_storage_ring_low_alpha.csv`
- `mls_storage_ring_low_emittance.csv`
- `mls_storage_ring_ssmb.csv`

These configuration files contain element-level strengths for quadrupoles and sextupoles.

Useful context:

- they show that machine optics modes are expected to vary sextupole families materially
- they provide plausible family-level numbers for different operating points

Important limit:

- the legacy GUI’s `MLSOPCCP:actOptRmpTblSet` handling is much simpler and only changes an assumed `Dmax`
- I did not find a direct mapping in the reference package from `actOptRmpTblSet` values to these named configurations

So the port should not silently replace the legacy `Dmax` logic with reference-package configuration logic.

## Injection Configuration Context

The injection configuration notably sets:

- `ring.energy = 105e6`
- cavity voltage to `72e3`

That is quite different from the default storage-ring lattice in `lattice.py`, which uses:

- `energy = 629e6`
- `main_cavity_voltage = 500e3`

This matters because the legacy `cal_alpha0()` uses energy and cavity voltage readbacks directly from EPICS. The reference package confirms that these quantities are mode-dependent enough that the legacy choice to read them live is reasonable.

## Ring Layout Correspondence

The reference lattice is assembled from:

- `first_half_of_K1`
- `L2`
- `K3`
- `L4`
- `second_half_of_K1`

Within those sections, the naming pattern of elements and monitors closely matches MLS naming conventions visible in the legacy PVs:

- BPM names like `BPMZ1L2RP`, `BPMZ5K3RP`
- sextupoles like `S1M1K3RP`, `S2M2L2RP`
- cavities, dipoles, quadrupoles using similar suffix structure

This supports interpreting the legacy GUI as a machine-operations tool built around the same naming ecosystem as the reference lattice.

## Specific Legacy Ambiguities Clarified By Reference Context

## Why `S2P2K` and `S2P2L` Are Separate

The legacy script treats:

- `S2P2KRP:setCur`
- `S2P2LRP:setCur`

as separate write channels, but often applies the same increment to both.

The reference mapping explains why they are separate:

- they correspond to different lattice-element groups in different sectors

This clarifies structure, but it does **not** answer whether they should always be driven identically in every operating mode. The legacy GUI does drive them together, and that behavior should stay unchanged in the first port.

## Why `BPDM()` Has 28 Positions

The reference lattice contains many monitor locations around the ring that align with the legacy hard-coded list. That strongly suggests the 28-position array is a hand-maintained subset of MLS BPM stations rather than placeholder numbers.

Again, this helps interpretation, but it does not recover the missing waveform-to-orbit conversion logic.

## Areas Where The Reference Package Does Not Resolve Legacy Uncertainty

- It does not define the missing legacy helper `setcur(...)`.
- It does not explain the broken `set_Isextupole_slowly()` helper.
- It does not define the response matrices saved in `original/SUwithoutorbitbumpResMat*.txt`.
- It does not reveal how `MLSOPCCP:actOptRmpTblSet` values `1`, `3`, or other values should map to lattice configurations.
- It does not validate the legacy chromaticity formulas or unit assumptions.
- It does not justify the legacy script’s choice to disable feedback and orbit correction during RF sweeps.

## Practical Guidance For Later Phases

The reference package is useful in later phases for:

- naming sanity checks
- explaining family/group structure in comments
- building plausible mock data for offline tests
- checking that BPM position arrays and family labels are physically plausible

The reference package should **not** be used in later phases to:

- silently rewrite the legacy GUI into a lattice-driven application
- substitute modeled sextupole defaults for live machine values
- change the meaning of bump modes without direct evidence from the legacy tool
- replace EPICS-driven measurement logic with AT calculations

## Summary

The main useful correspondences are:

- harmonic number `80`
- RF scale near `499.654 MHz`
- BPM longitudinal positions used by the GUI
- sextupole family naming and decomposition
- mode-dependent optics context from CSV configuration files

That is enough reference context to improve documentation and mocks later, but not enough to justify changing legacy control logic during the initial Python 3 port.
