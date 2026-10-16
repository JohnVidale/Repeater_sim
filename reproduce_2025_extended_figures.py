#!/usr/bin/env python3
"""Recreate 2025 Nature Geoscience Extended Data Figs. 3-4.

The array traces are aligned internally with TauP-predicted PKiKP moveout, but
the two earthquakes in a pair are *not* aligned to one another by their core
arrivals. Their relative timing and common source coordinates come directly
from ``ICevents_working.xlsx:aligned_pairs``; depth comes from ``pairs``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from obspy import read
from obspy.geodetics import gps2dist_azimuth
from obspy.taup import TauPyModel

import run_isolated_array_comparison_baseline as baseline


FIGURE_PAIRS = {
    "3": ("P31", "P33", "P34", "P36", "P37", "P38", "P39", "P63", "P355"),
    "4": ("P51", "P79", "P109", "P112", "P123", "P140", "P145", "P321"),
}
MODE = baseline.MODES["yka_40s"]
WORKBOOK = baseline.CURRENT_WORKBOOK
YKA_REFERENCE = (62.49, -114.60)
BEAM_INDEX = 4 * 11 + 5
PLOT_WINDOW = (-10.0, 10.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pair_inputs(
    labels: set[str], waveform_overrides: dict[int, Path]
) -> dict[str, dict[str, object]]:
    """Read the declared timing/location fields for each requested pair."""
    aligned = pd.read_excel(WORKBOOK, sheet_name="aligned_pairs")
    pairs = pd.read_excel(WORKBOOK, sheet_name="pairs")
    legacy_events = pd.read_excel(baseline.LEGACY_WORKBOOK, sheet_name="events")
    output: dict[str, dict[str, object]] = {}
    for label in sorted(labels):
        aligned_rows = aligned[aligned["label"].astype(str).eq(label)]
        pair_rows = pairs[pairs["label"].astype(str).eq(label)]
        if len(aligned_rows) != 1 or len(pair_rows) != 1:
            raise ValueError(
                f"Expected one aligned_pairs and one pairs row for {label}; "
                f"found {len(aligned_rows)} and {len(pair_rows)}"
            )
        row = aligned_rows.iloc[0]
        pair = pair_rows.iloc[0]
        required = (
            "event1",
            "event2",
            "same_location_event1_reference_time",
            "same_location_event1_lat",
            "same_location_event1_lon",
            "same_location_event2_reference_time",
            "same_location_event2_lat",
            "same_location_event2_lon",
        )
        missing = [name for name in required if pd.isna(row[name])]
        if missing or not bool(row["same_location_available"]):
            raise ValueError(f"{label} lacks authoritative same-location fields: {missing}")
        event1, event2 = int(row["event1"]), int(row["event2"])
        if event1 != int(pair["index1"]) or event2 != int(pair["index2"]):
            raise ValueError(f"{label} event IDs disagree between workbook sheets")
        waveform_paths = {}
        for event in (event1, event2):
            legacy_rows = legacy_events[legacy_events["INDEX"].astype(int).eq(event)]
            if len(legacy_rows) != 1:
                raise ValueError(f"Expected one legacy event row for {event}")
            legacy_time = pd.Timestamp(legacy_rows.iloc[0]["TIME"])
            default_path = (
                baseline.RESEARCH_IC_ROOT
                / "Mseed"
                / "YKA"
                / f"{legacy_time:%Y%m%d_%H%M}.mseed"
            )
            waveform_paths[event] = waveform_overrides.get(event, default_path).resolve()
            if not waveform_paths[event].is_file():
                raise FileNotFoundError(
                    f"Missing YKA waveform for event {event}: {waveform_paths[event]}"
                )
        output[label] = {
            "pair": label,
            "event1": event1,
            "event2": event2,
            "depth_km": float(pair["depth"]),
            "event1_values": {
                "time": str(row["same_location_event1_reference_time"]),
                "lat": float(row["same_location_event1_lat"]),
                "lon": float(row["same_location_event1_lon"]),
            },
            "event2_values": {
                "time": str(row["same_location_event2_reference_time"]),
                "lat": float(row["same_location_event2_lat"]),
                "lon": float(row["same_location_event2_lon"]),
            },
            "event1_waveform": str(waveform_paths[event1]),
            "event2_waveform": str(waveform_paths[event2]),
            "pick_align_shift_s": float(row["pick_align_shift_s"]),
            "same_location_event2_minus_event1_shift_s": float(
                row["same_location_event2_minus_event1_shift_s"]
            ),
        }
    return output


def inject_pair_overrides(stage: Path, inputs: dict[str, object]) -> None:
    """Put workbook values into staged legacy code and disable pair CC plots."""
    label = str(inputs["pair"])
    event1, event2 = int(inputs["event1"]), int(inputs["event2"])
    depth = float(inputs["depth_km"])
    events = {
        event1: {**inputs["event1_values"], "depth": depth},
        event2: {**inputs["event2_values"], "depth": depth},
    }

    run_path = stage / "run_compare_pair.py"
    text = run_path.read_text()
    marker = "    lines0 = search_df(df,'label',repeater,partial_match=True)\n"
    injection = f'''    if str(repeater) == {label!r}:
        lines0 = df.loc[df["label"].astype(str).eq({label!r})]
'''
    if marker not in text:
        raise RuntimeError("run_compare_pair pair marker not found")
    text = text.replace(marker, marker + injection, 1)
    marker = "    do_6  = True\n    do_7  = True\n"
    if marker not in text:
        raise RuntimeError("run_compare_pair workflow marker not found")
    run_path.write_text(text.replace(marker, "    do_6  = False\n    do_7  = False\n", 1))

    pair_injection = f'''    if str(repeater) == {label!r}:
        lines0 = df.loc[df["label"].astype(str).eq({label!r})].copy()
        lines0.loc[:, "tshift"] = 0.0
        lines0.loc[:, "shift_all"] = 0.0
        lines0.loc[:, "Y_shift"] = 0.0
        lines0.loc[:, "shift_bothY"] = 0.0
        lines0.loc[:, "A_shift"] = 0.0
'''
    event_pair_injection = f'''    if int(eq_num1) == {event1} and int(eq_num2) == {event2}:
        lines1 = lines1.copy()
        lines2 = lines2.copy()
        lines1.loc[:, "TIME"] = {events[event1]["time"]!r}
        lines1.loc[:, "LAT"] = {events[event1]["lat"]!r}
        lines1.loc[:, "LON"] = {events[event1]["lon"]!r}
        lines1.loc[:, "DEP"] = {events[event1]["depth"]!r}
        lines2.loc[:, "TIME"] = {events[event2]["time"]!r}
        lines2.loc[:, "LAT"] = {events[event2]["lat"]!r}
        lines2.loc[:, "LON"] = {events[event2]["lon"]!r}
        lines2.loc[:, "DEP"] = {events[event2]["depth"]!r}
'''
    event_single_injection = f'''    if int(eq_num) in ({event1}, {event2}):
        lines = lines.copy()
        _case = {{
            {event1}: {events[event1]!r},
            {event2}: {events[event2]!r},
        }}[int(eq_num)]
        lines.loc[:, "TIME"] = _case["time"]
        lines.loc[:, "LAT"] = _case["lat"]
        lines.loc[:, "LON"] = _case["lon"]
        lines.loc[:, "DEP"] = _case["depth"]
'''

    path = stage / "pro3_sort_plot_pair.py"
    text = path.read_text()
    marker = "    lines0      = search_df(df,'label'      ,repeater,partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro3 pair-row injection marker not found")
    text = text.replace(marker, marker + pair_injection, 1)
    marker = "    lines2 = search_df(df,'INDEX',str(eq_num2),partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro3 event-row injection marker not found")
    text = text.replace(marker, marker + event_pair_injection, 1)
    marker = "        fname2 = f\"{base_path}{subdirectory}{mseed_name2}.mseed\"\n"
    waveform_injection = f'''    if ARRAY == 5 and int(eq_num1) == {event1} and int(eq_num2) == {event2}:
        fname1 = {str(inputs["event1_waveform"])!r}
        fname2 = {str(inputs["event2_waveform"])!r}
'''
    if marker not in text:
        raise RuntimeError("pro3 waveform-path injection marker not found")
    path.write_text(text.replace(marker, marker + waveform_injection, 1))

    path = stage / "pro5_stack2d.py"
    text = path.read_text()
    marker = "    lines = search_df(df,'INDEX',str(eq_num),partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro5 event-row injection marker not found")
    path.write_text(text.replace(marker, marker + event_single_injection, 1))


def predicted_reference_time(inputs: dict[str, object], model: TauPyModel) -> float:
    event = inputs["event1_values"]
    distance_m = gps2dist_azimuth(
        YKA_REFERENCE[0], YKA_REFERENCE[1], float(event["lat"]), float(event["lon"])
    )[0]
    distance_deg = distance_m / (1000.0 * 111.0)
    arrivals = model.get_travel_times(
        source_depth_in_km=float(inputs["depth_km"]),
        distance_in_degree=distance_deg,
        phase_list=["PKiKP"],
    )
    if not arrivals:
        raise RuntimeError(f"No ak135 PKiKP prediction for {inputs['pair']}")
    return float(arrivals[0].time)


def run_pair(pair: str, root: Path, inputs: dict[str, object]) -> Path:
    run_root = root / pair
    intermediate = run_root / "intermediate"
    figures = run_root / "legacy_figures"
    stage = run_root / "staged_code"
    logs = run_root / "logs"
    for directory in (intermediate, figures, logs):
        directory.mkdir(parents=True)
    sources = baseline.stage_code(stage, intermediate, figures)
    inject_pair_overrides(stage, inputs)
    for filename, record in sources.items():
        record["executed_staged_sha256"] = sha256(stage / filename)
    driver = stage / "run_mode.py"
    driver.write_text(baseline.driver_text(pair, MODE))
    command = ["conda", "run", "-n", "vidale_main", "python", str(driver.resolve())]
    environment = os.environ.copy()
    environment["MPLBACKEND"] = "Agg"
    environment["MPLCONFIGDIR"] = str(run_root / "matplotlib_config")
    print(f"Starting {pair}", flush=True)
    completed = subprocess.run(
        command,
        cwd=stage,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (logs / "run.log").write_text(completed.stdout)
    provenance = {
        "pair": pair,
        "command": command,
        "sources": sources,
        "returncode": completed.returncode,
        "workbook": str(WORKBOOK),
        "workbook_sha256": sha256(WORKBOOK),
        "workbook_values": inputs,
        "waveform_sha256": {
            "event1": sha256(Path(str(inputs["event1_waveform"]))),
            "event2": sha256(Path(str(inputs["event2_waveform"]))),
        },
        "processing": {
            "array": "YKA",
            "bandpass_hz": [1.0, 2.0],
            "interpolation_sps": 100,
            "fractional_sample_stacking": True,
            "within_array_alignment": "ak135 PKiKP moveout",
            "inter_event_core_arrival_alignment": False,
            "legacy_pair_shift_fields_applied": False,
        },
    }
    if completed.returncode:
        (run_root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        raise RuntimeError(f"{pair} failed; see {logs / 'run.log'}")
    provenance["common_elements"] = baseline.selected_station_codes(intermediate)
    (run_root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Finished {pair}", flush=True)
    return run_root


def stack_pair(
    run_root: Path, travel_time_s: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    files = sorted(run_root.glob("intermediate/HD*_2dstack.mseed"))
    if len(files) != 2:
        raise RuntimeError(f"Expected two stacks in {run_root}, found {len(files)}")
    traces = [read(path)[BEAM_INDEX] for path in files]
    traces.sort(key=lambda trace: trace.stats.starttime)
    size = min(len(trace.data) for trace in traces)
    data = [np.asarray(trace.data[:size], float) for trace in traces]
    relative_time = np.arange(size) * traces[0].stats.delta - 50.0
    mask = (relative_time >= PLOT_WINDOW[0]) & (relative_time <= PLOT_WINDOW[1])
    normalized = []
    for item in data:
        rms = float(np.sqrt(np.mean(item[mask] * item[mask])))
        if not np.isfinite(rms) or rms == 0:
            raise RuntimeError(f"Invalid RMS for {run_root.name}")
        normalized.append(item / rms)
    absolute_travel_time = relative_time + travel_time_s
    return absolute_travel_time, normalized[0], normalized[1], run_root.name


def shared_amplitude_limit(first: np.ndarray, second: np.ndarray) -> float:
    """Return one symmetric limit for an overlap and its unscaled difference."""
    limit = float(max(np.max(np.abs(first)), np.max(np.abs(second))))
    if not np.isfinite(limit) or limit == 0:
        raise RuntimeError("Invalid plotted amplitude scale")
    return 1.05 * limit


def make_figure(
    root: Path,
    figure: str,
    inputs_by_pair: dict[str, dict[str, object]],
    model: TauPyModel,
    output_directory: Path | None = None,
) -> Path:
    pairs = FIGURE_PAIRS[figure]
    columns = 2
    rows = int(np.ceil(len(pairs) / columns))
    fig, axes = plt.subplots(rows, columns * 2, figsize=(13.5, 2.15 * rows))
    axes = np.atleast_2d(axes)
    for index, pair in enumerate(pairs):
        predicted_time = predicted_reference_time(inputs_by_pair[pair], model)
        time, first, second, label = stack_pair(root / pair, predicted_time)
        mask = (
            (time >= predicted_time + PLOT_WINDOW[0])
            & (time <= predicted_time + PLOT_WINDOW[1])
        )
        row, column = divmod(index, columns)
        left, right = axes[row, 2 * column], axes[row, 2 * column + 1]
        first_window = first[mask]
        second_window = second[mask]
        difference = second_window - first_window
        amplitude_limit = shared_amplitude_limit(first_window, second_window)
        left.plot(time[mask], first_window, color="tab:blue", lw=0.8, label="earlier event")
        left.plot(time[mask], second_window, color="tab:red", lw=0.8, label="later event")
        right.plot(time[mask], difference, color="black", lw=0.8)
        ticks = predicted_time + np.array([-8.0, 0.0, 8.0])
        for axis in (left, right):
            axis.axhline(0, color="0.75", lw=0.5)
            axis.set_xlim(predicted_time + PLOT_WINDOW[0], predicted_time + PLOT_WINDOW[1])
            axis.set_ylim(-amplitude_limit, amplitude_limit)
            axis.set_xticks(ticks)
            axis.tick_params(labelsize=7, length=2)
            axis.set_yticks([])
        left.text(0.03, 0.83, label, transform=left.transAxes, color="navy", fontsize=9)
        right.text(0.03, 0.83, "later - earlier", transform=right.transAxes, fontsize=7)
        if row == rows - 1 or index >= len(pairs) - columns:
            left.set_xlabel("time after authoritative origin (s)", fontsize=7)
            right.set_xlabel("time after authoritative origin (s)", fontsize=7)
    for index in range(len(pairs), rows * columns):
        axes[index // columns, 2 * (index % columns)].axis("off")
        axes[index // columns, 2 * (index % columns) + 1].axis("off")
    axes[0, 0].legend(loc="lower left", fontsize=7, frameon=False, ncol=2)
    fig.suptitle(
        f"2025 Extended Data Figure {figure}, updated YKA processing\n"
        "absolute global-reference timing; ak135 array moveout; no inter-event core-arrival shift; "
        "100 sps fractional stacking; per-event window RMS normalization; shared residual scale",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    output_directory = output_directory or root
    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / f"reproduced_extended_data_figure_{figure}.png"
    fig.savefig(output, dpi=240, bbox_inches="tight")
    fig.savefig(
        output_directory / f"reproduced_extended_data_figure_{figure}.pdf",
        bbox_inches="tight",
    )
    plt.close(fig)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--figures", nargs="+", choices=("3", "4"), default=("3", "4")
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--waveform-override",
        action="append",
        default=[],
        metavar="EVENT=PATH",
        help="Use PATH as the YKA miniSEED input for EVENT; may be repeated.",
    )
    args = parser.parse_args()
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    root = (args.output_root or Path("outputs") / f"extended_figures_current_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    waveform_overrides: dict[int, Path] = {}
    if args.waveform_override:
        input_waveforms = root / "input_waveforms"
        input_waveforms.mkdir()
        for value in args.waveform_override:
            event_text, separator, path_text = value.partition("=")
            if not separator:
                parser.error(f"Invalid --waveform-override {value!r}; expected EVENT=PATH")
            source = Path(path_text).expanduser().resolve()
            if not source.is_file():
                parser.error(f"Waveform override does not exist: {source}")
            event = int(event_text)
            destination = input_waveforms / f"event_{event}_{source.name}"
            shutil.copy2(source, destination)
            waveform_overrides[event] = destination
    requested_pairs = {pair for figure in args.figures for pair in FIGURE_PAIRS[figure]}
    inputs_by_pair = read_pair_inputs(requested_pairs, waveform_overrides)
    (root / "pair_inputs.json").write_text(
        json.dumps(
            {
                "workbook": str(WORKBOOK),
                "workbook_sha256": sha256(WORKBOOK),
                "sheet": "aligned_pairs",
                "pairs": inputs_by_pair,
            },
            indent=2,
        )
        + "\n"
    )
    model = TauPyModel(model="ak135")
    completed: set[str] = set()
    for figure in args.figures:
        for pair in FIGURE_PAIRS[figure]:
            if pair not in completed:
                run_pair(pair, root, inputs_by_pair[pair])
                completed.add(pair)
        print(make_figure(root, figure, inputs_by_pair, model), flush=True)
    (root / "run_summary.json").write_text(
        json.dumps(
            {
                "figures": list(args.figures),
                "pairs": sorted(completed),
                "output_root": str(root.resolve()),
                "completed_at": datetime.now().astimezone().isoformat(),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
