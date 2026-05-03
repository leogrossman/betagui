from __future__ import annotations

"""Generate maintainable CS-Studio Data Browser views for SSMB PoP-II studies.

The existing `v9` views work, but they are hand-edited XML and therefore painful to
maintain. This module turns the plot definitions into Python data structures so we can:

- preserve the proven hidden-dependency + XML-formula approach;
- compute baseline values from exported control-room data instead of guessing;
- keep operator labels, colors, and scales consistent across views;
- generate README / theory / PV map documents from the same source of truth.

The generated output is intentionally conservative: it favors baseline-relative trends and
simple algebraic formulas that are known to work in Phoebus Data Browser.
"""

from dataclasses import dataclass, field
from pathlib import Path
import csv
import statistics
import xml.etree.ElementTree as ET
from typing import Iterable, Mapping

FONT_TITLE = 'Liberation Sans|16|1'
FONT_LABEL = 'Liberation Sans|10|1'
FONT_SCALE = 'Liberation Sans|8|0'
FONT_LEGEND = 'Liberation Sans|9|0'
RING_SIZE = 259200
HIDDEN_AXIS = 9

L34 = 0.8594
L56 = 0.9006
S_U125 = 12.0
S_BPM4 = 9.0466
S_BPM5 = 14.9534
DU_UP = S_U125 - S_BPM4
DU_DN = S_U125 - S_BPM5

COLOR_BLACK = (0, 0, 0)
COLOR_GREY = (127, 127, 127)
COLOR_BLUE = (31, 119, 180)
COLOR_ORANGE = (255, 127, 14)
COLOR_GREEN = (44, 160, 44)
COLOR_RED = (214, 39, 40)
COLOR_PURPLE = (148, 103, 189)
COLOR_BROWN = (140, 86, 75)
COLOR_PINK = (227, 119, 194)
COLOR_CYAN = (23, 190, 207)
COLOR_OLIVE = (188, 189, 34)
COLOR_DARKBLUE = (0, 92, 175)
COLOR_DARKGREEN = (0, 120, 40)


@dataclass(frozen=True)
class PVDef:
    key: str
    pv: str
    label: str
    color: tuple[int, int, int] = COLOR_GREY


@dataclass(frozen=True)
class AxisDef:
    name: str
    visible: bool = True
    right: bool = False
    minimum: float = -1.0
    maximum: float = 1.0
    autoscale: bool = True
    grid: bool = True
    log_scale: bool = False


@dataclass(frozen=True)
class TraceDef:
    display_name: str
    axis: int
    color: tuple[int, int, int]
    visible: bool = True
    linewidth: int = 2
    request: str = 'RAW'
    point_type: str = 'NONE'
    trace_type: str = 'AREA'
    period: float = 0.0
    ring_size: int = RING_SIZE


@dataclass(frozen=True)
class PVTraceDef(TraceDef):
    pv: str = ''


@dataclass(frozen=True)
class FormulaInput:
    pv: str
    name: str


@dataclass(frozen=True)
class FormulaTraceDef(TraceDef):
    name: str = ''
    formula: str = ''
    inputs: tuple[FormulaInput, ...] = ()


@dataclass(frozen=True)
class PlotDef:
    title: str
    start: str
    end: str
    axes: tuple[AxisDef, ...]
    traces: tuple[TraceDef, ...]
    description: str


