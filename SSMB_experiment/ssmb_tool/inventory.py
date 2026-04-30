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
    unit: str = ""


LEGACY_SCALAR_CHANNELS = [
    ChannelSpec("rf_setpoint", "MCLKHGP:setFrq", "scalar", required=True, notes="Legacy RF setpoint/readback PV.", tags=("rf",), unit="kHz"),
    ChannelSpec("rf_readback", "MCLKHGP:setFrq", "scalar", required=True, notes="Using the same legacy RF PV until a separate readback PV is verified.", tags=("rf",), unit="kHz"),
    ChannelSpec("rf_readback_499mhz", "MCLKHGP:rdFrq499", "scalar", notes="Observed 499 MHz RF readback channel from the control-room scope panel.", tags=("rf",), unit="kHz"),
    ChannelSpec("tune_x_raw", "TUNEZRP:measX", "scalar", required=True, notes="Horizontal tune monitor frequency-like readback.", tags=("tune",), unit="raw"),
    ChannelSpec("tune_y_raw", "TUNEZRP:measY", "scalar", required=True, notes="Vertical tune monitor frequency-like readback.", tags=("tune",), unit="raw"),
    ChannelSpec("tune_s_raw", "cumz4x003gp:tuneSyn", "scalar", required=True, notes="Synchrotron monitor compared against master clock.", tags=("tune", "longitudinal"), unit="kHz"),
    ChannelSpec("cavity_voltage_kv", "PAHRP:setVoltCav", "scalar", required=True, notes="Cavity voltage readback/setpoint.", tags=("rf",), unit="kV"),
    ChannelSpec("beam_energy_mev", "ERMPCGP:rdRmp", "scalar", required=True, notes="Beam energy ramp readback.", tags=("beam",), unit="MeV"),
    ChannelSpec("beam_current", "CUM1ZK3RP:measCur", "scalar", notes="Beam current.", tags=("beam",), unit="mA"),
    ChannelSpec("beam_current_scope", "mlsCurrent:Mnt3collectData.VALD", "scalar", notes="Beam current/collection data channel seen in the control-room scope panel.", tags=("beam", "diagnostics"), unit="uA"),
    ChannelSpec("p1_h1_ampl", "SCOPE1ZULP:h1p1:rdAmpl", "scalar", notes="Live P1 harmonic amplitude monitor from the control-room scope panel.", tags=("ssmb_light", "p1"), unit="arb"),
    ChannelSpec("p1_h1_ampl_avg", "SCOPE1ZULP:h1p1:rdAmplAv", "scalar", notes="Average P1 harmonic amplitude monitor from the control-room scope panel.", tags=("ssmb_light", "p1", "average"), unit="arb"),
    ChannelSpec("p1_h1_ampl_dev", "SCOPE1ZULP:h1p1:rdAmplDev", "scalar", notes="Standard deviation of P1 harmonic amplitude from the control-room scope panel.", tags=("ssmb_light", "p1", "statistics"), unit="arb"),
    ChannelSpec("p3_h1_ampl", "SCOPE1ZULP:h1p3:rdAmpl", "scalar", notes="Live P3 harmonic amplitude monitor from the control-room scope panel.", tags=("ssmb_light", "p3"), unit="arb"),
    ChannelSpec("p3_h1_ampl_avg", "SCOPE1ZULP:h1p3:rdAmplAv", "scalar", notes="Average P3 harmonic amplitude monitor from the control-room scope panel.", tags=("ssmb_light", "p3", "average"), unit="arb"),
    ChannelSpec("optics_mode", "MLSOPCCP:actOptRmpTblSet", "scalar", notes="Optics table / mode.", tags=("machine_state",)),
    ChannelSpec("orbit_mode", "ORBITCCP:selRunMode", "scalar", notes="Orbit correction selection.", tags=("machine_state",)),
    ChannelSpec("orbit_mode_readback", "RMC00VP", "scalar", notes="Orbit-related readback used by betagui.", tags=("machine_state",)),
    ChannelSpec("feedback_x", "IGPF:X:FBCTRL", "scalar", notes="Horizontal feedback state.", tags=("feedback",)),
    ChannelSpec("feedback_y", "IGPF:Y:FBCTRL", "scalar", notes="Vertical feedback state.", tags=("feedback",)),
    ChannelSpec("feedback_s", "IGPF:Z:FBCTRL", "scalar", notes="Longitudinal feedback state.", tags=("feedback",)),
    ChannelSpec("lifetime_10h", "CUM1ZK3RP:rdLt10", "scalar", notes="10 h lifetime readback.", tags=("beam",)),
    ChannelSpec("lifetime_100h", "CUM1ZK3RP:rdLt100", "scalar", notes="100 h lifetime readback.", tags=("beam",)),
    ChannelSpec("calculated_lifetime", "OPCHECKCCP:calcCurrLife", "scalar", notes="Calculated lifetime.", tags=("beam",)),
    ChannelSpec("qpd_l2_sigma_x", "QPD01ZL2RP:rdSigmaX", "scalar", notes="L2 beam-size proxy at QPD01 / QPD01ZL2RP beam-screen monitor.", tags=("diagnostics", "u125_region"), unit="mm"),
    ChannelSpec("qpd_l2_sigma_y", "QPD01ZL2RP:rdSigmaY", "scalar", notes="L2 beam-size proxy at QPD01 / QPD01ZL2RP beam-screen monitor.", tags=("diagnostics", "u125_region"), unit="mm"),
    ChannelSpec("qpd_l2_sigma_y_avg", "QPD01ZL2RP:rdSigmaYav", "scalar", notes="Archived averaged Sigma-Y channel seen in copied control-room scripts for the QPD01 / QPD01ZL2RP synchrotron-radiation camera/profile monitor.", tags=("diagnostics", "u125_region", "average"), unit="mm"),
    ChannelSpec("qpd_l2_center_x_avg_um", "QPD01ZL2RP:rdCenterXav", "scalar", notes="Averaged X-center channel seen on the control-room strip-chart panel for the QPD01 / QPD01ZL2RP synchrotron-radiation camera/profile monitor.", tags=("diagnostics", "u125_region", "center"), unit="um"),
    ChannelSpec("qpd_l4_sigma_x", "QPD00ZL4RP:rdSigmaX", "scalar", notes="L4 beam-size proxy at QPD00 / QPD00ZL4RP beam-screen monitor (alias seen as qpdz0rp).", tags=("diagnostics", "l4"), unit="mm"),
    ChannelSpec("qpd_l4_sigma_y", "QPD00ZL4RP:rdSigmaY", "scalar", notes="L4 beam-size proxy at QPD00 / QPD00ZL4RP beam-screen monitor (alias seen as qpdz0rp).", tags=("diagnostics", "l4"), unit="mm"),
    ChannelSpec("qpd_l4_sigma_y_avg", "QPD00ZL4RP:rdSigmaYav", "scalar", notes="Archived averaged Sigma-Y channel seen in copied control-room scripts for the QPD00 / QPD00ZL4RP synchrotron-radiation camera/profile monitor.", tags=("diagnostics", "l4", "average"), unit="mm"),
    ChannelSpec("qpd_l4_center_x_avg_um", "QPD00ZL4RP:rdCenterXav", "scalar", notes="Averaged X-center channel seen on the control-room strip-chart panel for the QPD00 / QPD00ZL4RP synchrotron-radiation camera/profile monitor.", tags=("diagnostics", "l4", "center"), unit="um"),
    ChannelSpec("climate_kw13_return_temp_c", "KLIMAC1CP:coolKW13:rdRetTemp", "scalar", notes="Cooling-water return temperature seen on the control-room strip-chart panel near the SSMB diagnostics.", tags=("temperature", "cooling", "environment"), unit="C"),
    ChannelSpec("climate_sr_temp_c", "KLIMAC1CP:sr:rdTemp", "scalar", notes="SR-area temperature channel seen on the control-room strip-chart panel.", tags=("temperature", "environment", "sr"), unit="C"),
    ChannelSpec("climate_sr_temp1_c", "KLIMAC1CP:sr:rd1Temp", "scalar", notes="Second SR-area temperature channel seen on the control-room strip-chart panel.", tags=("temperature", "environment", "sr"), unit="C"),
    ChannelSpec("dose_rate", "SEKRRP:rdDose", "scalar", notes="Dose-rate readback.", tags=("diagnostics",), unit="Sv/h"),
    ChannelSpec("white_noise", "WFGENC1CP:rdVolt", "scalar", notes="White-noise drive / readback.", tags=("rf", "diagnostics"), unit="V"),
    ChannelSpec("bpm_buffer_raw", "BPMZ1X003GP:rdBufBpm", "waveform", notes="Legacy BPM orbit waveform/buffer readback.", tags=("orbit", "waveform")),
]

