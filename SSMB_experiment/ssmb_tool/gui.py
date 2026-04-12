from __future__ import annotations

import argparse
import queue
import threading
from pathlib import Path
from typing import Optional, Sequence

from .config import LoggerConfig, SSMB_ROOT, parse_labeled_pvs
from .epics_io import EpicsUnavailableError, ReadOnlyEpicsAdapter
from .log_now import build_specs, inventory_overview_lines, run_stage0_logger
from .sweep import RF_PV_NAME, SweepRuntimeConfig, build_plan_from_hz, preview_lines, run_rf_sweep_session

try:  # pragma: no cover - depends on host GUI packages
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on host GUI packages
    tk = None
    filedialog = None
    messagebox = None
    ttk = None


def _parse_text_mapping(text: str) -> dict[str, str]:
    items = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return parse_labeled_pvs(items)


class SSMBGui:
    def __init__(self, root: "tk.Tk", allow_writes: bool = False):
        self.root = root
        self.allow_writes = allow_writes
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self._build_vars()
        self._build_ui()
        self._refresh_inventory()
        self.root.after(100, self._drain_queue)

    def _build_vars(self) -> None:
        self.duration_var = tk.StringVar(value="60")
        self.sample_hz_var = tk.StringVar(value="1")
        self.timeout_var = tk.StringVar(value="0.5")
        self.label_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
        self.output_dir_var = tk.StringVar(value=str(SSMB_ROOT / ".ssmb_local" / "ssmb_stage0"))
        self.include_bpm_buffer_var = tk.BooleanVar(value=True)
        self.include_candidate_bpm_var = tk.BooleanVar(value=True)
        self.include_ring_bpm_var = tk.BooleanVar(value=True)
        self.include_quadrupole_var = tk.BooleanVar(value=False)
        self.include_sextupole_var = tk.BooleanVar(value=True)
        self.include_octupole_var = tk.BooleanVar(value=True)
        self.heavy_mode_var = tk.BooleanVar(value=False)

        self.center_rf_var = tk.StringVar(value="")
        self.delta_min_hz_var = tk.StringVar(value="-100")
        self.delta_max_hz_var = tk.StringVar(value="100")
        self.points_var = tk.StringVar(value="5")
        self.settle_var = tk.StringVar(value="1.0")
        self.samples_per_point_var = tk.StringVar(value="1")
        self.sample_spacing_var = tk.StringVar(value="0.0")

    def _build_ui(self) -> None:
        self.root.title("SSMB Experiment Stage 0 / RF Sweep")
        self.root.geometry("1380x900")

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        control = ttk.Frame(outer)
        control.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        notebook = ttk.Notebook(control)
        notebook.pack(fill="both", expand=False)

        logger_frame = ttk.Frame(notebook, padding=8)
        sweep_frame = ttk.Frame(notebook, padding=8)
        notebook.add(logger_frame, text="Stage 0 Logger")
        notebook.add(sweep_frame, text="RF Sweep")

        self._build_logger_tab(logger_frame)
        self._build_sweep_tab(sweep_frame)

        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Logged Channel Overview").grid(row=0, column=0, sticky="w")
        self.inventory_text = tk.Text(right, wrap="none", height=18)
        self.inventory_text.grid(row=1, column=0, sticky="nsew")
        self.inventory_text.configure(state="disabled")

        ttk.Label(right, text="Session / Run Log").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.log_text = tk.Text(right, wrap="word")
        self.log_text.grid(row=3, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    def _build_logger_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        for label, var in (
            ("Duration [s]", self.duration_var),
            ("Sample rate [Hz]", self.sample_hz_var),
            ("Timeout [s]", self.timeout_var),
            ("Session label", self.label_var),
            ("Operator note", self.note_var),
            ("Output root", self.output_dir_var),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=var, width=42).grid(row=row, column=1, sticky="ew", pady=2)
            row += 1

        preset_row = ttk.Frame(frame)
        preset_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(preset_row, text="Preset: low-alpha full log", command=self._preset_low_alpha).pack(side="left")
        ttk.Button(preset_row, text="Preset: bump OFF", command=lambda: self._preset_bump("bump_off")).pack(side="left", padx=4)
        ttk.Button(preset_row, text="Preset: bump ON", command=lambda: self._preset_bump("bump_on")).pack(side="left")
        row += 1

        ttk.Checkbutton(frame, text="Heavy logging mode", variable=self.heavy_mode_var, command=self._toggle_heavy_mode).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include BPM buffer waveform", variable=self.include_bpm_buffer_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include U125/L4 candidate BPM scalars", variable=self.include_candidate_bpm_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include ring BPM scalars", variable=self.include_ring_bpm_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include quadrupole currents", variable=self.include_quadrupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include sextupole currents", variable=self.include_sextupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="Include octupoles", variable=self.include_octupole_var, command=self._refresh_inventory).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Label(frame, text="Extra required PVs (LABEL=PV)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        self.extra_pvs_text = tk.Text(frame, width=48, height=6)
        self.extra_pvs_text.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        ttk.Label(frame, text="Optional experiment PVs (LABEL=PV)").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        self.optional_pvs_text = tk.Text(frame, width=48, height=6)
        self.optional_pvs_text.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(button_row, text="Preview Logged Channels", command=self._refresh_inventory).pack(side="left")
        ttk.Button(button_row, text="Run Stage 0 Log", command=self._run_stage0).pack(side="left", padx=6)

    def _build_sweep_tab(self, frame: "ttk.Frame") -> None:
        row = 0
        info = "Direct RF sweep in Hz around the current or entered RF PV value. Writes are disabled unless the GUI was started with --allow-writes."
        ttk.Label(frame, text=info, wraplength=360, justify="left").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1
        preset_row = ttk.Frame(frame)
        preset_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(preset_row, text="Preset: sweep bump OFF", command=lambda: self._preset_sweep("rf_sweep_bump_off")).pack(side="left")
        ttk.Button(preset_row, text="Preset: sweep bump ON", command=lambda: self._preset_sweep("rf_sweep_bump_on")).pack(side="left", padx=4)
        row += 1
        for label, var in (
            ("Center RF PV value", self.center_rf_var),
            ("Delta min [Hz]", self.delta_min_hz_var),
            ("Delta max [Hz]", self.delta_max_hz_var),
            ("Point count", self.points_var),
            ("Settle time [s]", self.settle_var),
            ("Samples per point", self.samples_per_point_var),
            ("Sample spacing [s]", self.sample_spacing_var),
        ):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=var, width=24).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

        sweep_buttons = ttk.Frame(frame)
        sweep_buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Button(sweep_buttons, text="Read Live RF", command=self._read_live_rf).pack(side="left")
        ttk.Button(sweep_buttons, text="Preview RF Sweep", command=self._preview_sweep).pack(side="left", padx=6)
        run_button = ttk.Button(sweep_buttons, text="Run RF Sweep", command=self._run_sweep)
        run_button.pack(side="left")
        if not self.allow_writes:
            run_button.state(["disabled"])

    def _collect_logger_config(self, allow_writes: bool = False) -> LoggerConfig:
        return LoggerConfig(
            duration_seconds=float(self.duration_var.get()),
            sample_hz=float(self.sample_hz_var.get()),
            timeout_seconds=float(self.timeout_var.get()),
            output_root=Path(self.output_dir_var.get()).expanduser().resolve(),
            safe_mode=not allow_writes,
            allow_writes=allow_writes,
            include_bpm_buffer=bool(self.include_bpm_buffer_var.get()),
            include_candidate_bpm_scalars=bool(self.include_candidate_bpm_var.get()),
            include_ring_bpm_scalars=bool(self.include_ring_bpm_var.get()),
            include_quadrupoles=bool(self.include_quadrupole_var.get()),
            include_sextupoles=bool(self.include_sextupole_var.get()),
            include_octupoles=bool(self.include_octupole_var.get()),
            session_label=self.label_var.get().strip(),
            operator_note=self.note_var.get().strip(),
            extra_pvs=_parse_text_mapping(self.extra_pvs_text.get("1.0", "end")),
            extra_optional_pvs=_parse_text_mapping(self.optional_pvs_text.get("1.0", "end")),
        )

    def _toggle_heavy_mode(self) -> None:
        heavy = bool(self.heavy_mode_var.get())
        if heavy:
            self.include_bpm_buffer_var.set(True)
            self.include_candidate_bpm_var.set(True)
            self.include_ring_bpm_var.set(True)
            self.include_quadrupole_var.set(True)
            self.include_sextupole_var.set(True)
            self.include_octupole_var.set(True)
            if float(self.sample_hz_var.get()) > 2.0:
                self.sample_hz_var.set("1")
        self._refresh_inventory()

    def _preset_low_alpha(self) -> None:
        self.label_var.set("low_alpha")
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.note_var.set("Low-alpha full passive logging")
        self._toggle_heavy_mode()

    def _preset_bump(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.duration_var.set("60")
        self.sample_hz_var.set("1")
        self.note_var.set("Set bump state externally before starting this passive log")
        self._toggle_heavy_mode()

    def _preset_sweep(self, label: str) -> None:
        self.label_var.set(label)
        self.heavy_mode_var.set(True)
        self.sample_hz_var.set("1")
        self.note_var.set("Rich SSMB RF sweep with external bump state fixed before run; online delta_s / eta / alpha0 summaries enabled")
        self.delta_min_hz_var.set("-20")
        self.delta_max_hz_var.set("20")
        self.points_var.set("11")
        self.settle_var.set("1.2")
        self.samples_per_point_var.set("5")
        self.sample_spacing_var.set("0.25")
        self._toggle_heavy_mode()
        self.include_bpm_buffer_var.set(False)
        self._refresh_inventory()

    def _append_log(self, message: str) -> None:
        at_bottom = self.log_text.yview()[1] >= 0.999
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.configure(state="disabled")
        if at_bottom:
            self.log_text.see("end")

    def _set_inventory_text(self, lines: list[str]) -> None:
        self.inventory_text.configure(state="normal")
        self.inventory_text.delete("1.0", "end")
        self.inventory_text.insert("1.0", "\n".join(lines))
        self.inventory_text.configure(state="disabled")

    def _drain_queue(self) -> None:
        while True:
            try:
                message = self.queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)
        self.root.after(100, self._drain_queue)

    def _emit(self, message: str) -> None:
        self.queue.put(message)

    def _run_in_worker(self, target, *args) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._emit("Another SSMB task is still running.")
            return

        def runner() -> None:
            try:
                target(*args)
            except Exception as exc:
                self._emit("Task failed: %s" % exc)

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def _refresh_inventory(self) -> None:
        try:
            _, specs = build_specs(self._collect_logger_config(allow_writes=False))
        except Exception as exc:
            self._set_inventory_text(["Could not build inventory: %s" % exc])
            return
        self._set_inventory_text(inventory_overview_lines(specs))

    def _run_stage0(self) -> None:
        config = self._collect_logger_config(allow_writes=False)
        self._run_in_worker(self._run_stage0_worker, config)

    def _run_stage0_worker(self, config: LoggerConfig) -> None:
        session_dir = run_stage0_logger(config, progress_callback=self._emit)
        self._emit("Stage 0 log saved to: %s" % session_dir)

    def _read_live_rf(self) -> None:
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
        except Exception as exc:
            self._append_log("Live RF read failed: %s" % exc)
            return
        if value is None:
            self._append_log("Live RF read failed for %s." % RF_PV_NAME)
            return
        text = "%.6f" % float(value)
        self.center_rf_var.set(text)
        self._append_log("Read live RF %s = %s" % (RF_PV_NAME, text))

    def _build_sweep_runtime(self) -> SweepRuntimeConfig:
        config = self._collect_logger_config(allow_writes=True)
        plan = build_plan_from_hz(
            center_rf_pv=float(self.center_rf_var.get()),
            delta_min_hz=float(self.delta_min_hz_var.get()),
            delta_max_hz=float(self.delta_max_hz_var.get()),
            n_points=int(self.points_var.get()),
            settle_seconds=float(self.settle_var.get()),
            samples_per_point=int(self.samples_per_point_var.get()),
            sample_spacing_seconds=float(self.sample_spacing_var.get()),
        )
        return SweepRuntimeConfig(logger_config=config, plan=plan, write_enabled=True)

    def _preview_sweep(self) -> None:
        try:
            runtime = self._build_sweep_runtime()
        except Exception as exc:
            self._append_log("RF sweep preview failed: %s" % exc)
            return
        current_rf = None
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
            current_rf = float(value) if value is not None else None
        except Exception:
            current_rf = None
        lines = preview_lines(runtime.plan, current_rf)
        self._set_inventory_text(lines)
        self._append_log("RF sweep preview updated.")

    def _run_sweep(self) -> None:
        if not self.allow_writes:
            self._append_log("RF sweep writes are disabled. Start the GUI with --allow-writes.")
            return
        runtime = self._build_sweep_runtime()
        current_rf = None
        try:
            adapter = ReadOnlyEpicsAdapter(timeout=float(self.timeout_var.get()))
            value = adapter.get(RF_PV_NAME, None)
            current_rf = float(value) if value is not None else None
        except Exception:
            current_rf = None
        lines = preview_lines(runtime.plan, current_rf)
        preview_text = "\n".join(lines)
        if not messagebox.askokcancel("Confirm RF Sweep", preview_text):
            self._append_log("RF sweep cancelled by user.")
            return
        self._run_in_worker(self._run_sweep_worker, runtime)

    def _run_sweep_worker(self, runtime: SweepRuntimeConfig) -> None:
        session_dir = run_rf_sweep_session(runtime, progress_callback=self._emit)
        self._emit("RF sweep log saved to: %s" % session_dir)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GUI for SSMB Stage 0 logging and conservative RF sweeps.")
    parser.add_argument("--allow-writes", action="store_true", help="Enable the RF sweep execution button. Stage 0 logging remains read-only.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if tk is None:
        raise SystemExit("tkinter is unavailable; cannot start the SSMB GUI.")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    root = tk.Tk()
    SSMBGui(root, allow_writes=args.allow_writes)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
