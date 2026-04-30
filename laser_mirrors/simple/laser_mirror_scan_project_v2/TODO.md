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
- [x] Add first-pass soft limits:
  - implemented as max delta from captured reference
- [ ] Improve soft limits:
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
- [x] selectable signal source concept: P1, QPD00 SigmaX/Y, QPD01 SigmaX/Y
- [ ] verify real QPD PV names on control-room machine
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


## IOC / EPICS motor-record implementation investigation

The PV host found by `cainfo` is:

```text
iocsc1cp.mlscs.bessy.de:34363
```

The actual `.NET → motor → EPICS` translation is usually **not inside the GUI PC**. It is usually one of:

1. IOC boot directory on the IOC host or NFS-mounted IOC tree.
2. EPICS database files (`*.db`, `*.template`, `*.substitutions`).
3. IOC startup script (`st.cmd`, `*.cmd`).
4. Motor support driver configuration.
5. Autosave/restore files.
6. Systemd service or procServ screen running the IOC.

Non-invasive things to try on the control-room PC:

```bash
cainfo MNF2C2L2RP
caget MNF2C2L2RP.RTYP MNF2C2L2RP.DESC MNF2C2L2RP.EGU
```

Look for display files referencing the PVs:

```bash
grep -R "MNF2C2L2RP" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
grep -R "MNF1C1L2RP" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
```

If you have access to IOC files, search for the PV base:

```bash
grep -R "MNF2C2L2RP" /opt/epics /net /srv /home 2>/dev/null
```

Avoid broad searches during operation. Ask controls staff for the IOC repository/boot path for host `iocsc1cp.mlscs.bessy.de`.