OPTIONAL_EXPERIMENT_CHANNELS = [
    ChannelSpec(
        "l4_bump_hcorr_k3_upstream",
        "HS1P2K3RP:setCur",
        "scalar",
        notes="Recovered L4 bump corrector current in upstream K3. The recovered notebook suggests this corrector is part of a local corrector winding integrated into the sextupole package.",
        tags=("bump", "corrector", "k3"),
    ),
    ChannelSpec(
        "l4_bump_hcorr_l4_upstream",
        "HS3P1L4RP:setCur",
        "scalar",
        notes="Recovered L4 bump corrector current in upstream L4. The recovered notebook suggests this corrector is part of a local corrector winding integrated into the sextupole package.",
        tags=("bump", "corrector", "l4"),
    ),
    ChannelSpec(
        "l4_bump_hcorr_l4_downstream",
        "HS3P2L4RP:setCur",
        "scalar",
        notes="Recovered L4 bump corrector current in downstream L4. The recovered notebook suggests this corrector is part of a local corrector winding integrated into the sextupole package.",
        tags=("bump", "corrector", "l4"),
    ),
    ChannelSpec(
        "l4_bump_hcorr_k1_downstream",
        "HS1P1K1RP:setCur",
        "scalar",
        notes="Recovered L4 bump corrector current in downstream K1. The recovered notebook suggests this corrector is part of a local corrector winding integrated into the sextupole package.",
        tags=("bump", "corrector", "k1"),
    ),
    ChannelSpec("l4_bump_feedback_enable", "AKC10VP", "scalar", notes="Recovered bump-loop enable PV.", tags=("bump", "controller")),
    ChannelSpec("l4_bump_feedback_gain", "AKC11VP", "scalar", notes="Recovered bump-loop gain PV.", tags=("bump", "controller")),
    ChannelSpec("l4_bump_feedback_ref", "AKC12VP", "scalar", notes="Recovered bump-loop orbit-reference PV.", tags=("bump", "controller")),
    ChannelSpec("l4_bump_feedback_deadband", "AKC13VP", "scalar", notes="Recovered bump-loop deadband PV.", tags=("bump", "controller")),
    ChannelSpec(
        "rf_frequency_control_enable",
        "MCLKHGP:ctrl:enable",
        "scalar",
        notes="Recovered RF frequency control enable PV. The bump-loop notebook disables frequency control while the bump loop is active.",
        tags=("rf", "controller"),
    ),
    ChannelSpec(
        "l4_bump_orbit_bpm_k1",
        "BPMZ1K1RP:rdX",
        "scalar",
        notes="Recovered bump-loop BPM used in the arithmetic orbit average. OCR from the photo looked like BPMZ1IK1RP, but the MLS naming pattern strongly indicates BPMZ1K1RP.",
        tags=("bump", "bpm", "k1"),
    ),
    ChannelSpec("l4_bump_orbit_bpm_l2", "BPMZ1L2RP:rdX", "scalar", notes="Recovered bump-loop BPM used in the arithmetic orbit average.", tags=("bump", "bpm", "l2")),
    ChannelSpec("l4_bump_orbit_bpm_k3", "BPMZ1K3RP:rdX", "scalar", notes="Recovered bump-loop BPM used in the arithmetic orbit average.", tags=("bump", "bpm", "k3")),
    ChannelSpec("l4_bump_orbit_bpm_l4", "BPMZ1L4RP:rdX", "scalar", notes="Recovered bump-loop BPM used in the arithmetic orbit average.", tags=("bump", "bpm", "l4")),
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
                unit="mm",
            )
        )
        specs.append(
            ChannelSpec(
                label="%s_y" % element.family_name.lower(),
                pv=y_pv,
                kind="scalar",
                notes="%s vertical BPM candidate near %s." % (element.family_name, region_tag),
                tags=("bpm", region_tag),
                unit="mm",
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
                unit="A",
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
        specs.append(ChannelSpec(spec.label, pv_name, spec.kind, spec.required, spec.notes, spec.tags, spec.unit))
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


def spec_index(specs: Sequence[ChannelSpec]) -> Dict[str, ChannelSpec]:
    return {spec.label: spec for spec in specs}
