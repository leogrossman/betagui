"""Small EPICS access helpers for the betagui port.

This module keeps machine-facing access separate from logic that can be tested
offline. It is intentionally small and avoids hiding much behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


class EpicsUnavailableError(RuntimeError):
    """Raised when pyepics is not available but live access was requested."""


def _import_epics():
    try:
        import epics  # type: ignore
    except ImportError as exc:
        raise EpicsUnavailableError(
            "pyepics is not available; use mock_epics for offline work."
        ) from exc
    return epics


class PVHandle:
    """Minimal PV wrapper used by the ported code."""

    def __init__(self, pv, name: str):
        self._pv = pv
        self.name = name

    def get(self):
        return self._pv.get()

    def put(self, value):
        # WRITE PATH: this changes a live PV when backed by pyepics.
        return self._pv.put(value)

    @property
    def connected(self) -> Optional[bool]:
        return getattr(self._pv, "connected", None)


class EpicsAdapter:
    """Tiny factory/cache for PV objects."""

    def __init__(self, timeout: float = 1.0):
        self.timeout = timeout
        self._epics = _import_epics()
        self._cache: Dict[str, PVHandle] = {}

    def pv(self, name: str) -> PVHandle:
        handle = self._cache.get(name)
        if handle is None:
            pv = self._epics.PV(name, connection_timeout=self.timeout)
            handle = PVHandle(pv, name)
            self._cache[name] = handle
        return handle

    def get(self, name: str, default=None):
        value = self.pv(name).get()
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        # WRITE PATH: this changes a live PV when backed by pyepics.
        return self.pv(name).put(value)

    def snapshot(self, names: Iterable[str]) -> Dict[str, object]:
        return {name: self.get(name) for name in names}


@dataclass
class BetaguiPVs:
    """Common PV names used by the legacy tool."""

    tune_x: Optional[str] = "TUNEZRP:measX"
    tune_y: Optional[str] = "TUNEZRP:measY"
    tune_s: Optional[str] = "TUNEZRP:measZ"
    rf_setpoint: Optional[str] = "MCLKHGP:setFrq"
    optics_mode: Optional[str] = "MLSOPCCP:actOptRmpTblSet"
    orbit_mode: Optional[str] = "ORBITCCP:selRunMode"
    orbit_mode_readback: Optional[str] = "RMC00VP"
    feedback_x: Optional[str] = "IGPF:X:FBCTRL"
    feedback_y: Optional[str] = "IGPF:Y:FBCTRL"
    feedback_s: Optional[str] = "IGPF:Z:FBCTRL"
    cavity_voltage: Optional[str] = "PAHRP:setVoltCav"
    beam_energy: Optional[str] = "ERMPCGP:rdRmp"
    phase_modulation: Optional[str] = "PAHRP:cmdExtPhasMod"
    beam_lifetime_10h: Optional[str] = "CUM1ZK3RP:rdLt10"
    beam_lifetime_100h: Optional[str] = "CUM1ZK3RP:rdLt100"
    calculated_lifetime: Optional[str] = "OPCHECKCCP:calcCurrLife"
    qpd1_sigma_x: Optional[str] = "QPD01ZL2RP:rdSigmaX"
    qpd1_sigma_y: Optional[str] = "QPD01ZL2RP:rdSigmaY"
    qpd0_sigma_x: Optional[str] = "QPD00ZL4RP:rdSigmaX"
    qpd0_sigma_y: Optional[str] = "QPD00ZL4RP:rdSigmaY"
    dose_rate: Optional[str] = "SEKRRP:rdDose"
    beam_current: Optional[str] = "CUM1ZK3RP:measCur"
    white_noise: Optional[str] = "WFGENC1CP:rdVolt"
    sext_s1p1: Optional[str] = "S1P1RP:setCur"
    sext_s1p2: Optional[str] = "S1P2RP:setCur"
    sext_s2p1: Optional[str] = "S2P1RP:setCur"
    sext_s2p2: Optional[str] = "S2P2RP:setCur"
    sext_s2p2k: Optional[str] = "S2P2KRP:setCur"
    sext_s2p2l: Optional[str] = "S2P2LRP:setCur"
    sext_s3p1: Optional[str] = "S3P1RP:setCur"
    sext_s3p2: Optional[str] = "S3P2RP:setCur"

    def sextupole_names(self):
        return [
            self.sext_s1p1,
            self.sext_s1p2,
            self.sext_s2p1,
            self.sext_s2p2k,
            self.sext_s2p2l,
            self.sext_s3p1,
            self.sext_s3p2,
        ]

    @classmethod
    def legacy(cls) -> "BetaguiPVs":
        return cls()

    @classmethod
    def twin_mls(cls, prefix: str = "leo") -> "BetaguiPVs":
        leader = prefix.strip(":")
        if leader:
            leader = leader + ":"
        return cls(
            tune_x=leader + "beam:twiss:x:tune",
            tune_y=leader + "beam:twiss:y:tune",
            tune_s=None,
            rf_setpoint=leader + "MCLKHGP:rdFrq",
            optics_mode=None,
            orbit_mode=None,
            orbit_mode_readback=None,
            feedback_x=None,
            feedback_y=None,
            feedback_s=None,
            cavity_voltage=None,
            beam_energy=None,
            phase_modulation=None,
            beam_lifetime_10h=None,
            beam_lifetime_100h=None,
            calculated_lifetime=None,
            qpd1_sigma_x=None,
            qpd1_sigma_y=None,
            qpd0_sigma_x=None,
            qpd0_sigma_y=None,
            dose_rate=None,
            beam_current=None,
            white_noise=None,
            sext_s1p1=leader + "S1P1RP:setCur",
            sext_s1p2=leader + "S1P2RP:setCur",
            sext_s2p1=leader + "S2P1RP:setCur",
            sext_s2p2=leader + "S2P2RP:setCur",
            sext_s2p2k=leader + "S2P2KRP:setCur",
            sext_s2p2l=leader + "S2P2LRP:setCur",
            sext_s3p1=leader + "S3P1RP:setCur",
            sext_s3p2=leader + "S3P2RP:setCur",
        )
