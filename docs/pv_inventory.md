# EPICS PV Inventory From `original/betagui.py`

## Notes

- Inventory is based on PV strings found directly in `original/betagui.py`.
- Some PVs are read-only diagnostics in the current script.
- Some PVs are written directly and are therefore machine-state changing.
- A few commented-out alternates are listed separately at the end.

## Tune Measurement

- `TUNEZRP:measX`
  Purpose: horizontal tune readback
  Access in script: read
- `TUNEZRP:measY`
  Purpose: vertical tune readback
  Access in script: read
- `TUNEZRP:measZ`
  Purpose: synchrotron tune readback
  Access in script: read

## RF / Longitudinal Parameters

- `MCLKHGP:setFrq`
  Purpose: RF frequency setpoint
  Access in script: read and write
- `PAHRP:setVoltCav`
  Purpose: cavity voltage used in `cal_alpha0()`
  Access in script: read
- `PAHRP:cmdExtPhasMod`
  Purpose: external phase modulation command
  Access in script: write in reset path

## Sextupole Current Setpoints

- `S1P1RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S1P2RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S2P1RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S2P2RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write in secondary scan window
- `S2P2KRP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S2P2LRP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S3P1RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write
- `S3P2RP:setCur`
  Purpose: sextupole set current
  Access in script: read and write

## Orbit / Feedback / Optics Mode

- `ORBITCCP:selRunMode`
  Purpose: orbit correction mode selection
  Access in script: write during measurement/reset, read in scan logging
- `RMC00VP`
  Purpose: orbit correction status readback
  Access in script: read
- `IGPF:X:FBCTRL`
  Purpose: horizontal feedback control
  Access in script: read and write
- `IGPF:Y:FBCTRL`
  Purpose: vertical feedback control
  Access in script: read and write
- `IGPF:Z:FBCTRL`
  Purpose: longitudinal feedback control
  Access in script: read and write
- `MLSOPCCP:actOptRmpTblSet`
  Purpose: optics/ramp table mode
  Access in script: read

## BPM / Orbit Diagnostics

- `BPMZ1X003GP:rdBufBpm`
  Purpose: BPM waveform/buffer readback
  Access in script: PV created, intended read path commented out

## Beam Current / Lifetime / Energy Diagnostics

- `CUM1ZK3RP:rdLt10`
  Purpose: lifetime-related diagnostic
  Access in script: PV created, not used later
- `CUM1ZK3RP:rdLt100`
  Purpose: lifetime-related diagnostic
  Access in script: PV created, not used later
- `OPCHECKCCP:calcCurrLife`
  Purpose: calculated current lifetime
  Access in script: PV created, not used later
- `CUM1ZK3RP:measCur`
  Purpose: beam current readback
  Access in script: read
- `ERMPCGP:rdRmp`
  Purpose: beam energy / ramp readback
  Access in script: read

## Beam Size / Optics Diagnostics

- `QPD01ZL2RP:rdSigmaX`
  Purpose: QPD horizontal sigma
  Access in script: read
- `QPD01ZL2RP:rdSigmaY`
  Purpose: QPD vertical sigma
  Access in script: read
- `QPD00ZL4RP:rdSigmaX`
  Purpose: QPD horizontal sigma
  Access in script: read
- `QPD00ZL4RP:rdSigmaY`
  Purpose: QPD vertical sigma
  Access in script: read
- `SEKRRP:rdDose`
  Purpose: dose readback
  Access in script: PV created, not used later
- `WFGENC1CP:rdVolt`
  Purpose: white-noise generator voltage readback
  Access in script: read

## Commented-Out Alternate PVs

- `cumz4x003gp:tuneSyn`
  Purpose: alternate synchrotron tune source
  Status: commented out
- `JLC09VP`
  Purpose: alternate synchrotron tune source
  Status: commented out

## Grouped By Write Capability

### PVs Written By The Script

- `MCLKHGP:setFrq`
- `S1P1RP:setCur`
- `S1P2RP:setCur`
- `S2P1RP:setCur`
- `S2P2RP:setCur`
- `S2P2KRP:setCur`
- `S2P2LRP:setCur`
- `S3P1RP:setCur`
- `S3P2RP:setCur`
- `ORBITCCP:selRunMode`
- `IGPF:X:FBCTRL`
- `IGPF:Y:FBCTRL`
- `IGPF:Z:FBCTRL`
- `PAHRP:cmdExtPhasMod`

### Read-Only In Current Script

- `BPMZ1X003GP:rdBufBpm`
- `TUNEZRP:measX`
- `TUNEZRP:measY`
- `TUNEZRP:measZ`
- `MLSOPCCP:actOptRmpTblSet`
- `RMC00VP`
- `PAHRP:setVoltCav`
- `CUM1ZK3RP:rdLt10`
- `CUM1ZK3RP:rdLt100`
- `OPCHECKCCP:calcCurrLife`
- `QPD01ZL2RP:rdSigmaX`
- `QPD01ZL2RP:rdSigmaY`
- `QPD00ZL4RP:rdSigmaX`
- `QPD00ZL4RP:rdSigmaY`
- `SEKRRP:rdDose`
- `CUM1ZK3RP:measCur`
- `ERMPCGP:rdRmp`
- `WFGENC1CP:rdVolt`
