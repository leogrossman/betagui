from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from .lattice import LatticeContext, LatticeElement


@dataclass(frozen=True)
class ChannelSpec:
    label: str
    pv: Optional[str]
    kind: str
    required: bool = False
    notes: str = ""
    tags: Sequence[str] = ()


LEGACY_SCALAR_CHANNELS = [
    ChannelSpec("rf_setpoint", "MCLKHGP:setFrq", "scalar", required=True, notes="Legacy RF setpoint/readback PV.", tags=("rf",)),
    ChannelSpec("rf_readback", "MCLKHGP:setFrq", "scalar", required=True, notes="Using the same legacy RF PV until a separate readback PV is verified.", tags=("rf",)),
    ChannelSpec("tune_x_raw", "TUNEZRP:measX", "scalar", required=True, notes="Horizontal tune monitor frequency-like readback.", tags=("tune",)),
    ChannelSpec("tune_y_raw", "TUNEZRP:measY", "scalar", required=True, notes="Vertical tune monitor frequency-like readback.", tags=("tune",)),
    ChannelSpec("tune_s_raw", "cumz4x003gp:tuneSyn", "scalar", required=True, notes="Synchrotron monitor compared against master clock.", tags=("tune", "longitudinal")),
    ChannelSpec("cavity_voltage_kv", "PAHRP:setVoltCav", "scalar", required=True, notes="Cavity voltage readback/setpoint.", tags=("rf",)),
    ChannelSpec("beam_energy_mev", "ERMPCGP:rdRmp", "scalar", required=True, notes="Beam energy ramp readback.", tags=("beam",)),
    ChannelSpec("beam_current", "CUM1ZK3RP:measCur", "scalar", notes="Beam current.", tags=("beam",)),
    ChannelSpec("optics_mode", "MLSOPCCP:actOptRmpTblSet", "scalar", notes="Optics table / mode.", tags=("machine_state",)),
    ChannelSpec("orbit_mode", "ORBITCCP:selRunMode", "scalar", notes="Orbit correction selection.", tags=("machine_state",)),
    ChannelSpec("orbit_mode_readback", "RMC00VP", "scalar", notes="Orbit-related readback used by betagui.", tags=("machine_state",)),
    ChannelSpec("feedback_x", "IGPF:X:FBCTRL", "scalar", notes="Horizontal feedback state.", tags=("feedback",)),
    ChannelSpec("feedback_y", "IGPF:Y:FBCTRL", "scalar", notes="Vertical feedback state.", tags=("feedback",)),
    ChannelSpec("feedback_s", "IGPF:Z:FBCTRL", "scalar", notes="Longitudinal feedback state.", tags=("feedback",)),
    ChannelSpec("lifetime_10h", "CUM1ZK3RP:rdLt10", "scalar", notes="10 h lifetime readback.", tags=("beam",)),
    ChannelSpec("lifetime_100h", "CUM1ZK3RP:rdLt100", "scalar", notes="100 h lifetime readback.", tags=("beam",)),
    ChannelSpec("calculated_lifetime", "OPCHECKCCP:calcCurrLife", "scalar", notes="Calculated lifetime.", tags=("beam",)),
    ChannelSpec("qpd_l2_sigma_x", "QPD01ZL2RP:rdSigmaX", "scalar", notes="L2 beam-size proxy at QPD01 / QPD01ZL2RP beam-screen monitor.", tags=("diagnostics", "u125_region")),
    ChannelSpec("qpd_l2_sigma_y", "QPD01ZL2RP:rdSigmaY", "scalar", notes="L2 beam-size proxy at QPD01 / QPD01ZL2RP beam-screen monitor.", tags=("diagnostics", "u125_region")),
    ChannelSpec("qpd_l4_sigma_x", "QPD00ZL4RP:rdSigmaX", "scalar", notes="L4 beam-size proxy at QPD00 / QPD00ZL4RP beam-screen monitor (alias seen as qpdz0rp).", tags=("diagnostics", "l4")),
    ChannelSpec("qpd_l4_sigma_y", "QPD00ZL4RP:rdSigmaY", "scalar", notes="L4 beam-size proxy at QPD00 / QPD00ZL4RP beam-screen monitor (alias seen as qpdz0rp).", tags=("diagnostics", "l4")),
    ChannelSpec("dose_rate", "SEKRRP:rdDose", "scalar", notes="Dose-rate readback.", tags=("diagnostics",)),
    ChannelSpec("white_noise", "WFGENC1CP:rdVolt", "scalar", notes="White-noise drive / readback.", tags=("rf", "diagnostics")),
    ChannelSpec("bpm_buffer_raw", "BPMZ1X003GP:rdBufBpm", "waveform", notes="Legacy BPM orbit waveform/buffer readback.", tags=("orbit", "waveform")),
]

