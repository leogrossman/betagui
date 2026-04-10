"""Offline EPICS stand-ins for testing betagui logic.

The model is deliberately simple. It is only meant to exercise control flow and
produce plausible-looking numbers for offline tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class MockPV:
    name: str
    value: object = 0.0
    on_put: Optional[Callable[[str, object], None]] = None

    def get(self):
        return self.value

    def put(self, value):
        self.value = value
        if self.on_put is not None:
            self.on_put(self.name, value)
        return True


@dataclass
class MockMachineModel:
    """Small stateful model for RF/tune/sextupole behavior."""

    rf0_hz: float = 499_654_096.6666665
    # Keep the mock tune readbacks in kHz because the legacy code treats the
    # tune PVs as frequency-like readouts rather than fractional tunes.
    tune_x0_khz: float = 1200.0
    tune_y0_khz: float = 850.0
    tune_s0_khz: float = 7.5
    energy_mev: float = 629.0
    cavity_voltage_kv: float = 500.0
    optics_mode: int = 1
    sextupoles: Dict[str, float] = field(
        default_factory=lambda: {
            "S1P1RP:setCur": 45.8,
            "S1P2RP:setCur": 45.8,
            "S2P1RP:setCur": -47.6,
            "S2P2RP:setCur": -64.2,
            "S2P2KRP:setCur": -64.2,
            "S2P2LRP:setCur": -64.2,
            "S3P1RP:setCur": 0.0,
            "S3P2RP:setCur": 0.0,
        }
    )
    feedback_state: Dict[str, float] = field(
        default_factory=lambda: {
            "IGPF:X:FBCTRL": 1.0,
            "IGPF:Y:FBCTRL": 1.0,
            "IGPF:Z:FBCTRL": 1.0,
        }
    )
    orbit_mode: float = 1.0
    phase_modulation: str = "disabled"
    beam_current_ma: float = 5.0
    qpd1_sigma_x: float = 120.0
    qpd1_sigma_y: float = 95.0
    qpd0_sigma_x: float = 130.0
    qpd0_sigma_y: float = 100.0
    beam_lifetime_10h: float = 8.0
    beam_lifetime_100h: float = 7.5
    calculated_lifetime_h: float = 7.8
    dose_rate: float = 0.0
    white_noise_v: float = 0.02

    def on_put(self, name: str, value):
        if name == "MCLKHGP:setFrq":
            self.rf0_hz = float(value)
            return
        if name in self.sextupoles:
            self.sextupoles[name] = float(value)
            return
        if name in self.feedback_state:
            self.feedback_state[name] = float(value)
            return
        if name == "ORBITCCP:selRunMode":
            self.orbit_mode = float(value)
            return
        if name == "PAHRP:cmdExtPhasMod":
            self.phase_modulation = str(value)

    def tune_shift_khz(self):
        """Simple first-order response to RF and sextupole changes.

        The coefficients are tuned for plausibility, not fidelity:
        - RF sweeps should produce order-unity chromaticities
        - sextupole changes should visibly move the tunes
        - values should stay easy to inspect during offline testing
        """
        rf_offset_mhz = (self.rf0_hz - 499_654_096.6666665) / 1e6
        s1 = self.sextupoles["S1P1RP:setCur"] + self.sextupoles["S1P2RP:setCur"]
        s2 = (
            self.sextupoles["S2P1RP:setCur"]
            + self.sextupoles["S2P2KRP:setCur"]
            + self.sextupoles["S2P2LRP:setCur"]
        )
        s3 = self.sextupoles["S3P1RP:setCur"] + self.sextupoles["S3P2RP:setCur"]
        ds1 = s1 - (45.8 + 45.8)
        ds2 = s2 - (-47.6 - 64.2 - 64.2)
        ds3 = s3 - 0.0
        return {
            "x": -850.0 * rf_offset_mhz + 0.90 * ds1 - 0.35 * ds2 + 0.20 * ds3,
            "y": -620.0 * rf_offset_mhz - 0.45 * ds1 + 0.85 * ds2 + 0.12 * ds3,
            "s": -90.0 * rf_offset_mhz + 0.08 * ds1 - 0.05 * ds2 + 0.30 * ds3,
        }

    def read(self, name: str):
        shift = self.tune_shift_khz()
        if name == "TUNEZRP:measX":
            return self.tune_x0_khz + shift["x"]
        if name == "TUNEZRP:measY":
            return self.tune_y0_khz + shift["y"]
        if name == "TUNEZRP:measZ":
            return self.tune_s0_khz + shift["s"]
        if name == "MCLKHGP:setFrq":
            return self.rf0_hz
        if name == "MLSOPCCP:actOptRmpTblSet":
            return self.optics_mode
        if name == "ORBITCCP:selRunMode":
            return self.orbit_mode
        if name == "RMC00VP":
            return self.orbit_mode
        if name in self.feedback_state:
            return self.feedback_state[name]
        if name == "PAHRP:setVoltCav":
            return self.cavity_voltage_kv
        if name == "ERMPCGP:rdRmp":
            return self.energy_mev
        if name == "PAHRP:cmdExtPhasMod":
            return self.phase_modulation
        if name == "CUM1ZK3RP:rdLt10":
            return self.beam_lifetime_10h
        if name == "CUM1ZK3RP:rdLt100":
            return self.beam_lifetime_100h
        if name == "OPCHECKCCP:calcCurrLife":
            return self.calculated_lifetime_h
        if name == "QPD01ZL2RP:rdSigmaX":
            return self.qpd1_sigma_x
        if name == "QPD01ZL2RP:rdSigmaY":
            return self.qpd1_sigma_y
        if name == "QPD00ZL4RP:rdSigmaX":
            return self.qpd0_sigma_x
        if name == "QPD00ZL4RP:rdSigmaY":
            return self.qpd0_sigma_y
        if name == "SEKRRP:rdDose":
            return self.dose_rate
        if name == "CUM1ZK3RP:measCur":
            return self.beam_current_ma
        if name == "WFGENC1CP:rdVolt":
            return self.white_noise_v
        if name in self.sextupoles:
            return self.sextupoles[name]
        return 0.0


class MockEpicsAdapter:
    """Adapter with the same minimal shape as EpicsAdapter."""

    def __init__(self, model: Optional[MockMachineModel] = None):
        self.model = model or MockMachineModel()
        self._cache: Dict[str, MockPV] = {}

    def pv(self, name: str) -> MockPV:
        pv = self._cache.get(name)
        if pv is None:
            pv = MockPV(name=name, value=self.model.read(name), on_put=self.model.on_put)
            self._cache[name] = pv
        pv.value = self.model.read(name)
        return pv

    def get(self, name: str, default=None):
        value = self.model.read(name)
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        # WRITE PATH IN MOCK MODE: changes only the in-memory model.
        return self.pv(name).put(value)
