## SSMB Experiment TODO

This file tracks feature ideas and unresolved polish items requested during control-room development so they do not need to be repeated.

### High Priority

- Make live monitor pane cards even more compact if needed after real-machine use.
- Add explicit logger-health widget with flush state, last write timestamp, and current session path.
- Add more lattice-device mappings for oscillation-study candidates.
- Improve lattice marker placement and label de-overlap further for dense regions.
- Add better cavity / RF theory text directly in lattice inspector.

### Diagnostics / Physics

- Add richer local derived quantities in lattice inspector for selected BPMs and magnets.
- Add optional local oscillation analysis for selected lattice devices.
- Improve bump-quality metric with more formal undulator-region constraints.
- Add more explicit controlled-orbit-family interpretation for bump-on RF sweeps.
- Add optional fit overlays in oscillation-study candidate plots.

### QPD / Beam Screens

- Consider a lightweight live 2D QPD image path only if a safe/readable image PV is identified.
- Improve beam-screen proxy view with center-x, center-y, sigma-x, sigma-y, and ellipse orientation if available.
- Add explicit distinction between source dipole location and physical camera head location in the lattice inspector UI.

### Bump Lab

- Add a dedicated monitor-health strip inside bump lab.
- Add suggested alternative BPM sets for testing improved bump strategies.
- Add click-through shortcuts from bump-lab BPM list to lattice view.
- Consider a larger split-layout for bump-lab plots if operators still need more room.

### Future / Not For Immediate Control-Room Use

- Offline/analysis-side pyAT comparison workflow for live data versus model, not inside the live control-room GUI.
- Optional replay mode for saved sessions inside the experimental GUI.
- Better multi-parameter correlation / lag explorer for the slow P1 oscillation study.
