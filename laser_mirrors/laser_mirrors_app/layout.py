from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpticsComponent:
    """Named optical element in the curated PoP II steering schematic."""

    key: str
    label: str
    x_mm: float
    y_mm: float
    kind: str
    note: str = ""


def default_optics_layout() -> list[OpticsComponent]:
    """Return a curated optics layout derived from the PoP II setup drawings.

    The absolute upstream distances are only approximate because the source
    material is a schematic, not a surveyed metrology export. The critical
    distances for the steering transform remain exact in the geometry module:

    - mirror 1 to mirror 2: 2285 mm
    - mirror 2 to undulator center: 6010 mm

    Here we preserve the documented *ordering* and the presence of the fixed
    fold mirror between the two movable mirrors so the operator sees a faithful
    representation of the actual beamline topology.
    """

    return [
        OpticsComponent("pop1_head", "PoP I head", -5200.0, -45.0, "laser"),
        OpticsComponent("pop2_amp", "PoP II amp", -4250.0, -45.0, "laser"),
        OpticsComponent("pc4", "Pockels cell", -3600.0, -45.0, "optic"),
        OpticsComponent("shutter", "Shutter", -3050.0, -45.0, "optic"),
        OpticsComponent("aperture", "Aperture", -2550.0, -45.0, "optic"),
        OpticsComponent("lens_neg150", "Lens f=-150", -2150.0, -45.0, "lens"),
        OpticsComponent("photodiode", "Photodiode", -1800.0, -180.0, "diagnostic"),
        OpticsComponent("power_meter", "Power meter", -1600.0, 95.0, "diagnostic"),
        OpticsComponent("lens_pos300", "Lens f=300", -1350.0, -45.0, "lens"),
        OpticsComponent("mirror1", "Mirror 1", 0.0, -45.0, "mirror", "First movable steering mirror"),
        OpticsComponent("fixed_fold", "Static fold", 1200.0, 120.0, "mirror", "Fixed fold mirror between the movers"),
        OpticsComponent("mirror2", "Mirror 2", 2285.0, -15.0, "mirror", "Second movable steering mirror"),
        OpticsComponent("undulator", "Undulator center", 8295.0, 0.0, "interaction", "Target interaction point"),
        OpticsComponent("to_undulator", "To undulator", 8825.0, 0.0, "label"),
    ]

