# Runtime Checklist

Use this short checklist before any future real-machine deployment.

## Environment

- Confirm the project uses the intended pyenv environment:
  `python3 --version`
- Confirm required imports:
  `numpy`, `scipy`, `matplotlib`, `epics`, `tkinter`
- Confirm EPICS CLI tools are available:
  `cainfo`, `caget`, `camonitor`, `caput`

## Read-Only Validation

- Start with:
  `python3 control_room/betagui_safe.py`
- Do not use `--allow-writes` yet.
- Confirm the GUI starts without import or display errors.
- Confirm the status panel does not report missing critical PVs.
- Confirm expected legacy PVs are reachable with `cainfo`.

## PV Sanity

- RF PV is present and readable.
- tune X and tune Y PVs are present and readable.
- synchrotron-tune PV is present if dynamic `alpha0` will be used.
- sextupole family PVs are present and readable.
- feedback and orbit-control PVs are present if legacy write behavior is expected.
- cavity-voltage and beam-energy PVs are present if dynamic `alpha0` will be used.

## Safety

- Review [write_paths.md](write_paths.md).
- Confirm saved initial settings are sensible before testing reset behavior.
- Confirm operator intent before enabling any write-capable run.
- Use `--allow-writes` only after read-only validation is complete.

## First Live Functional Checks

- Measure `alpha0` only if the required PVs are confirmed.
- Run a small chromaticity measurement with conservative inputs.
- Verify RF returns to the initial value afterward.
- Verify feedback/orbit states are restored afterward.
- Only then consider matrix measurement or manual correction buttons.

## If Anything Is Unclear

- Stop and fall back to mock mode or the digital twin.
- Do not guess at missing PV mappings or machine-state semantics.