PV = {
    'x3': PVDef('x3', 'BPMZ3L2RP:rdX', 'BPM3 X upstream-1', COLOR_BLUE),
    'x4': PVDef('x4', 'BPMZ4L2RP:rdX', 'BPM4 X upstream-2', COLOR_GREEN),
    'x5': PVDef('x5', 'BPMZ5L2RP:rdX', 'BPM5 X downstream-1', COLOR_ORANGE),
    'x6': PVDef('x6', 'BPMZ6L2RP:rdX', 'BPM6 X downstream-2', COLOR_RED),
    'y3': PVDef('y3', 'BPMZ3L2RP:rdY', 'BPM3 Y upstream-1', COLOR_BLUE),
    'y4': PVDef('y4', 'BPMZ4L2RP:rdY', 'BPM4 Y upstream-2', COLOR_GREEN),
    'y5': PVDef('y5', 'BPMZ5L2RP:rdY', 'BPM5 Y downstream-1', COLOR_ORANGE),
    'y6': PVDef('y6', 'BPMZ6L2RP:rdY', 'BPM6 Y downstream-2', COLOR_RED),
    'i1': PVDef('i1', 'HS1P2K3RP:setCur', 'I1 K3 upstream', COLOR_BLUE),
    'i2': PVDef('i2', 'HS3P1L4RP:setCur', 'I2 L4 upstream', COLOR_GREEN),
    'i3': PVDef('i3', 'HS3P2L4RP:setCur', 'I3 L4 downstream', COLOR_ORANGE),
    'i4': PVDef('i4', 'HS1P1K1RP:setCur', 'I4 K1 downstream', COLOR_RED),
    'sig': PVDef('sig', 'SCOPE1ZULP:h1p1:rdAmplAv', 'P1 coherent average', COLOR_BLACK),
    'sigraw': PVDef('sigraw', 'SCOPE1ZULP:h1p1:rdAmpl', 'P1 coherent raw', COLOR_GREY),
    'sig2': PVDef('sig2', 'SCOPE1ZULP:h1p2:rdAmplAv', 'P2 average', COLOR_DARKBLUE),
    'sig3': PVDef('sig3', 'SCOPE1ZULP:h1p3:rdAmplAv', 'P3 average', COLOR_PURPLE),
    'qpd_l2x': PVDef('qpd_l2x', 'QPD01ZL2RP:rdSigmaXav', 'QPD L2 sigma X', COLOR_BLUE),
    'qpd_l2y': PVDef('qpd_l2y', 'QPD01ZL2RP:rdSigmaYav', 'QPD L2 sigma Y', COLOR_GREEN),
    'qpd_l4x': PVDef('qpd_l4x', 'QPD00ZL4RP:rdSigmaXav', 'QPD L4 sigma X', COLOR_ORANGE),
    'qpd_l4y': PVDef('qpd_l4y', 'QPD00ZL4RP:rdSigmaYav', 'QPD L4 sigma Y', COLOR_RED),
    'beam_cur': PVDef('beam_cur', 'CUM1ZK3RP:rdCur', 'Beam current', COLOR_OLIVE),
    'lt100': PVDef('lt100', 'CUM1ZK3RP:rdLt100', 'Lifetime 100 s', COLOR_PINK),
    'lt3': PVDef('lt3', 'CUM1ZK3RP:rdLt3', 'Lifetime 3 s', COLOR_BROWN),
    'rf': PVDef('rf', 'MCLKHGP:rdFrq499', 'RF readback 499 MHz', COLOR_BLUE),
    'rfset': PVDef('rfset', 'MCLKHGP:setFrq499', 'RF setpoint 499 MHz', COLOR_GREEN),
    'energy': PVDef('energy', 'ERMPCGP:rdRmp', 'Beam energy ramp', COLOR_CYAN),
    'cav': PVDef('cav', 'PAHRP:NRVD:rdVoltCav', 'Cavity voltage readback', COLOR_ORANGE),
    'cavset': PVDef('cavset', 'PAHRP:setVoltCav', 'Cavity voltage setpoint', COLOR_RED),
    'q1': PVDef('q1', 'Q1P1L2RP:setCur', 'Q1 set current (alpha0 scan knob)', COLOR_PINK),
    'u125_gap': PVDef('u125_gap', 'U125IL2RP:BasePmGap.A', 'U125 gap', COLOR_DARKGREEN),
    'purity': PVDef('purity', 'PURITYCCP:calculation', 'Purity calculation', COLOR_PURPLE),
    'oplife': PVDef('oplife', 'OPCHECKCCP:calcCurrLife', 'Current lifetime calculation', COLOR_BROWN),
    'akc05': PVDef('akc05', 'AKC05VP', 'AKC05', COLOR_BLUE),
    'akc06': PVDef('akc06', 'AKC06VP', 'AKC06', COLOR_GREEN),
    'akc10': PVDef('akc10', 'AKC10VP', 'AKC10', COLOR_ORANGE),
    'akc11': PVDef('akc11', 'AKC11VP', 'AKC11', COLOR_RED),
    'akc12': PVDef('akc12', 'AKC12VP', 'AKC12 bump reference', COLOR_PINK),
    'akc13': PVDef('akc13', 'AKC13VP', 'AKC13', COLOR_PURPLE),
    'mnf1': PVDef('mnf1', 'MNF1C1L2RP', 'MNF1', COLOR_BLUE),
    'mnf2': PVDef('mnf2', 'MNF1C2L2RP', 'MNF2', COLOR_GREEN),
    'mnf3': PVDef('mnf3', 'MNF2C2L2RP', 'MNF3', COLOR_ORANGE),
    'mnf4': PVDef('mnf4', 'MNF2C1L2RP', 'MNF4', COLOR_RED),
    'screen': PVDef('screen', 'SCRYZK3RP.VAL', 'Screen position', COLOR_BROWN),
    'wfvolt': PVDef('wfvolt', 'WFGEN2C1CP:setVolt', 'Waveform/polarization drive voltage (candidate)', COLOR_CYAN),
    'wfout': PVDef('wfout', 'WFGEN2C1CP:stOut', 'Waveform output state (candidate)', COLOR_OLIVE),
    'scopeavglen': PVDef('scopeavglen', 'SCOPE1ZULP:rdAvLength', 'Scope averaging length / shot-window proxy', COLOR_DARKBLUE),
    'cavtemp': PVDef('cavtemp', 'PAHRP:Ctrl:rdCavTempBody', 'Cavity body temperature', COLOR_BROWN),
    'plunger': PVDef('plunger', 'PAHRP:Ctrl:rdPlngPos', 'PAH plunger position', COLOR_PURPLE),
    'tunex': PVDef('tunex', 'TUNEZRP:measX', 'Tune monitor X raw', COLOR_BLUE),
    'tuney': PVDef('tuney', 'TUNEZRP:measY', 'Tune monitor Y raw', COLOR_GREEN),
    'tunez': PVDef('tunez', 'TUNEZRP:measZ', 'Tune monitor Z raw', COLOR_ORANGE),
}

FALLBACK_BASELINES = {
    'BPMZ3L2RP:rdX': -0.0694,
    'BPMZ4L2RP:rdX': -0.1746,
    'BPMZ5L2RP:rdX': -0.7574,
    'BPMZ6L2RP:rdX': -0.1691,
    'BPMZ3L2RP:rdY': -0.1427,
    'BPMZ4L2RP:rdY': -0.1669,
    'BPMZ5L2RP:rdY': -0.0526,
    'BPMZ6L2RP:rdY': -0.0292,
}


@dataclass
class ExportStats:
    values: dict[str, list[float]] = field(default_factory=dict)

    def median(self, pv: str, default: float = 0.0) -> float:
        vals = self.values.get(pv) or []
        return statistics.median(vals) if vals else default


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    indent = '\n' + level * '  '
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + '  '
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def _simple(parent: ET.Element, name: str, value: object) -> ET.Element:
    node = ET.SubElement(parent, name)
    node.text = str(value).lower() if isinstance(value, bool) else str(value)
    return node


def _color(parent: ET.Element, rgb: tuple[int, int, int]) -> None:
    node = ET.SubElement(parent, 'color')
    for comp, value in zip(('red', 'green', 'blue'), rgb):
        _simple(node, comp, value)


def load_export_stats(export_dir: Path) -> ExportStats:
    stats = ExportStats()
    for path in sorted(export_dir.glob('*.txt')):
        header = None
        rows: list[list[str]] = []
        for line in path.read_text(errors='ignore').splitlines():
            if line.startswith('# Time\t'):
                header = line[2:].split('\t')
                continue
            if header and line and not line.startswith('#'):
                rows.append(line.split('\t'))
        if not header:
            continue
        for index, column in enumerate(header[1:], start=1):
            if not column.endswith(' Value'):
                continue
            pv = column[:-6]
            bucket = stats.values.setdefault(pv, [])
            for row in rows:
                if index >= len(row):
                    continue
                try:
                    bucket.append(float(row[index]))
                except ValueError:
                    continue
    return stats


