# Development Roadmap

## Highest priority before machine use

- [ ] Verify motor sign convention:
  - [ ] `MNF1C1L2RP`
  - [ ] `MNF1C2L2RP`
  - [ ] `MNF2C1L2RP`
  - [ ] `MNF2C2L2RP`
- [ ] Verify µrad/step calibration:
  - [ ] horizontal `2.75 µrad/step`
  - [ ] vertical `1.89 µrad/step`
- [ ] Confirm P1 PV:
  - candidate pattern from LiveEvaluation: `SCOPE1ZULP:h1p*:rdAmpl`
  - averaged variants: `rdAmplAv`
- [ ] Add soft limits:
  - max step delta from reference
  - max absolute motor value
  - max angle span
- [ ] Add required scan preview approval table before write scans.

## Optical schematic improvements

Uploaded layout material shows a richer PoP II setup:

- PoP II laser
- Pockels cell PC4
- half-wave plate
- polarizing beam splitter cube
- remotely controlled shutter
- lenses:
  - `f = -300 mm`
  - `f = 1600 mm`
  - `f = -150 mm`
  - `f = 300 mm`
- photodiodes
- power meter
- path to undulator

Current GUI only draws the steering geometry:

```text
M1 → M2 → undulator
```

Future work:

- [ ] Add optical-table overview layer.
- [ ] Draw PoP I and PoP II paths in different styles.
- [ ] Draw telescope/lens elements from the PDF.
- [ ] Add optional top-view and side-view tabs.
- [ ] Add measured component coordinates if available.

## Scan modes

Implemented:

- [x] full 2D angle scan
- [x] horizontal-only angle scan
- [x] vertical-only angle scan
- [x] mirror-2-only spiral scan

Future:

- [ ] mirror 1 primary scan, solve mirror 2 to hold point
- [ ] mirror 2 primary scan, solve mirror 1 to hold point
- [ ] adaptive optimizer
- [ ] coarse grid + local refinement
- [ ] Gaussian/parabolic fit to P1 map
- [ ] automatic return to best point

## Data features

- [x] CSV output
- [x] run log
- [x] config JSON
- [ ] save PNG plots
- [ ] save full PV snapshot at each point
- [ ] record alarm status at each point
- [ ] record machine current / bunch charge / RF state PVs
- [ ] connect directly to LiveEvaluation harmonic PVs

## Safety features

- [x] read-only default
- [x] explicit `--write-mode`
- [x] STOP all
- [x] return to captured reference
- [ ] configurable limits file
- [ ] scan dry-run report with max/min motor commands
- [ ] lockout if any motor alarm severity is not `NO_ALARM`
- [ ] optional operator confirmation per point for early commissioning
