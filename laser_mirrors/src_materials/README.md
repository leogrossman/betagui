# Source Materials

This folder contains only the reference material that is directly useful for the
`laser_mirrors` control-room tool.

## Layout

- `MirrorControl/`
  - legacy Picomotor control scripts
  - legacy geometry calculator
  - legacy `mirror_state.ini` behavior
- `laser_setup/`
  - compact laser / optics layout references
  - selected PDFs and images needed to understand the physical setup
- `mirrorsSpiral.py`
  - older scan/control UI used as inspiration
- `see Fig07 - TUP70.pdf`
  - target angle-scan style measurement reference
- `WEPMO02.pdf`
  - additional experiment background

## Why this is curated

The original working folder contained a much larger mix of photos, videos,
installers, and transient setup files. That was useful for ad-hoc local work,
but too heavy and noisy for the live `betagui` repository.

This curated subset is meant to stay:

- small enough to pull quickly in the control room
- rich enough to understand the geometry and legacy software behavior
- stable enough to serve as a long-term reference next to the new code