def build_context(stats: ExportStats) -> dict[str, float]:
    ctx: dict[str, float] = {}
    for key in ('x3', 'x4', 'x5', 'x6', 'y3', 'y4', 'y5', 'y6'):
        pv = PV[key].pv
        ctx[f'base_{key}'] = stats.median(pv, FALLBACK_BASELINES.get(pv, 0.0))
    for key in ('i1', 'i2', 'i3', 'i4', 'q1', 'rf', 'cav', 'tunex', 'tuney', 'tunez', 'qpd_l2x', 'qpd_l2y', 'qpd_l4x', 'qpd_l4y', 'scopeavglen', 'wfvolt', 'wfout', 'energy', 'beam_cur'):
        ctx[f'base_{key}'] = stats.median(PV[key].pv, 0.0)
    ctx['base_sum_i2'] = sum(ctx[f'base_{k}'] ** 2 for k in ('i1', 'i2', 'i3', 'i4'))
    ctx['base_x_up_ang'] = (ctx['base_x4'] - ctx['base_x3']) / L34
    ctx['base_x_dn_ang'] = (ctx['base_x6'] - ctx['base_x5']) / L56
    ctx['base_y_up_ang'] = (ctx['base_y4'] - ctx['base_y3']) / L34
    ctx['base_y_dn_ang'] = (ctx['base_y6'] - ctx['base_y5']) / L56
    ctx['base_x_mismatch'] = ctx['base_x_dn_ang'] - ctx['base_x_up_ang']
    ctx['base_y_mismatch'] = ctx['base_y_dn_ang'] - ctx['base_y_up_ang']
    ctx['base_u125_x_up'] = ctx['base_x4'] + ctx['base_x_up_ang'] * DU_UP
    ctx['base_u125_x_dn'] = ctx['base_x5'] + ctx['base_x_dn_ang'] * DU_DN
    ctx['base_u125_y_up'] = ctx['base_y4'] + ctx['base_y_up_ang'] * DU_UP
    ctx['base_u125_y_dn'] = ctx['base_y5'] + ctx['base_y_dn_ang'] * DU_DN
    return ctx


def hidden_dependencies() -> list[PVTraceDef]:
    return [
        PVTraceDef(display_name=f'dep {spec.pv}', pv=spec.pv, axis=HIDDEN_AXIS, color=COLOR_GREY, visible=False, linewidth=1)
        for spec in PV.values()
    ]


def pv_trace(spec: PVDef, axis: int, *, display_name: str | None = None, visible: bool = True, linewidth: int = 2) -> PVTraceDef:
    return PVTraceDef(display_name=display_name or spec.label, pv=spec.pv, axis=axis, color=spec.color, visible=visible, linewidth=linewidth)


def formula_trace(name: str, expr: str, inputs: Iterable[tuple[str, str]], axis: int, color: tuple[int, int, int], *, visible: bool = True, linewidth: int = 2) -> FormulaTraceDef:
    return FormulaTraceDef(
        display_name=name,
        name=name,
        formula=expr,
        inputs=tuple(FormulaInput(PV[pv_key].pv, alias) for pv_key, alias in inputs),
        axis=axis,
        color=color,
        visible=visible,
        linewidth=linewidth,
    )


def formula_exprs(ctx: Mapping[str, float]) -> dict[str, str]:
    return {
        'mean_dx': f'0.25*((x3-({ctx["base_x3"]}))+(x4-({ctx["base_x4"]}))+(x5-({ctx["base_x5"]}))+(x6-({ctx["base_x6"]})))',
        'x_up_ang_dev': f'((x4-x3)/{L34}-({ctx["base_x_up_ang"]}))',
        'x_dn_ang_dev': f'((x6-x5)/{L56}-({ctx["base_x_dn_ang"]}))',
        'x_mismatch_dev': f'(((x6-x5)/{L56})-((x4-x3)/{L34})-({ctx["base_x_mismatch"]}))',
        'y_up_ang_dev': f'((y4-y3)/{L34}-({ctx["base_y_up_ang"]}))',
        'y_dn_ang_dev': f'((y6-y5)/{L56}-({ctx["base_y_dn_ang"]}))',
        'y_mismatch_dev': f'(((y6-y5)/{L56})-((y4-y3)/{L34})-({ctx["base_y_mismatch"]}))',
        'u125_x_up_dev': f'(x4+((x4-x3)/{L34})*({DU_UP})-({ctx["base_u125_x_up"]}))',
        'u125_x_dn_dev': f'(x5+((x6-x5)/{L56})*({DU_DN})-({ctx["base_u125_x_dn"]}))',
        'u125_y_up_dev': f'(y4+((y4-y3)/{L34})*({DU_UP})-({ctx["base_u125_y_up"]}))',
        'u125_y_dn_dev': f'(y5+((y6-y5)/{L56})*({DU_DN})-({ctx["base_u125_y_dn"]}))',
        'u125_x_consistency': f'((x5+((x6-x5)/{L56})*({DU_DN}))-(x4+((x4-x3)/{L34})*({DU_UP}))-({ctx["base_u125_x_dn"] - ctx["base_u125_x_up"]}))',
        'u125_y_consistency': f'((y5+((y6-y5)/{L56})*({DU_DN}))-(y4+((y4-y3)/{L34})*({DU_UP}))-({ctx["base_u125_y_dn"] - ctx["base_u125_y_up"]}))',
        'sum_i2_dev': f'((i1*i1+i2*i2+i3*i3+i4*i4)-({sum(ctx[f"base_{k}"] ** 2 for k in ("i1", "i2", "i3", "i4"))}))',
        'lr_balance_dev': f'((i1+i4)-(i2+i3)-(({ctx["base_i1"]}+{ctx["base_i4"]})-({ctx["base_i2"]}+{ctx["base_i3"]})))',
        'pair_balance_dev': f'((i1+i2-i3-i4)-(({ctx["base_i1"]}+{ctx["base_i2"]})-({ctx["base_i3"]}+{ctx["base_i4"]})))',
        'q1_dev': f'(q1-({ctx["base_q1"]}))',
        'rf_dev_hz': f'(rf-({ctx["base_rf"]}))',
        'energy_dev': f'(energy-({ctx["base_energy"]}))',
        'cav_dev': f'(cav-({ctx["base_cav"]}))',
        'tunex_dev': f'(tunex-({ctx["base_tunex"]}))',
        'tuney_dev': f'(tuney-({ctx["base_tuney"]}))',
        'tunez_dev': f'(tunez-({ctx["base_tunez"]}))',
        'qpd_l2x_pct': f'(100*(qpd_l2x-({ctx["base_qpd_l2x"]}))/({ctx["base_qpd_l2x"] if ctx["base_qpd_l2x"] else 1.0}))',
        'qpd_l2y_pct': f'(100*(qpd_l2y-({ctx["base_qpd_l2y"]}))/({ctx["base_qpd_l2y"] if ctx["base_qpd_l2y"] else 1.0}))',
        'qpd_l4x_pct': f'(100*(qpd_l4x-({ctx["base_qpd_l4x"]}))/({ctx["base_qpd_l4x"] if ctx["base_qpd_l4x"] else 1.0}))',
        'qpd_l4y_pct': f'(100*(qpd_l4y-({ctx["base_qpd_l4y"]}))/({ctx["base_qpd_l4y"] if ctx["base_qpd_l4y"] else 1.0}))',
    }


