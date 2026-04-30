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
    static_fold_distance_mm: float = 1200.0


@dataclass
class ControllerConfig:
    safe_mode: bool = False
    write_mode: bool = False
    state_file_path: str = "src_materials/MirrorControl/mirror_state.ini"
    motor_recovery_path: str = "laser_mirror_motor_state.json"
    last_command_path: str = "laser_mirror_last_command.json"
    startup_offset_x_mm: float = 0.0
    startup_offset_y_mm: float = 0.0
    startup_angle_x_urad: float = 0.0
    startup_angle_y_urad: float = 0.0
    signal_pv: str = "SCOPE1ZULP:h1p1:rdAmplAv"
    signal_label: str = "P1 avg"
    p1_poll_interval_ms: int = 300
    p1_average_samples: int = 30
    max_step_per_put: float = 8.0
    inter_put_delay_s: float = 0.35
    wait_timeout_s: float = 30.0
    settle_s: float = 0.8
    max_delta_from_reference: float = 500.0
    max_absolute_move_steps: float = 1200.0
    preview_required: bool = True
    alarm_lockout: bool = True


@dataclass
class ScanConfig:
    mode: str = "both_2d"
    center_angle_x_urad: float = 0.0
    center_angle_y_urad: float = 0.0
    span_angle_x_urad: float = 50.0
    span_angle_y_urad: float = 50.0
    points_x: int = 7
    points_y: int = 7
    dwell_s: float = 1.0
    p1_samples_per_point: int = 5
    serpentine: bool = True
    objective: str = "max"
    solve_mode: str = "mirror1_primary"
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    spiral_step_x: float = 6.0
    spiral_step_y: float = 8.0
    spiral_turns: int = 20


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
