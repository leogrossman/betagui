from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class GeometryConfig:
    mirror_distance_mm: float = 2285.0
    undulator_distance_mm: float = 6010.0
    horizontal_step_urad: float = 2.75
    vertical_step_urad: float = 1.89
    mirror2_x_sign: float = -1.0
    mirror2_y_sign: float = 1.0


@dataclass
class ControllerConfig:
    backend: str = "simulated"
    safe_mode: bool = True
    p1_backend: str = "simulated"
    p1_pv: str = ""
    picomotor_config_path: str = "src_materials/MirrorControl/config.ini"
    calibration_path: str = "src_materials/MirrorControl/calib.ini"
    state_file_path: str = "src_materials/MirrorControl/mirror_state.ini"
    startup_offset_x_mm: float = 0.0
    startup_offset_y_mm: float = 0.0
    startup_angle_x_urad: float = 0.0
    startup_angle_y_urad: float = 0.0
    p1_poll_interval_ms: int = 500
    p1_average_samples: int = 20


@dataclass
class ScanConfig:
    center_angle_x_urad: float = 0.0
    center_angle_y_urad: float = 0.0
    span_angle_x_urad: float = 400.0
    span_angle_y_urad: float = 400.0
    points_x: int = 9
    points_y: int = 9
    dwell_s: float = 0.5
    p1_samples_per_point: int = 3
    serpentine: bool = True
    objective: str = "max"
    solve_mode: str = "two_mirror_target"


@dataclass
class AppConfig:
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    controller: ControllerConfig = field(default_factory=ControllerConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            geometry=GeometryConfig(**raw.get("geometry", {})),
            controller=ControllerConfig(**raw.get("controller", {})),
            scan=ScanConfig(**raw.get("scan", {})),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
