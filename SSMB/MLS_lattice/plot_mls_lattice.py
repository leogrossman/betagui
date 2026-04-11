#!/usr/bin/env python3
"""Generate optics and synoptic plots for the MLS lattice."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

import matplotlib
import numpy as np


def _configure_matplotlib() -> None:
    cache_root = Path(tempfile.gettempdir()) / "mls_lattice_matplotlib"
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg-cache"))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    matplotlib.use("Agg")


_configure_matplotlib()

import at  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "mlsreflat-main" / "src"
DATA_ROOT = SRC_ROOT / "mlsreflat" / "storage_ring" / "data"
LATTICE_PATH = SRC_ROOT / "mlsreflat" / "storage_ring" / "lattice.py"
POWER_SUPPLY_PATH = SRC_ROOT / "mlsreflat" / "storage_ring" / "mls_storage_ring_power_supplies.json"
INVENTORY_PATH = ROOT / "reference" / "control_room_inventory_20260410" / "inventory.json"


def _install_reflat_stubs() -> None:
    reflat_tools = types.ModuleType("reflat_tools")
    lattice_mod = types.ModuleType("reflat_tools.lattice")
    configuration_mod = types.ModuleType("reflat_tools.configuration")
    paths_mod = types.ModuleType("reflat_tools.paths")

    def create_lattice(parts, name: str, energy: float):
        elements = []
        for part in parts:
            if isinstance(part, (list, tuple)):
                elements.extend(part)
            else:
                elements.append(part)
        return at.Lattice(elements, name=name, energy=energy)

    class DefaultPath:
        def __init__(self, _package: str):
            self.base = DATA_ROOT

        def set_filepath(self, filename: str) -> Path:
            return self.base / filename

    def set_configuration(ring: at.Lattice, filepath: Path) -> at.Lattice:
        with Path(filepath).open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        for row in rows:
            element = (row.get("element") or "").strip()
            attribute = (row.get("attribute") or "").strip()
            if not element or not attribute:
                continue
            value = float(row["value"])
            index_text = (row.get("index") or "").strip()
            index = int(index_text) if index_text else None

            for elem in ring:
                if elem.FamName != element:
                    continue
                if attribute in {"K", "H"}:
                    setattr(elem, attribute, value)
                elif attribute in {"PolynomA", "PolynomB"}:
                    array = np.array(getattr(elem, attribute), dtype=float, copy=True)
                    if index is None:
                        raise ValueError(f"Missing index for {element}.{attribute}")
                    if len(array) <= index:
                        array = np.pad(array, (0, index + 1 - len(array)))
                    array[index] = value
                    setattr(elem, attribute, array)
                else:
                    setattr(elem, attribute, value)
        return ring

    lattice_mod.create_lattice = create_lattice
    configuration_mod.set_configuration = set_configuration
    paths_mod.DefaultPath = DefaultPath

    sys.modules["reflat_tools"] = reflat_tools
    sys.modules["reflat_tools.lattice"] = lattice_mod
    sys.modules["reflat_tools.configuration"] = configuration_mod
    sys.modules["reflat_tools.paths"] = paths_mod


def load_ring(config_name: str) -> at.Lattice:
    _install_reflat_stubs()
    sys.path.insert(0, str(SRC_ROOT))

    spec = importlib.util.spec_from_file_location("mls_lattice_module", LATTICE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    ring = module.mls_storage_ring()

    if config_name != "bare":
        config_spec = importlib.util.spec_from_file_location(
            "mls_config_module", SRC_ROOT / "mlsreflat" / "storage_ring" / "configurations.py"
        )
        config_module = importlib.util.module_from_spec(config_spec)
        assert config_spec.loader is not None
        config_spec.loader.exec_module(config_module)
        ring = getattr(config_module, config_name)(ring)

    return ring


SECTION_STYLES = {
    "K1": "#f4a261",
    "L2": "#2a9d8f",
    "K3": "#577590",
    "L4": "#e76f51",
}

ELEMENT_STYLES = {
    "Dipole": ("#264653", 0.75),
    "Quadrupole": ("#1d3557", 0.55),
    "Sextupole": ("#e63946", 0.45),
    "Octupole": ("#6a4c93", 0.35),
    "RFCavity": ("#f4d35e", 0.8),
    "Monitor": ("#6c757d", 0.18),
    "Marker": ("#111111", 0.12),
}


def section_from_name(name: str) -> str | None:
    match = re.search(r"(K1|L2|K3|L4)RP\b", name)
    return match.group(1) if match else None


def section_spans(ring: at.Lattice) -> list[tuple[str, float, float]]:
    spans: list[tuple[str, float, float]] = []
    positions = ring.get_s_pos(range(len(ring) + 1))
    current_section = None
    start = 0.0

    for idx, elem in enumerate(ring):
        section = section_from_name(elem.FamName)
        if section is None:
            continue
        if current_section is None:
            current_section = section
            start = positions[idx]
            continue
        if section != current_section:
            spans.append((current_section, start, positions[idx]))
            current_section = section
            start = positions[idx]

    if current_section is not None:
        spans.append((current_section, start, positions[-1]))

    return spans


def element_bars(ring: at.Lattice) -> list[tuple[float, float, str, str]]:
    positions = ring.get_s_pos(range(len(ring) + 1))
    bars = []
    for idx, elem in enumerate(ring):
        elem_type = type(elem).__name__
        if elem_type not in ELEMENT_STYLES:
            continue
        start = positions[idx]
        end = positions[idx + 1]
        if end <= start:
            end = start + 0.02
        bars.append((start, end, elem_type, elem.FamName))
    return bars


def get_optics(ring: at.Lattice):
    ring = ring.deepcopy()
    if hasattr(ring, "disable_6d"):
        ring.disable_6d()
    ld, bd, data = at.get_optics(ring, refpts=range(len(ring) + 1), method=at.linopt4)
    return ld, bd, data


def annotate_special_positions(ax, ring: at.Lattice, y_top: float) -> None:
    positions = ring.get_s_pos(range(len(ring) + 1))
    for idx, elem in enumerate(ring):
        if elem.FamName == "CAV":
            s = 0.5 * (positions[idx] + positions[idx + 1])
            ax.axvline(s, color="#ffb703", lw=1.5, ls="--", alpha=0.8)
            ax.text(s, y_top, "RF cavity (L4)", rotation=90, va="top", ha="right", fontsize=9)
        if elem.FamName == "U125":
            s = positions[idx]
            ax.axvline(s, color="#2a9d8f", lw=1.5, ls="--", alpha=0.8)
            ax.text(s, y_top, "U125 undulator", rotation=90, va="top", ha="left", fontsize=9)


def plot_full_lattice(ring: at.Lattice, config_name: str, output_path: Path) -> None:
    _, _, data = get_optics(ring)
    s = data.s_pos
    beta_x = data.beta[:, 0]
    beta_y = data.beta[:, 1]
    dispersion = data.dispersion[:, 0]

    fig = plt.figure(figsize=(16, 9), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[3.2, 1.2, 1.2])
    ax_beta = fig.add_subplot(gs[0])
    ax_eta = fig.add_subplot(gs[1], sharex=ax_beta)
    ax_syn = fig.add_subplot(gs[2], sharex=ax_beta)

    ax_beta.plot(s, beta_x, label=r"$\beta_x$", color="#1d3557", lw=2.0)
    ax_beta.plot(s, beta_y, label=r"$\beta_y$", color="#d62828", lw=2.0)
    ax_beta.set_ylabel("beta [m]")
    ax_beta.set_title(f"MLS lattice optics ({config_name})")
    ax_beta.grid(True, alpha=0.25)
    ax_beta.legend(loc="upper right")

    y_top = max(beta_x.max(), beta_y.max()) * 0.97
    for section, start, end in section_spans(ring):
        ax_beta.axvspan(start, end, color=SECTION_STYLES[section], alpha=0.08)
        ax_beta.text((start + end) / 2, y_top, section, ha="center", va="top", fontsize=10)
    annotate_special_positions(ax_beta, ring, y_top)

    ax_eta.plot(s, dispersion, color="#2a9d8f", lw=2.0)
    ax_eta.axhline(0.0, color="black", lw=0.8, alpha=0.5)
    ax_eta.set_ylabel("eta_x [m]")
    ax_eta.grid(True, alpha=0.25)

    for start, end, elem_type, _ in element_bars(ring):
        color, height = ELEMENT_STYLES[elem_type]
        ax_syn.add_patch(Rectangle((start, 0.0), end - start, height, facecolor=color, edgecolor="none"))

    ax_syn.set_ylim(0, 0.9)
    ax_syn.set_yticks([])
    ax_syn.set_xlabel("s [m]")
    ax_syn.set_ylabel("synoptic")
    ax_syn.grid(True, axis="x", alpha=0.25)

    legend_handles = [
        Rectangle((0, 0), 1, 1, facecolor=color, edgecolor="none", label=elem_type)
        for elem_type, (color, _) in ELEMENT_STYLES.items()
        if elem_type in {"Dipole", "Quadrupole", "Sextupole", "Octupole", "RFCavity", "Monitor"}
    ]
    ax_syn.legend(handles=legend_handles, loc="upper right", ncol=3, fontsize=9)

    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_l2_undulator_zoom(ring: at.Lattice, config_name: str, output_path: Path) -> None:
    _, _, data = get_optics(ring)
    s = data.s_pos
    beta_x = data.beta[:, 0]
    beta_y = data.beta[:, 1]
    dispersion = data.dispersion[:, 0]

    positions = ring.get_s_pos(range(len(ring) + 1))
    u_start = None
    for idx, elem in enumerate(ring):
        if elem.FamName == "U125":
            u_start = positions[idx]
            u_end = positions[idx + 1]
            break
    if u_start is None:
        raise RuntimeError("U125 marker not found")

    l2_candidates = [(start, end) for name, start, end in section_spans(ring) if name == "L2"]
    l2_start = min(start for start, _ in l2_candidates)
    l2_end = max(end for _, end in l2_candidates)

    window_start = max(l2_start, u_start - 4.5)
    window_end = min(l2_end, u_end + 4.5)
    mask = (s >= window_start) & (s <= window_end)

    fig = plt.figure(figsize=(16, 8), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[3.0, 1.0, 1.4])
    ax_beta = fig.add_subplot(gs[0])
    ax_eta = fig.add_subplot(gs[1], sharex=ax_beta)
    ax_syn = fig.add_subplot(gs[2], sharex=ax_beta)

    ax_beta.plot(s[mask], beta_x[mask], color="#1d3557", lw=2.0, label=r"$\beta_x$")
    ax_beta.plot(s[mask], beta_y[mask], color="#d62828", lw=2.0, label=r"$\beta_y$")
    ax_beta.axvspan(window_start, window_end, color=SECTION_STYLES["L2"], alpha=0.08)
    ax_beta.axvline(u_start, color="#2a9d8f", lw=1.5, ls="--", alpha=0.85)
    ax_beta.text(u_start, max(beta_y[mask]) * 0.97, "U125 undulator", rotation=90, va="top", ha="left", fontsize=10)
    ax_beta.set_title(f"L2 / U125 straight zoom ({config_name})")
    ax_beta.set_ylabel("beta [m]")
    ax_beta.legend(loc="upper right")
    ax_beta.grid(True, alpha=0.25)

    ax_eta.plot(s[mask], dispersion[mask], color="#2a9d8f", lw=2.0)
    ax_eta.axhline(0.0, color="black", lw=0.8, alpha=0.5)
    ax_eta.set_ylabel("eta_x [m]")
    ax_eta.grid(True, alpha=0.25)

    for start, end, elem_type, name in element_bars(ring):
        if end < window_start or start > window_end:
            continue
        color, height = ELEMENT_STYLES[elem_type]
        ax_syn.add_patch(Rectangle((start, 0.0), end - start, height, facecolor=color, edgecolor="none"))
        if name in {"U125", "BM1L2RP", "BM2L2RP", "OML2RP"}:
            x = (start + end) / 2 if name != "U125" else start
            ax_syn.text(x, height + 0.03, name, ha="center", va="bottom", fontsize=9)

    for idx, elem in enumerate(ring):
        center = 0.5 * (positions[idx] + positions[idx + 1])
        if window_start <= center <= window_end and elem.FamName.startswith(("BPM", "Q", "S", "BM")):
            ax_beta.text(center, max(beta_y[mask]) * 0.9, elem.FamName, rotation=90, fontsize=8, ha="center", va="top")

    ax_syn.set_ylim(0, 0.9)
    ax_syn.set_yticks([])
    ax_syn.set_xlabel("s [m]")
    ax_syn.set_ylabel("synoptic")
    ax_syn.grid(True, axis="x", alpha=0.25)
    ax_syn.set_xlim(window_start, window_end)

    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_l4_zoom(ring: at.Lattice, config_name: str, output_path: Path) -> None:
    _, _, data = get_optics(ring)
    s = data.s_pos
    beta_x = data.beta[:, 0]
    beta_y = data.beta[:, 1]
    dispersion = data.dispersion[:, 0]

    spans = section_spans(ring)
    l4_candidates = [(start, end) for name, start, end in spans if name == "L4"]
    l4_start = min(start for start, _ in l4_candidates)
    l4_end = max(end for _, end in l4_candidates)
    margin = 0.3
    mask = (s >= l4_start - margin) & (s <= l4_end + margin)

    fig = plt.figure(figsize=(16, 8), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[3.0, 1.0, 1.4])
    ax_beta = fig.add_subplot(gs[0])
    ax_eta = fig.add_subplot(gs[1], sharex=ax_beta)
    ax_syn = fig.add_subplot(gs[2], sharex=ax_beta)

    ax_beta.plot(s[mask], beta_x[mask], color="#1d3557", lw=2.0, label=r"$\beta_x$")
    ax_beta.plot(s[mask], beta_y[mask], color="#d62828", lw=2.0, label=r"$\beta_y$")
    ax_beta.axvspan(l4_start, l4_end, color=SECTION_STYLES["L4"], alpha=0.12)
    ax_beta.set_ylabel("beta [m]")
    ax_beta.set_title(f"L4 straight zoom ({config_name})")
    ax_beta.legend(loc="upper right")
    ax_beta.grid(True, alpha=0.25)

    y_top = max(beta_x[mask].max(), beta_y[mask].max()) * 0.97
    annotate_special_positions(ax_beta, ring, y_top)

    positions = ring.get_s_pos(range(len(ring) + 1))
    for idx, elem in enumerate(ring):
        center = 0.5 * (positions[idx] + positions[idx + 1])
        if l4_start <= center <= l4_end and elem.FamName.startswith(("BPM", "Q", "S", "BM", "OM")):
            ax_beta.text(center, y_top * 0.9, elem.FamName, rotation=90, fontsize=8, ha="center", va="top")

    ax_eta.plot(s[mask], dispersion[mask], color="#2a9d8f", lw=2.0)
    ax_eta.axhline(0.0, color="black", lw=0.8, alpha=0.5)
    ax_eta.set_ylabel("eta_x [m]")
    ax_eta.grid(True, alpha=0.25)

    for start, end, elem_type, name in element_bars(ring):
        if end < l4_start - margin or start > l4_end + margin:
            continue
        color, height = ELEMENT_STYLES[elem_type]
        ax_syn.add_patch(Rectangle((start, 0.0), end - start, height, facecolor=color, edgecolor="none"))
        if name in {"CAV", "BM1L4RP", "BM2L4RP", "OML4RP"}:
            ax_syn.text((start + end) / 2, height + 0.03, name, ha="center", va="bottom", fontsize=9)

    ax_syn.set_ylim(0, 0.9)
    ax_syn.set_yticks([])
    ax_syn.set_xlabel("s [m]")
    ax_syn.set_ylabel("synoptic")
    ax_syn.grid(True, axis="x", alpha=0.25)
    ax_syn.set_xlim(l4_start - margin, l4_end + margin)

    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def load_power_supply_map() -> tuple[dict[str, list[str]], dict[str, str]]:
    with POWER_SUPPLY_PATH.open() as handle:
        data = json.load(handle)

    element_to_supply: dict[str, str] = {}
    grouped = {}
    for family, mapping in data.items():
        grouped[family] = mapping
        for supply, elements in mapping.items():
            for element in elements:
                element_to_supply[element] = supply
    return grouped, element_to_supply


def load_inventory_lookup() -> set[str]:
    if not INVENTORY_PATH.exists():
        return set()
    with INVENTORY_PATH.open() as handle:
        inventory = json.load(handle)
    connected = set()
    for entry in inventory.get("legacy_pv_probe_results", []):
        result = entry.get("result", {})
        if result.get("returncode") == 0:
            connected.add(entry.get("pv", ""))
    return connected


def infer_pv_candidates(elem_name: str, elem_type: str, supply: str | None) -> list[str]:
    candidates: list[str] = []
    if supply:
        candidates.extend([f"{supply}:setCur", f"{supply}:rdCur"])
    if elem_type == "Monitor":
        candidates.extend([f"{elem_name}:rdX", f"{elem_name}:rdY"])
    elif elem_type == "RFCavity":
        candidates.extend(["MCLKHGP:setFrq"])
    elif elem_type == "Marker" and elem_name == "U125":
        candidates.extend(["U125"])
    else:
        candidates.extend([f"{elem_name}:set", f"{elem_name}:read"])
    return candidates


def describe_role(elem_name: str, elem_type: str) -> str:
    if elem_name == "CAV":
        return "Main RF cavity in the L4 long straight"
    if elem_name == "U125":
        return "Undulator marker in the L2 straight"
    if elem_type == "Dipole":
        return "Main bending dipole"
    if elem_type == "Quadrupole":
        return "Quadrupole focusing element"
    if elem_type == "Sextupole":
        return "Sextupole / chromatic correction family member"
    if elem_type == "Octupole":
        return "Octupole / nonlinear optics element"
    if elem_type == "Monitor":
        return "Beam position monitor"
    if elem_type == "Marker":
        return "Lattice marker"
    return elem_type


def lattice_records(ring: at.Lattice) -> list[dict[str, object]]:
    _, element_to_supply = load_power_supply_map()
    connected_pvs = load_inventory_lookup()
    positions = ring.get_s_pos(range(len(ring) + 1))
    records: list[dict[str, object]] = []
    for idx, elem in enumerate(ring):
        elem_type = type(elem).__name__
        supply = element_to_supply.get(elem.FamName)
        pv_candidates = infer_pv_candidates(elem.FamName, elem_type, supply)
        record = {
            "index": idx,
            "family_name": elem.FamName,
            "element_type": elem_type,
            "section": section_from_name(elem.FamName),
            "s_start_m": float(positions[idx]),
            "s_end_m": float(positions[idx + 1]),
            "s_center_m": float(0.5 * (positions[idx] + positions[idx + 1])),
            "length_m": float(positions[idx + 1] - positions[idx]),
            "power_supply": supply,
            "power_supply_set_pv": f"{supply}:setCur" if supply else None,
            "power_supply_rd_pv": f"{supply}:rdCur" if supply else None,
            "pv_candidates": pv_candidates,
            "connected_inventory_pvs": [pv for pv in pv_candidates if pv in connected_pvs],
            "role": describe_role(elem.FamName, elem_type),
        }
        if hasattr(elem, "K"):
            record["K"] = float(elem.K)
        if hasattr(elem, "H"):
            record["H"] = float(elem.H)
        if hasattr(elem, "PolynomB"):
            pb = np.array(elem.PolynomB, dtype=float).tolist()
            if any(abs(v) > 0 for v in pb):
                record["PolynomB"] = pb
        records.append(record)
    return records


def write_lattice_exports(ring: at.Lattice, config_name: str, output_dir: Path) -> tuple[Path, Path, Path]:
    records = lattice_records(ring)
    grouped_supplies, _ = load_power_supply_map()
    connected_pvs = sorted(load_inventory_lookup())

    json_path = output_dir / f"mls_lattice_{config_name}_export.json"
    csv_path = output_dir / f"mls_lattice_{config_name}_elements.csv"
    md_path = output_dir / f"mls_lattice_{config_name}_briefing.md"

    l4_records = [r for r in records if r["section"] == "L4"]
    l2_records = [r for r in records if r["section"] == "L2" or r["family_name"] == "U125"]
    special = {
        "rf_cavity": next((r for r in records if r["family_name"] == "CAV"), None),
        "u125_undulator": next((r for r in records if r["family_name"] == "U125"), None),
        "l4_section_bounds_m": {
            "start": min(r["s_start_m"] for r in l4_records),
            "end": max(r["s_end_m"] for r in l4_records),
        },
        "l2_u125_window_bounds_m": {
            "start": min(r["s_start_m"] for r in l2_records),
            "end": max(r["s_end_m"] for r in l2_records),
        },
    }

    export = {
        "config": config_name,
        "ring_name": ring.name,
        "energy_eV": float(ring.energy),
        "circumference_m": float(ring.get_s_pos(len(ring))[-1]),
        "elements": records,
        "special_locations": special,
        "power_supplies": grouped_supplies,
        "connected_inventory_pvs": connected_pvs,
    }

    with json_path.open("w") as handle:
        json.dump(export, handle, indent=2)

    fieldnames = [
        "index",
        "family_name",
        "element_type",
        "section",
        "s_start_m",
        "s_end_m",
        "s_center_m",
        "length_m",
        "power_supply",
        "power_supply_set_pv",
        "power_supply_rd_pv",
        "K",
        "H",
        "role",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key) for key in fieldnames})

    lines = [
        f"# MLS lattice briefing ({config_name})",
        "",
        "## Files",
        f"- Full ring optics: [`mls_lattice_{config_name}_full.png`](./mls_lattice_{config_name}_full.png)",
        f"- L4 zoom: [`mls_lattice_{config_name}_L4.png`](./mls_lattice_{config_name}_L4.png)",
        f"- L2 / U125 zoom: [`mls_lattice_{config_name}_L2_U125.png`](./mls_lattice_{config_name}_L2_U125.png)",
        f"- Machine-readable export: [`mls_lattice_{config_name}_export.json`](./mls_lattice_{config_name}_export.json)",
        f"- Flat element table: [`mls_lattice_{config_name}_elements.csv`](./mls_lattice_{config_name}_elements.csv)",
        "",
        "## Key locations",
        f"- RF cavity: `CAV` at s = {special['rf_cavity']['s_center_m']:.3f} m in L4",
        f"- U125 undulator marker: `U125` at s = {special['u125_undulator']['s_start_m']:.3f} m in L2",
        f"- L4 straight span: {special['l4_section_bounds_m']['start']:.3f} m to {special['l4_section_bounds_m']['end']:.3f} m",
        "",
        "## L4 element order",
    ]
    for record in l4_records:
        lines.append(
            f"- `{record['family_name']}` | {record['element_type']} | s = {record['s_center_m']:.3f} m | "
            f"supply = `{record['power_supply']}` | role = {record['role']}"
        )
    lines.extend(
        [
            "",
            "## U125 neighborhood",
        ]
    )
    for record in [r for r in l2_records if abs(r["s_center_m"] - special["u125_undulator"]["s_start_m"]) <= 6.0]:
        lines.append(
            f"- `{record['family_name']}` | {record['element_type']} | s = {record['s_center_m']:.3f} m | "
            f"supply = `{record['power_supply']}` | role = {record['role']}"
        )
    lines.extend(
        [
            "",
            "## EPICS naming hints",
            "- Magnet power-supply PVs are inferred from the repo's power-supply map, for example `S1P1RP:setCur` or `Q2P1L4RP:setCur`.",
            "- BPM-style readouts are inferred only heuristically here. The control-room inventory in this repo confirms a few connected PVs, especially `QPD00ZL4RP:rdSigmaX`, `QPD00ZL4RP:rdSigmaY`, and the sextupole supply channels.",
            "- `pv_candidates` and `connected_inventory_pvs` are included per element in the JSON export so another Codex instance can reason from them.",
        ]
    )
    with md_path.open("w") as handle:
        handle.write("\n".join(lines) + "\n")

    return json_path, csv_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="low_emittance", choices=["bare", "injection", "low_alpha", "low_emittance", "ssmb"])
    parser.add_argument("--output-dir", default=str(ROOT / "analysis_outputs"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ring = load_ring(args.config)
    plot_full_lattice(ring, args.config, output_dir / f"mls_lattice_{args.config}_full.png")
    plot_l4_zoom(ring, args.config, output_dir / f"mls_lattice_{args.config}_L4.png")
    plot_l2_undulator_zoom(ring, args.config, output_dir / f"mls_lattice_{args.config}_L2_U125.png")
    write_lattice_exports(ring, args.config, output_dir)


if __name__ == "__main__":
    main()
