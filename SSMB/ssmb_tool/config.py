from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


PACKAGE_ROOT = Path(__file__).resolve().parent
LATTICE_DIR = PACKAGE_ROOT.parent / "MLS_lattice"
DEFAULT_LATTICE_EXPORT = LATTICE_DIR / "mls_lattice_low_emittance_export.json"
DEFAULT_OUTPUT_ROOT = Path(".ssmb_local") / "ssmb_stage0"
DEFAULT_SAMPLE_HZ = 1.0
DEFAULT_DURATION_S = 60.0
DEFAULT_TIMEOUT_S = 0.5


@dataclass(frozen=True)
class LoggerConfig:
    duration_seconds: float = DEFAULT_DURATION_S
    sample_hz: float = DEFAULT_SAMPLE_HZ
    timeout_seconds: float = DEFAULT_TIMEOUT_S
    output_root: Path = DEFAULT_OUTPUT_ROOT
    lattice_export: Path = DEFAULT_LATTICE_EXPORT
    safe_mode: bool = True
    allow_writes: bool = False
    include_bpm_buffer: bool = True
    include_candidate_bpm_scalars: bool = True
    include_ring_bpm_scalars: bool = True
    include_quadrupoles: bool = False
    include_sextupoles: bool = True
    include_octupoles: bool = True
    session_label: str = ""
    operator_note: str = ""
    extra_pvs: Dict[str, str] = field(default_factory=dict)
    extra_optional_pvs: Dict[str, Optional[str]] = field(default_factory=dict)

    def validate(self) -> None:
        if self.sample_hz <= 0.0:
            raise ValueError("sample_hz must be positive.")
        if self.sample_hz > 10.0:
            raise ValueError("sample_hz above 10 Hz is intentionally blocked for passive control-room logging.")
        if self.duration_seconds <= 0.0:
            raise ValueError("duration_seconds must be positive.")
        if self.include_ring_bpm_scalars and self.sample_hz > 2.0:
            raise ValueError("Full-ring BPM scalar logging is limited to 2 Hz or below to avoid unnecessary PV load.")


def parse_labeled_pvs(items: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError("Expected LABEL=PVNAME format, got %r" % item)
        label, pv_name = item.split("=", 1)
        label = label.strip()
        pv_name = pv_name.strip()
        if not label or not pv_name:
            raise ValueError("Expected LABEL=PVNAME format, got %r" % item)
        mapping[label] = pv_name
    return mapping