def build_plot_defs(ctx: Mapping[str, float]) -> list[PlotDef]:
    expr = formula_exprs(ctx)
    x_inputs = (('x3', 'x3'), ('x4', 'x4'), ('x5', 'x5'), ('x6', 'x6'))
    y_inputs = (('y3', 'y3'), ('y4', 'y4'), ('y5', 'y5'), ('y6', 'y6'))
    i_inputs = (('i1', 'i1'), ('i2', 'i2'), ('i3', 'i3'), ('i4', 'i4'))

    raw_plot = PlotDef(
        title='SSMB PoP-II raw sanity: BPMs + steerers + signal + machine knobs',
        start='-10 minutes',
        end='now',
        axes=(
            AxisDef('P1/P2/P3 scope signals [raw units]', minimum=0.0, maximum=0.01, autoscale=True),
            AxisDef('BPM raw positions [mm]', minimum=-1.0, maximum=1.0, autoscale=True, right=True),
            AxisDef('Steerers / Q1 / AKC / MNF [raw]', minimum=-1.0, maximum=1.0, autoscale=True),
            AxisDef('QPD sigmas [raw]', minimum=0.0, maximum=600.0, autoscale=True, right=True),
            AxisDef('Tune / RF / cavity / shot-window / laser setting [raw]', minimum=-1.0, maximum=1.0, autoscale=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            pv_trace(PV['sig'], 0, display_name='P1 coherent avg', linewidth=3),
            pv_trace(PV['sig2'], 0, display_name='P2 avg', visible=False),
            pv_trace(PV['sig3'], 0, display_name='P3 avg', visible=False),
            pv_trace(PV['x3'], 1, display_name='BPM3 X raw'),
            pv_trace(PV['x4'], 1, display_name='BPM4 X raw'),
            pv_trace(PV['x5'], 1, display_name='BPM5 X raw'),
            pv_trace(PV['x6'], 1, display_name='BPM6 X raw'),
            pv_trace(PV['y3'], 1, display_name='BPM3 Y raw', visible=False),
            pv_trace(PV['y4'], 1, display_name='BPM4 Y raw', visible=False),
            pv_trace(PV['y5'], 1, display_name='BPM5 Y raw', visible=False),
            pv_trace(PV['y6'], 1, display_name='BPM6 Y raw', visible=False),
            pv_trace(PV['i1'], 2, display_name='I1 raw'),
            pv_trace(PV['i2'], 2, display_name='I2 raw'),
            pv_trace(PV['i3'], 2, display_name='I3 raw'),
            pv_trace(PV['i4'], 2, display_name='I4 raw'),
            pv_trace(PV['q1'], 2, display_name='Q1 raw'),
            pv_trace(PV['qpd_l2x'], 3, display_name='QPD L2 sigma X'),
            pv_trace(PV['qpd_l2y'], 3, display_name='QPD L2 sigma Y'),
            pv_trace(PV['qpd_l4x'], 3, display_name='QPD L4 sigma X'),
            pv_trace(PV['qpd_l4y'], 3, display_name='QPD L4 sigma Y'),
            pv_trace(PV['tunex'], 4, display_name='Tune X raw', visible=False),
            pv_trace(PV['tuney'], 4, display_name='Tune Y raw', visible=False),
            pv_trace(PV['tunez'], 4, display_name='Tune Z raw', visible=False),
            pv_trace(PV['rf'], 4, display_name='RF readback', visible=False),
            pv_trace(PV['cav'], 4, display_name='Cavity voltage', visible=False),
            pv_trace(PV['scopeavglen'], 4, display_name='Scope avg length', visible=False),
            pv_trace(PV['wfvolt'], 4, display_name='WFGEN2 voltage', visible=False),
            pv_trace(PV['wfout'], 4, display_name='WFGEN2 output state', visible=False),
        ),
        description='Open first to confirm raw PV connectivity before trusting formulas.',
    )

    formula_smoke = PlotDef(
        title='Formula smoke test: BPM3/BPM4 upstream X angle only',
        start='-10 minutes',
        end='now',
        axes=(
            AxisDef('BPM3/BPM4 X raw [mm]', minimum=-0.3, maximum=0.0, autoscale=True),
            AxisDef('Upstream X angle [mrad]', minimum=-0.05, maximum=0.05, autoscale=True, right=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            pv_trace(PV['x3'], 0, display_name='BPM3 X raw', linewidth=2),
            pv_trace(PV['x4'], 0, display_name='BPM4 X raw', linewidth=2),
            formula_trace('BPM34 upstream X angle [mrad]', f'((x4-x3)/{L34})', (('x3', 'x3'), ('x4', 'x4')), 1, COLOR_RED, linewidth=3),
        ),
        description='Isolates the XML-formula mechanism to one proven calculation.',
    )

    overview = PlotDef(
        title='SSMB PoP-II overview: signal + U125 angle/offset proxies + bumper/Q1 context',
        start='-10 minutes',
        end='now',
        axes=(
            AxisDef('Scope signal amplitude [raw units]', minimum=0.002, maximum=0.008, autoscale=True),
            AxisDef('Stacked derived diagnostics (see labels for scale)', minimum=0.0, maximum=10.5, autoscale=False, right=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            pv_trace(PV['sig'], 0, display_name='BLACK P1 coherent avg', linewidth=3),
            pv_trace(PV['sig3'], 0, display_name='PURPLE P3 avg', visible=False),
            formula_trace('BLUE 0.8 + 18·mean ΔX U125 BPMs [mm]', f'0.8+18*({expr["mean_dx"]})', x_inputs, 1, COLOR_BLUE, linewidth=3),
            formula_trace('GREEN 2.0 + 10·Δx′ mismatch [mrad]', f'2.0+10*({expr["x_mismatch_dev"]})', x_inputs, 1, COLOR_GREEN, linewidth=3),
            formula_trace('ORANGE 3.2 + 10·Δy′ mismatch [mrad]', f'3.2+10*({expr["y_mismatch_dev"]})', y_inputs, 1, COLOR_ORANGE, linewidth=3),
            formula_trace('RED 4.4 + 20·U125 X consistency [mm]', f'4.4+20*({expr["u125_x_consistency"]})', x_inputs, 1, COLOR_RED, linewidth=3),
            formula_trace('PINK 5.6 + 20·U125 Y consistency [mm]', f'5.6+20*({expr["u125_y_consistency"]})', y_inputs, 1, COLOR_PINK, linewidth=3),
            formula_trace('CYAN 6.8 + 8·ΔΣI² [A²]', f'6.8+8*({expr["sum_i2_dev"]})', i_inputs, 1, COLOR_CYAN, linewidth=3),
            formula_trace('BROWN 8.0 + 5·ΔQ1 [A]', f'8.0+5*({expr["q1_dev"]})', (('q1', 'q1'),), 1, COLOR_BROWN, linewidth=3),
            formula_trace('OLIVE 9.2 + 0.2·ΔQPD L2 σx [%]', f'9.2+0.2*({expr["qpd_l2x_pct"]})', (('qpd_l2x', 'qpd_l2x'),), 1, COLOR_OLIVE, linewidth=3),
        ),
        description='Operational overview with stacked deviation traces so small trends remain visible instead of flattening.',
    )

    orbit = PlotDef(
        title='U125 orbit / offset / angle detail: deviations from exported baselines',
        start='-30 minutes',
        end='now',
        axes=(
            AxisDef('BPM ΔX from baseline [mm]', minimum=-0.05, maximum=0.05, autoscale=False),
            AxisDef('BPM ΔY from baseline [mm]', minimum=-0.10, maximum=0.10, autoscale=False, right=True),
            AxisDef('U125 inferred center / consistency [mm]', minimum=-0.10, maximum=0.10, autoscale=False),
            AxisDef('U125 angle deviations [mrad]', minimum=-0.10, maximum=0.10, autoscale=False, right=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            formula_trace('BPM3 ΔX from baseline [mm]', f'(x3-({ctx["base_x3"]}))', x_inputs, 0, COLOR_BLUE),
            formula_trace('BPM4 ΔX from baseline [mm]', f'(x4-({ctx["base_x4"]}))', x_inputs, 0, COLOR_GREEN),
            formula_trace('BPM5 ΔX from baseline [mm]', f'(x5-({ctx["base_x5"]}))', x_inputs, 0, COLOR_ORANGE),
            formula_trace('BPM6 ΔX from baseline [mm]', f'(x6-({ctx["base_x6"]}))', x_inputs, 0, COLOR_RED),
            formula_trace('BPM3 ΔY from baseline [mm]', f'(y3-({ctx["base_y3"]}))', y_inputs, 1, COLOR_BLUE),
            formula_trace('BPM4 ΔY from baseline [mm]', f'(y4-({ctx["base_y4"]}))', y_inputs, 1, COLOR_GREEN),
            formula_trace('BPM5 ΔY from baseline [mm]', f'(y5-({ctx["base_y5"]}))', y_inputs, 1, COLOR_ORANGE),
            formula_trace('BPM6 ΔY from baseline [mm]', f'(y6-({ctx["base_y6"]}))', y_inputs, 1, COLOR_RED),
            formula_trace('U125 X from upstream pair Δ [mm]', expr['u125_x_up_dev'], x_inputs, 2, COLOR_DARKBLUE),
            formula_trace('U125 X from downstream pair Δ [mm]', expr['u125_x_dn_dev'], x_inputs, 2, COLOR_PINK),
            formula_trace('U125 X consistency downstream-upstream [mm]', expr['u125_x_consistency'], x_inputs, 2, COLOR_RED),
            formula_trace('U125 Y from upstream pair Δ [mm]', expr['u125_y_up_dev'], y_inputs, 2, COLOR_DARKGREEN, visible=False),
            formula_trace('U125 Y from downstream pair Δ [mm]', expr['u125_y_dn_dev'], y_inputs, 2, COLOR_PURPLE, visible=False),
            formula_trace('U125 Y consistency downstream-upstream [mm]', expr['u125_y_consistency'], y_inputs, 2, COLOR_BROWN),
            formula_trace('x′ upstream Δ [mrad]', expr['x_up_ang_dev'], x_inputs, 3, COLOR_BLUE),
            formula_trace('x′ downstream Δ [mrad]', expr['x_dn_ang_dev'], x_inputs, 3, COLOR_ORANGE),
            formula_trace('Δx′ mismatch [mrad]', expr['x_mismatch_dev'], x_inputs, 3, COLOR_RED),
            formula_trace('y′ upstream Δ [mrad]', expr['y_up_ang_dev'], y_inputs, 3, COLOR_GREEN),
            formula_trace('y′ downstream Δ [mrad]', expr['y_dn_ang_dev'], y_inputs, 3, COLOR_PINK),
            formula_trace('Δy′ mismatch [mrad]', expr['y_mismatch_dev'], y_inputs, 3, COLOR_BROWN),
        ),
        description='Tracks whether the beam position and angle through the undulator stay close to the good-overlap reference while scanning alpha0 / bumper settings.',
    )

    machine = PlotDef(
        title='Bumper + Q1/alpha0 + AKC/MNF machine context',
        start='-30 minutes',
        end='now',
        axes=(
            AxisDef('Steerer current deviations [mA]', minimum=-1.0, maximum=1.0, autoscale=False),
            AxisDef('Derived bumper proxies [A or A²]', minimum=-0.1, maximum=0.1, autoscale=False, right=True),
            AxisDef('Q1 / energy deviations', minimum=-0.5, maximum=0.5, autoscale=True),
            AxisDef('AKC raw values', minimum=-5.0, maximum=5.0, autoscale=True, right=True),
            AxisDef('MNF / U125 raw values', minimum=-20.0, maximum=400.0, autoscale=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            formula_trace('1000·ΔI1 [mA]', f'1000*(i1-({ctx["base_i1"]}))', i_inputs, 0, COLOR_BLUE),
            formula_trace('1000·ΔI2 [mA]', f'1000*(i2-({ctx["base_i2"]}))', i_inputs, 0, COLOR_GREEN),
            formula_trace('1000·ΔI3 [mA]', f'1000*(i3-({ctx["base_i3"]}))', i_inputs, 0, COLOR_ORANGE),
            formula_trace('1000·ΔI4 [mA]', f'1000*(i4-({ctx["base_i4"]}))', i_inputs, 0, COLOR_RED),
            formula_trace('ΔΣI² [A²]', expr['sum_i2_dev'], i_inputs, 1, COLOR_CYAN),
            formula_trace('Δ left-right balance [A]', expr['lr_balance_dev'], i_inputs, 1, COLOR_PINK),
            formula_trace('Δ pair balance [A]', expr['pair_balance_dev'], i_inputs, 1, COLOR_BROWN),
            formula_trace('ΔQ1 [A]', expr['q1_dev'], (('q1', 'q1'),), 2, COLOR_PINK),
            formula_trace('ΔEnergy ramp [MeV]', expr['energy_dev'], (('energy', 'energy'),), 2, COLOR_CYAN),
            pv_trace(PV['q1'], 3, display_name='Q1 actual current', linewidth=3),
            pv_trace(PV['akc12'], 3, display_name='AKC12 bump reference', linewidth=2),
            pv_trace(PV['akc05'], 3, display_name='AKC05', visible=False),
            pv_trace(PV['akc06'], 3, display_name='AKC06', visible=False),
            pv_trace(PV['akc10'], 3, display_name='AKC10', visible=False),
            pv_trace(PV['akc11'], 3, display_name='AKC11', visible=False),
            pv_trace(PV['akc13'], 3, display_name='AKC13', visible=False),
            pv_trace(PV['mnf1'], 4, display_name='MNF1', linewidth=2),
            pv_trace(PV['mnf2'], 4, display_name='MNF2', linewidth=2),
            pv_trace(PV['mnf3'], 4, display_name='MNF3', linewidth=2),
            pv_trace(PV['mnf4'], 4, display_name='MNF4', linewidth=2),
            pv_trace(PV['u125_gap'], 4, display_name='U125 gap', visible=False),
        ),
        description='Combines bumper steerers with the global quadrupole knob Q1P1L2RP:setCur and machine context values relevant to alpha0 scans.',
    )

    signal = PlotDef(
        title='Signal + QPD/profile + tune/RF + shot-window / laser-setting proxies',
        start='-30 minutes',
        end='now',
        axes=(
            AxisDef('Coherent / scope signals [raw units]', minimum=0.0, maximum=0.01, autoscale=True),
            AxisDef('QPD sigma deviations [%]', minimum=-10.0, maximum=10.0, autoscale=False, right=True),
            AxisDef('Tune/RF deviations', minimum=-50.0, maximum=50.0, autoscale=True),
            AxisDef('Scope average length / WFGEN2 setting', minimum=-1.0, maximum=5000.0, autoscale=True, right=True),
            AxisDef('hidden', visible=False),
        ),
        traces=tuple(hidden_dependencies()) + (
            pv_trace(PV['sig'], 0, display_name='P1 coherent avg', linewidth=3),
            pv_trace(PV['sig2'], 0, display_name='P2 avg', visible=False),
            pv_trace(PV['sig3'], 0, display_name='P3 avg', visible=False),
            formula_trace('QPD L2 σx deviation [%]', expr['qpd_l2x_pct'], (('qpd_l2x', 'qpd_l2x'),), 1, COLOR_BLUE),
            formula_trace('QPD L2 σy deviation [%]', expr['qpd_l2y_pct'], (('qpd_l2y', 'qpd_l2y'),), 1, COLOR_GREEN),
            formula_trace('QPD L4 σx deviation [%]', expr['qpd_l4x_pct'], (('qpd_l4x', 'qpd_l4x'),), 1, COLOR_ORANGE),
            formula_trace('QPD L4 σy deviation [%]', expr['qpd_l4y_pct'], (('qpd_l4y', 'qpd_l4y'),), 1, COLOR_RED),
            formula_trace('Δ tune monitor X [counts]', expr['tunex_dev'], (('tunex', 'tunex'),), 2, COLOR_BLUE),
            formula_trace('Δ tune monitor Y [counts]', expr['tuney_dev'], (('tuney', 'tuney'),), 2, COLOR_GREEN),
            formula_trace('Δ tune monitor Z [counts]', expr['tunez_dev'], (('tunez', 'tunez'),), 2, COLOR_ORANGE),
            formula_trace('Δ RF readback [Hz]', expr['rf_dev_hz'], (('rf', 'rf'),), 2, COLOR_PINK),
            formula_trace('Δ cavity voltage', expr['cav_dev'], (('cav', 'cav'),), 2, COLOR_BROWN, visible=False),
            pv_trace(PV['scopeavglen'], 3, display_name='Scope averaging length / shot-window proxy', linewidth=3),
            pv_trace(PV['wfvolt'], 3, display_name='WFGEN2 voltage (candidate laser setting)', linewidth=2),
            pv_trace(PV['wfout'], 3, display_name='WFGEN2 output state', linewidth=2),
        ),
        description='P1/P2/P3 together with QPD profile changes, tune/RF drift, and the best currently identified proxies for shots / laser-state context.',
    )

    return [raw_plot, formula_smoke, overview, orbit, machine, signal]


def _add_axis(parent: ET.Element, axis: AxisDef) -> None:
    node = ET.SubElement(parent, 'axis')
    _simple(node, 'visible', axis.visible)
    _simple(node, 'name', axis.name)
    _simple(node, 'use_axis_name', True)
    _simple(node, 'use_trace_names', False)
    _simple(node, 'right', axis.right)
    _color(node, COLOR_BLACK)
    _simple(node, 'min', axis.minimum)
    _simple(node, 'max', axis.maximum)
    _simple(node, 'grid', axis.grid)
    _simple(node, 'autoscale', axis.autoscale)
    _simple(node, 'log_scale', axis.log_scale)


def _add_trace(parent: ET.Element, trace: TraceDef) -> None:
    tag = 'formula' if isinstance(trace, FormulaTraceDef) else 'pv'
    node = ET.SubElement(parent, tag)
    _simple(node, 'display_name', trace.display_name)
    _simple(node, 'visible', trace.visible)
    _simple(node, 'name', trace.display_name if isinstance(trace, FormulaTraceDef) else trace.pv)
    _simple(node, 'axis', trace.axis)
    _color(node, trace.color)
    _simple(node, 'trace_type', trace.trace_type)
    _simple(node, 'linewidth', trace.linewidth)
    _simple(node, 'line_style', 'SOLID')
    _simple(node, 'point_type', trace.point_type)
    _simple(node, 'point_size', 2)
    _simple(node, 'waveform_index', 0)
    _simple(node, 'period', trace.period)
    _simple(node, 'ring_size', trace.ring_size)
    if isinstance(trace, FormulaTraceDef):
        _simple(node, 'formula', trace.formula)
        for item in trace.inputs:
            input_node = ET.SubElement(node, 'input')
            _simple(input_node, 'pv', item.pv)
            _simple(input_node, 'name', item.name)
    else:
        _simple(node, 'request', trace.request)


def plot_to_xml(plot: PlotDef) -> str:
    root = ET.Element('databrowser')
    _simple(root, 'title', plot.title)
    _simple(root, 'show_legend', True)
    _simple(root, 'show_toolbar', True)
    _simple(root, 'grid', True)
    _simple(root, 'update_period', 1.0)
    _simple(root, 'scroll_step', 5)
    _simple(root, 'scroll', True)
    _simple(root, 'start', plot.start)
    _simple(root, 'end', plot.end)
    _simple(root, 'archive_rescale', 'NONE')
    fg = ET.SubElement(root, 'foreground')
    for comp, value in zip(('red', 'green', 'blue'), COLOR_BLACK):
        _simple(fg, comp, value)
    bg = ET.SubElement(root, 'background')
    for comp, value in zip(('red', 'green', 'blue'), (255, 255, 255)):
        _simple(bg, comp, value)
    _simple(root, 'title_font', FONT_TITLE)
    _simple(root, 'label_font', FONT_LABEL)
    _simple(root, 'scale_font', FONT_SCALE)
    _simple(root, 'legend_font', FONT_LEGEND)
    axes = ET.SubElement(root, 'axes')
    for axis in plot.axes:
        _add_axis(axes, axis)
    ET.SubElement(root, 'annotations')
    pvlist = ET.SubElement(root, 'pvlist')
    for trace in plot.traces:
        _add_trace(pvlist, trace)
    _indent_xml(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def write_plot(plot: PlotDef, path: Path) -> None:
    path.write_text(plot_to_xml(plot))


def generate_pv_map(path: Path) -> None:
    with path.open('w', newline='') as fp:
        writer = csv.writer(fp)
        writer.writerow(['key', 'PV', 'meaning'])
        for spec in PV.values():
            writer.writerow([spec.key, spec.pv, spec.label])


def build_readme(ctx: Mapping[str, float]) -> str:
    return f"""# SSMB PoP-II CS-Studio diagnostics v10 (generated)

This package is generated from `phoebusgen/ssmb_views.py` so the working PV list,
operator labels, and formula definitions stay consistent. The older working files remain
untouched:

- `../orignal--leo_20260502_SSMB_PoPII_scanshots.plt`
- `../bumper_full_diag_v9/`

## Open order in the control room

1. `00_raw_sanity_no_formulas_10min.plt`
2. `99_formula_smoke_test_open_first.plt`
3. `01_core_operator_overview_10min.plt`
4. `02_u125_orbit_offset_angle_30min.plt`
5. `03_bumper_alpha0_machine_30min.plt`
6. `04_signal_qpd_rf_laser_30min.plt`

## Key additions relative to v9

- generator-driven `.plt` files instead of hand-editing;
- explicit `Q1P1L2RP:setCur` tracking for alpha0 scans;
- inferred U125 center / consistency traces so you can see whether the undulator beam line stays sane;
- percent-deviation QPD traces so small optics changes do not flatten;
- shot-window and laser-setting proxies included as visible context:
  - `SCOPE1ZULP:rdAvLength`
  - `WFGEN2C1CP:setVolt`
  - `WFGEN2C1CP:stOut`

## Important caveats

- Exact shot-count PV is still unverified in this repo. `SCOPE1ZULP:rdAvLength` is used as a practical averaging / shot-window proxy.
- Exact polarization-plate / laser-power PV chain is still unverified. `WFGEN2C1CP:setVolt` and `WFGEN2C1CP:stOut` are kept as candidate laser-setting context PVs because they already appear in the working control-room views.
- Tune monitor values are treated as baseline-relative monitor counts, not as already-calibrated machine tune values.

## Baselines used for deviation plots

| Quantity | Baseline |
|---|---:|
| BPM3 X | {ctx['base_x3']:.6f} mm |
| BPM4 X | {ctx['base_x4']:.6f} mm |
| BPM5 X | {ctx['base_x5']:.6f} mm |
| BPM6 X | {ctx['base_x6']:.6f} mm |
| BPM3 Y | {ctx['base_y3']:.6f} mm |
| BPM4 Y | {ctx['base_y4']:.6f} mm |
| BPM5 Y | {ctx['base_y5']:.6f} mm |
| BPM6 Y | {ctx['base_y6']:.6f} mm |
| Q1 current | {ctx['base_q1']:.6f} A |
| RF readback | {ctx['base_rf']:.6f} |
| Energy ramp | {ctx['base_energy']:.6f} |

## What each generated view is for

### `01_core_operator_overview_10min.plt`

Use this during the live scan. The black trace is the main `P1` signal. The stacked colored traces deliberately magnify small drifts:

- blue: mean U125 horizontal orbit drift;
- green: horizontal angle mismatch across U125;
- orange: vertical angle mismatch across U125;
- red: U125 horizontal consistency (downstream minus upstream extrapolation);
- pink: U125 vertical consistency;
- cyan: bumper-strength proxy `ΔΣI²`;
- brown: `ΔQ1`;
- olive: `QPD01 sigmaX` percentage change.

### `02_u125_orbit_offset_angle_30min.plt`

Use this when you need to answer: *is the beam position/angle near the undulator becoming too crazy while Q1 or the bumper changes?*

### `03_bumper_alpha0_machine_30min.plt`

Use this when scanning the global quads. It keeps `Q1P1L2RP:setCur`, the four bumper steerers, `AKC12VP`, and the `MNF*` controls in one place.

### `04_signal_qpd_rf_laser_30min.plt`

Use this when you want to compare signal changes against profile-size changes, RF drift, and the best currently known shot-window / laser-setting proxies.

## What to test first in the control room

1. Open `00_raw_sanity_no_formulas_10min.plt`.
2. Verify `P1`, BPMs, steerers, `Q1P1L2RP:setCur`, and QPD sigmas all update.
3. Open `99_formula_smoke_test_open_first.plt`.
4. If the formula trace works, move to `01_core_operator_overview_10min.plt`.
5. While changing `Q1P1L2RP:setCur`, watch whether `Δx′`, `Δy′`, and U125 consistency stay quiet.
6. If they do not, open `02_u125_orbit_offset_angle_30min.plt` and `03_bumper_alpha0_machine_30min.plt` side by side.

## Regenerate after edits

```bash
cd /path/to/betagui
python3 CS_studio/generate_ssmb_cs_plots.py
```
"""


def build_theory(ctx: Mapping[str, float]) -> str:
    return f"""# Theory and interpretation for generated CS-Studio v10

## Why these plots exist

The question is not only whether the four-steerer bumper changes the path length, but whether it also perturbs the beam position and angle through the undulator region, changes the effective overlap with the laser, or leaks into optics-sensitive quantities while Q1 is scanned.

## U125 angle proxies

```text
x'_34 = (x4 - x3) / {L34}
x'_56 = (x6 - x5) / {L56}
Δx'  = x'_56 - x'_34
```

and analogously for `y`.

## Inferred U125 center from BPM pairs

```text
x_U125,up = x4 + x'_34 * ({DU_UP})
x_U125,dn = x5 + x'_56 * ({DU_DN})
```

The plots show both extrapolations and their consistency. If the consistency remains near zero, the straight-line picture through U125 is relatively stable. If it grows during scans, the beam line through the undulator is distorting.

## Why Q1P1L2RP:setCur matters

`Q1P1L2RP:setCur` is the global quadrupole / alpha0 scan knob. It must be visible alongside bumper currents, not hidden in the background.

## Bumper strength proxy

```text
ΣI² = I1² + I2² + I3² + I4²
```

is used as an operational proxy because path-length effects scale approximately with squared kick / slope. v10 mostly shows changes of this quantity relative to the good-overlap baseline.

## QPD interpretation

The exported absolute QPD sigma values are large:

- QPD L2 sigma X baseline: {ctx['base_qpd_l2x']:.3f}
- QPD L2 sigma Y baseline: {ctx['base_qpd_l2y']:.3f}
- QPD L4 sigma X baseline: {ctx['base_qpd_l4x']:.3f}
- QPD L4 sigma Y baseline: {ctx['base_qpd_l4y']:.3f}

To keep subtle optics changes visible, v10 shows percentage deviations from those baselines instead of raw values.

## Practical checklist

During a scan ask:

1. Did P1 move while ΔQ1 changed as intended?
2. Did Δx′, Δy′, or U125 consistency move at the same time?
3. Did ΣI² or steerer balance drift unexpectedly?
4. Did the QPD sigma deviations move by several percent?
5. Did RF or shot-window / laser-setting proxies move too?

If yes to 2–5, the signal change is not a clean one-variable Q1/alpha0 effect.
"""


def render_package(export_dir: Path, output_dir: Path) -> None:
    stats = load_export_stats(export_dir)
    ctx = build_context(stats)
    output_dir.mkdir(parents=True, exist_ok=True)
    plots = build_plot_defs(ctx)
    names = [
        '00_raw_sanity_no_formulas_10min.plt',
        '99_formula_smoke_test_open_first.plt',
        '01_core_operator_overview_10min.plt',
        '02_u125_orbit_offset_angle_30min.plt',
        '03_bumper_alpha0_machine_30min.plt',
        '04_signal_qpd_rf_laser_30min.plt',
    ]
    for plot, name in zip(plots, names):
        write_plot(plot, output_dir / name)
    (output_dir / 'README.md').write_text(build_readme(ctx))
    (output_dir / 'theory.md').write_text(build_theory(ctx))
    generate_pv_map(output_dir / 'pv_map.csv')


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Generate maintainable CS-Studio .plt views for SSMB PoP-II diagnostics.')
    parser.add_argument('--export-dir', default='CS_studio/control_room_cs_studio_outputs/cs-studiov5')
    parser.add_argument('--output-dir', default='CS_studio/bumper_full_diag_v10_generated')
    parser.add_argument('--repo-root', default=None)
    args = parser.parse_args(argv)

    here = Path(__file__).resolve()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else here.parents[2]
    export_dir = (repo_root / args.export_dir).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    render_package(export_dir, output_dir)
    print(f'Generated CS-Studio package at {output_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