OPTIONAL_EXPERIMENT_CHANNELS = [
    ChannelSpec("l4_bump_h1", None, "scalar", notes="Fill in when the L4 bump corrector PV is verified.", tags=("bump", "optional")),
    ChannelSpec("l4_bump_h2", None, "scalar", notes="Fill in when the L4 bump corrector PV is verified.", tags=("bump", "optional")),
    ChannelSpec("l4_bump_v1", None, "scalar", notes="Fill in when the L4 bump corrector PV is verified.", tags=("bump", "optional")),
    ChannelSpec("u125_gap", None, "scalar", notes="Fill in when the U125 gap/position PV is verified.", tags=("u125", "optional")),
    ChannelSpec("global_clock", None, "scalar", notes="Fill in when the master/global clock PV is verified.", tags=("clock", "optional")),
    ChannelSpec("alpha1", None, "scalar", notes="Optional direct machine proxy for alpha1 if available.", tags=("alpha", "optional")),
    ChannelSpec("alpha2", None, "scalar", notes="Optional direct machine proxy for alpha2 if available.", tags=("alpha", "optional")),
    ChannelSpec("eta1", None, "scalar", notes="Optional direct machine proxy for eta1 if available.", tags=("eta", "optional")),
    ChannelSpec("eta2", None, "scalar", notes="Optional direct machine proxy for eta2 if available.", tags=("eta", "optional")),
]


def _monitor_specs(elements: Iterable[LatticeElement], region_tag: str) -> List[ChannelSpec]:
    specs: List[ChannelSpec] = []
    for element in elements:
        if element.element_type != "Monitor":
            continue
        x_pv = None
        y_pv = None
        for candidate in element.pv_candidates:
            if candidate.endswith(":rdX") and x_pv is None:
                x_pv = candidate
            elif candidate.endswith(":rdY") and y_pv is None:
                y_pv = candidate
        specs.append(
            ChannelSpec(
                label="%s_x" % element.family_name.lower(),
                pv=x_pv,
                kind="scalar",
                notes="%s horizontal BPM candidate near %s." % (element.family_name, region_tag),
                tags=("bpm", region_tag),
            )
        )
        specs.append(
            ChannelSpec(
                label="%s_y" % element.family_name.lower(),
                pv=y_pv,
                kind="scalar",
                notes="%s vertical BPM candidate near %s." % (element.family_name, region_tag),
                tags=("bpm", region_tag),
            )
        )
    return specs


def _octupole_specs(elements: Iterable[LatticeElement]) -> List[ChannelSpec]:
    return _power_supply_specs(elements, "octupole")


def _power_supply_specs(elements: Iterable[LatticeElement], device_tag: str) -> List[ChannelSpec]:
    seen = set()
    specs: List[ChannelSpec] = []
    for element in elements:
        pv_name = element.power_supply_rd_pv or element.power_supply_set_pv
        if not pv_name or pv_name in seen:
            continue
        seen.add(pv_name)
        specs.append(
            ChannelSpec(
                label=element.family_name.lower(),
                pv=pv_name,
                kind="scalar",
                notes="%s %s current/readback candidate." % (element.family_name, device_tag),
                tags=(device_tag, element.section or "ring"),
            )
        )
    return specs


def build_default_inventory(
    lattice: LatticeContext,
    extra_pvs: Optional[Dict[str, str]] = None,
    extra_optional_pvs: Optional[Dict[str, Optional[str]]] = None,
) -> List[ChannelSpec]:
    specs: List[ChannelSpec] = list(LEGACY_SCALAR_CHANNELS)
    specs.extend(_monitor_specs(lattice.u125_neighborhood(), "u125_region"))
    specs.extend(_monitor_specs(lattice.l4_straight(), "l4"))
    specs.extend(_monitor_specs(lattice.monitors(), "ring"))
    specs.extend(_power_supply_specs(lattice.sextupoles(), "sextupole"))
    specs.extend(_power_supply_specs(lattice.octupoles(), "octupole"))
    specs.extend(_power_supply_specs(lattice.quadrupoles(), "quadrupole"))
    optional_map = dict(extra_optional_pvs or {})
    for spec in OPTIONAL_EXPERIMENT_CHANNELS:
        pv_name = optional_map.get(spec.label, spec.pv)
        specs.append(ChannelSpec(spec.label, pv_name, spec.kind, spec.required, spec.notes, spec.tags))
    for label, pv_name in (extra_pvs or {}).items():
        specs.append(ChannelSpec(label=label, pv=pv_name, kind="scalar", notes="User-supplied extra PV.", tags=("extra",)))
    deduped: List[ChannelSpec] = []
    seen = set()
    for spec in specs:
        if spec.label in seen:
            continue
        deduped.append(spec)
        seen.add(spec.label)
    return deduped


def inventory_summary(specs: Sequence[ChannelSpec]) -> Dict[str, object]:
    return {
        "channel_count": len(specs),
        "required_count": sum(1 for spec in specs if spec.required),
        "labels": [spec.label for spec in specs],
    }
