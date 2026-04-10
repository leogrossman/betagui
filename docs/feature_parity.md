# Feature Parity

This table tracks the Python 3 port against the legacy control-room script in
[original/betagui.py](https://github.com/leogrossman/betagui/blob/main/original/betagui.py).

## Status Table

| Area | Legacy Python 2 | Python 3 Port | Notes |
| --- | --- | --- | --- |
| GUI startup | Yes | Yes | Python 3 import/runtime is safer and lazier |
| Barebones CLI measurement path | No | Yes | Added as a fallback for control-room use |
| Live legacy PV profile | Yes | Yes | Preserved as the default live-machine profile |
| RF sweep chromaticity measurement | Yes | Yes | Same broad workflow and fit logic |
| Dynamic `alpha0` | Yes | Yes | Requires the same machine-side PV class as legacy |
| Manual `alpha0` entry | Yes | Yes | Needed for partial environments and the twin |
| Feedback/orbit disable and restore | Yes | Yes | Wrapped in explicit helper logic |
| Response-matrix measurement | Yes | Yes | Same finite-difference idea as legacy |
| Matrix load/save | Yes | Yes | Legacy tagged text format preserved |
| Manual `d\xi` correction buttons | Yes | Yes | Same matrix-driven sextupole correction idea |
| Reset to saved state | Yes | Yes | RF, sextupoles, feedback, orbit, phase modulation |
| Secondary `sext scan` window | Yes | Yes | Restored in the Python 3 GUI |
| Polynomial sextupole response measurement | Partial / broken | Yes | Restored with explicit repairs |
| Scan-table generation | Partial / broken | Yes | Restored with explicit repairs |
| Scan-table diagnostic logging | Partial / broken | Yes | Restored with the original diagnostic intent |
| BPM orbit plotting | Placeholder zeros | Placeholder zeros | Legacy code already had live BPM readout disabled |
| Mock offline mode | No | Yes | Development/testing only |
| Digital twin mode | No | Yes | Development/testing only |
| Import without live EPICS | No | Yes | Porting safety improvement |

## Faithfulness Notes

The physics-facing measurement path stays close to the original code where the
legacy behavior was internally coherent:

- `MeaChrom(...)` still performs RF sweep, tune averaging, polynomial fit, and
  `xi` extraction from the tune-vs-RF slope
- the response-matrix path still measures `d\xi / dI` by stepping sextupole
  families and inverting the measured matrix
- the secondary scan still fits the no-intercept model
  `d\xi = p1 * dI^2 + p2 * dI`

## Repaired Legacy Defects

Some parts of the legacy script were not runnable as written. Those repairs are
explicit in the Python 3 code and should be treated as documented deviations,
not silent reinterpretations.

| Legacy defect | Python 3 repair |
| --- | --- |
| Missing helper `setcur(...)` | Replaced by a small family-current helper |
| Float index into `bumpdataS[...]` | Uses the row closest to the starting current as reference |
| `Sc` and `Sd` accidentally scan a fixed value only | Uses configured min and max for all four scan axes |
| Scan-table output drops one sextupole current | Writes the full seven-current machine state |

## Intentional Safety Differences

These are deliberate and should remain explicit:

- default mode in the development launcher is mock mode
- live EPICS is opt-in in the development launcher
- live writes are opt-in in every new launcher
- the digital twin uses an explicit non-legacy PV profile

## Remaining Non-Parity Areas

| Area | Status | Why |
| --- | --- | --- |
| Live BPM orbit waveform in plot | Not restored | The legacy source already had this path disabled |
| One-to-one digital-twin PV parity | Not available | The twin does not expose the full legacy namespace |
| Control-room-on-machine validation | Pending | Needs real machine-side testing with operators |

## Output Reference Notes

The text files shipped in [original/](https://github.com/leogrossman/betagui/tree/main/original)
are matrix references, not saved chromaticity measurements.

So output checking in this repo is split into:

- exact numeric handling of legacy matrix files
- regression testing of chromaticity values in mock mode
