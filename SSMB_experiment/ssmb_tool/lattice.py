from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class LatticeElement:
    family_name: str
    element_type: str
    section: Optional[str]
    s_center_m: float
    role: str
    power_supply_set_pv: Optional[str]
    power_supply_rd_pv: Optional[str]
    pv_candidates: Sequence[str]
    connected_inventory_pvs: Sequence[str]
    optics_center: Dict[str, object]
    model_strengths: Dict[str, object]


@dataclass
class LatticeContext:
    ring_name: str
    energy_eV: float
    circumference_m: float
    elements: List[LatticeElement]
    special_locations: Dict[str, Dict[str, object]]
    optics_samples: Dict[str, List[float]]
    global_metrics: Dict[str, object]

    @classmethod
    def load(cls, path: Path) -> "LatticeContext":
        data = json.loads(path.read_text(encoding="utf-8"))
        elements = [
            LatticeElement(
                family_name=item["family_name"],
                element_type=item["element_type"],
                section=item.get("section"),
                s_center_m=float(item["s_center_m"]),
                role=item.get("role", ""),
                power_supply_set_pv=item.get("power_supply_set_pv"),
                power_supply_rd_pv=item.get("power_supply_rd_pv"),
                pv_candidates=item.get("pv_candidates", []),
                connected_inventory_pvs=item.get("connected_inventory_pvs", []),
                optics_center=dict(item.get("optics_center", {})),
                model_strengths={
                    "K": item.get("K"),
                    "H": item.get("H"),
                    "PolynomB": item.get("PolynomB"),
                },
            )
            for item in data.get("elements", [])
        ]
        return cls(
            ring_name=str(data.get("ring_name", "MLS")),
            energy_eV=float(data.get("energy_eV", 0.0)),
            circumference_m=float(data.get("circumference_m", 0.0)),
            elements=elements,
            special_locations=dict(data.get("special_locations", {})),
            optics_samples={
                str(key): (list(value) if isinstance(value, (list, tuple)) else [value])
                for key, value in dict(data.get("optics_samples", {})).items()
            },
            global_metrics=dict(data.get("global_metrics", {})),
        )

    def monitors(self) -> List[LatticeElement]:
        return [item for item in self.elements if item.element_type == "Monitor"]

    def octupoles(self) -> List[LatticeElement]:
        return [item for item in self.elements if item.element_type == "Octupole"]

    def quadrupoles(self) -> List[LatticeElement]:
        return [item for item in self.elements if item.element_type == "Quadrupole"]

    def sextupoles(self) -> List[LatticeElement]:
        return [item for item in self.elements if item.element_type == "Sextupole"]

    def section_elements(self, section: str) -> List[LatticeElement]:
        return [item for item in self.elements if item.section == section]

    def u125_neighborhood(self) -> List[LatticeElement]:
        center = 12.0
        return [item for item in self.elements if abs(item.s_center_m - center) <= 6.5]

    def l4_straight(self) -> List[LatticeElement]:
        return [item for item in self.elements if item.section == "L4" and 29.0 <= item.s_center_m <= 43.0]
