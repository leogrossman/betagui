# PV Overview

## Mirror motors

| PV base | Description | Record type | Units |
|---|---|---|---|
| `MNF1C1L2RP` | Mirror 1 vertical | motor | steps |
| `MNF1C2L2RP` | Mirror 1 horizontal | motor | steps |
| `MNF2C1L2RP` | Mirror 2 vertical | motor | steps |
| `MNF2C2L2RP` | Mirror 2 horizontal | motor | steps |

## Useful fields

For every motor base:

| Field | Meaning |
|---|---|
| `.VAL` | commanded setpoint |
| `.RBV` | readback value |
| `.DMOV` | done moving |
| `.MOVN` | moving |
| `.STOP` | stop motion |
| `.DESC` | description |
| `.EGU` | engineering units |
| `.STAT` | alarm status |
| `.SEVR` | alarm severity |
| `.RTYP` | record type |

## P1 / harmonic candidates

From the uploaded LiveEvaluation project, the harmonic PV pattern appears to be:

```text
SCOPE1ZULP:h1p1:rdAmpl
SCOPE1ZULP:h1p2:rdAmpl
SCOPE1ZULP:h1p3:rdAmpl
SCOPE1ZULP:h1p1:rdAmplAv
SCOPE1ZULP:h1p1:rdAmplDev
SCOPE1ZULP:h1p1:rdTurnNr
SCOPE1ZULP:h1p1:rdPeakNr
```

The correct one for the scan must be verified on the control-room machine.
