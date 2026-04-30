# IOC / PV Implementation Investigation

The uploaded `idcp` folder looks like an insertion-device control-panel / IOC deployment tree, not the mirror Picomotor IOC itself.

Useful findings from `idcp.zip`:

- It contains many display files for `U125IL2RP`.
- It contains config YAML with IOC/network metadata.
- It references a motor panel file:
  - `idcp/dl/U125IL2RP.v.motor.bob`
  - `idcp/dl/U125IL2RP.v.motor.adl`
- It lists IOC-style metadata such as:
  - `application: idcp`
  - `description: U125/1 ,U125IL2RP, idcp90, installed at MLS`
  - `ioc: eis4gp.mlscs.bessy.de`
  - `epics_server_port: 6064`
  - `rootdir: /vwhost/opt`

This appears to be the U125 insertion-device control system, not the `MNF...` mirror motors. The mirror motor PVs were served by:

```text
iocsc1cp.mlscs.bessy.de:34363
```

from earlier `cainfo`.

## What to look for on the control-room machine

The EPICS implementation of `MNF1C1L2RP`, etc. is likely in the IOC boot tree or a controls repository, not necessarily on the GUI workstation.

Search targeted paths, not the entire filesystem during operation.

### 1. Find OPI/display files

```bash
grep -R "MNF2C2L2RP" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
grep -R "MNF1C1L2RP" /opt/OPI /net/nfs/srv/MachinePhysics 2>/dev/null
```

### 2. Find IOC database records

Ask controls staff for the IOC boot path for:

```text
iocsc1cp.mlscs.bessy.de
```

Then search there:

```bash
grep -R "MNF2C2L2RP" <IOC_BOOT_OR_REPO_PATH>
grep -R "MNF1C1L2RP" <IOC_BOOT_OR_REPO_PATH>
```

Look for:

```text
st.cmd
*.db
*.template
*.substitutions
*.req
autosave*.sav
motor*.cmd
procServ config
systemd unit
```

### 3. Inspect motor record fields

Safe commands:

```bash
cainfo MNF2C2L2RP
caget MNF2C2L2RP.RTYP MNF2C2L2RP.DESC MNF2C2L2RP.EGU
caget MNF2C2L2RP.RBV MNF2C2L2RP.DMOV MNF2C2L2RP.MOVN
```

Potentially useful motor record fields, if present:

```text
VELO, VBAS, ACCL, BVEL, BDST, MRES, ERES, SREV, UREV, HLM, LLM, DHLM, DLLM
```

Use `caget` on a few fields only; avoid broad wildcard scans during operation.

## Likely crash root causes

- Too many `.VAL` puts too quickly.
- Large command jumps without waiting for `.DMOV`.
- `.STOP` sent during IOC/driver busy state.
- Motor record/driver assumes a motion sequence not respected by custom script.
- Missing velocity/acceleration limits or controller-side command queue overflow.

The GUI now uses ramped moves and `.DMOV` waits, but IOC-side behavior must be verified.
