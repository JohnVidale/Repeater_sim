#!/usr/bin/env python3
"""Run P38 array alignment with an optional relative location offset.

Both cases use explicit analysis reference times and coordinates from
``ICevents_working.xlsx:aligned_pairs``.  The staged legacy code receives zero
additional pair/common shifts, preventing an implicit double application.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import matplotlib.pyplot as plt
import numpy as np
from obspy.geodetics import gps2dist_azimuth
from obspy.taup import TauPyModel

import run_isolated_array_comparison_baseline as baseline
from array_comparison.p38_inputs import case_events, read_inputs


PAIR = "P38"
EVENT1 = 732
EVENT2 = 750
PHASES = ("PKiKP", "PKIKP")


def inject_case_overrides(stage_dir: Path, inputs: dict[str, object], differential: bool) -> None:
    events = case_events(inputs, differential)
    pair_injection = f'''
    if str(repeater) == {PAIR!r}:
        lines0 = lines0.copy()
        lines0.loc[:, "tshift"] = 0.0
        lines0.loc[:, "shift_all"] = 0.0
        lines0.loc[:, "Y_shift"] = 0.0
        lines0.loc[:, "shift_bothY"] = 0.0
        lines0.loc[:, "A_shift"] = 0.0
'''
    event_pair_injection = f'''
    if int(eq_num1) == {EVENT1} and int(eq_num2) == {EVENT2}:
        lines1 = lines1.copy()
        lines2 = lines2.copy()
        lines1.loc[:, "TIME"] = {events[EVENT1]["time"]!r}
        lines1.loc[:, "LAT"] = {events[EVENT1]["lat"]!r}
        lines1.loc[:, "LON"] = {events[EVENT1]["lon"]!r}
        lines1.loc[:, "DEP"] = {events[EVENT1]["depth"]!r}
        lines2.loc[:, "TIME"] = {events[EVENT2]["time"]!r}
        lines2.loc[:, "LAT"] = {events[EVENT2]["lat"]!r}
        lines2.loc[:, "LON"] = {events[EVENT2]["lon"]!r}
        lines2.loc[:, "DEP"] = {events[EVENT2]["depth"]!r}
'''
    event_single_injection = f'''
    if int(eq_num) in ({EVENT1}, {EVENT2}):
        lines = lines.copy()
        _case = {{
            {EVENT1}: {events[EVENT1]!r},
            {EVENT2}: {events[EVENT2]!r},
        }}[int(eq_num)]
        lines.loc[:, "TIME"] = _case["time"]
        lines.loc[:, "LAT"] = _case["lat"]
        lines.loc[:, "LON"] = _case["lon"]
        lines.loc[:, "DEP"] = _case["depth"]
'''

    path = stage_dir / "pro3_sort_plot_pair.py"
    text = path.read_text()
    marker = "    lines0      = search_df(df,'label'      ,repeater,partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro3 pair-row injection marker not found")
    text = text.replace(marker, marker + pair_injection, 1)
    marker = "    lines2 = search_df(df,'INDEX',str(eq_num2),partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro3 event-row injection marker not found")
    path.write_text(text.replace(marker, marker + event_pair_injection, 1))

    path = stage_dir / "pro5_stack2d.py"
    text = path.read_text()
    marker = "    lines = search_df(df,'INDEX',str(eq_num),partial_match=True)\n"
    if marker not in text:
        raise RuntimeError("pro5 event-row injection marker not found")
    path.write_text(text.replace(marker, marker + event_single_injection, 1))

    for filename in ("pro6_pair_cc.py", "pro7_pair_scan.py"):
        path = stage_dir / filename
        text = path.read_text()
        marker = "    lines2 = search_df(df,'INDEX',str(eq_num2),partial_match=True)\n"
        if marker not in text:
            raise RuntimeError(f"{filename} event-row injection marker not found")
        path.write_text(text.replace(marker, marker + event_pair_injection, 1))


def run_mode(
    output_root: Path,
    case_name: str,
    differential: bool,
    mode_name: str,
    inputs: dict[str, object],
) -> int:
    mode = baseline.MODES[mode_name]
    mode_root = output_root / "cases" / case_name / mode_name
    intermediate = mode_root / "intermediate"
    figures = mode_root / "figures"
    logs = mode_root / "logs"
    stage_dir = mode_root / "staged_code"
    for directory in (intermediate, figures, logs):
        directory.mkdir(parents=True)
    sources = baseline.stage_code(stage_dir, intermediate, figures)
    inject_case_overrides(stage_dir, inputs, differential)
    driver = stage_dir / "run_mode.py"
    driver.write_text(baseline.driver_text(PAIR, mode))
    settings = {
        **mode,
        "pair": PAIR,
        "case": case_name,
        "differential_location_applied": differential,
        "workbook_values": inputs,
        "event_values_used": case_events(inputs, differential),
        "legacy_shift_overrides": {
            "tshift": 0.0,
            "shift_all": 0.0,
            "Y_shift": 0.0,
            "shift_bothY": 0.0,
            "A_shift": 0.0,
        },
        "sources": sources,
    }
    (mode_root / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    command = ["conda", "run", "-n", "vidale_main", "python", str(driver)]
    environment = os.environ.copy()
    environment["MPLBACKEND"] = "Agg"
    environment["MPLCONFIGDIR"] = str(mode_root / "matplotlib_config")
    completed = subprocess.run(
        command,
        cwd=stage_dir,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    (logs / "run.log").write_text(completed.stdout)
    (logs / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    (logs / "exit_code.txt").write_text(f"{completed.returncode}\n")
    if completed.returncode == 0:
        common = baseline.selected_station_codes(intermediate)
        (mode_root / "common_elements.json").write_text(json.dumps(common, indent=2) + "\n")
    return completed.returncode


def read_station_file(path: Path) -> list[tuple[str, float, float]]:
    stations = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3:
            stations.append((fields[0], float(fields[1]), float(fields[2])))
    return stations


def first_arrival_time(
    model: TauPyModel, depth: float, distance: float, phase: str
) -> float | None:
    arrivals = model.get_travel_times(
        source_depth_in_km=depth,
        distance_in_degree=distance,
        phase_list=[phase],
    )
    return float(arrivals[0].time) if arrivals else None


def predicted_location_effects(output_root: Path, inputs: dict[str, object]) -> list[dict[str, object]]:
    model = TauPyModel(model="ak135")
    centroid = case_events(inputs, False)
    differential = case_events(inputs, True)
    arrays = {
        "YKA": baseline.ARRAY_CODES_ROOT / "Files" / "Stations" / "sta_CN_YK.txt",
        "ILAR": baseline.ARRAY_CODES_ROOT / "Files" / "Stations" / "sta_ILAR.txt",
    }
    rows: list[dict[str, object]] = []
    for array_name, station_path in arrays.items():
        for station, station_lat, station_lon in read_station_file(station_path):
            for phase in PHASES:
                values = {}
                for case_name, events in (("centroid", centroid), ("differential", differential)):
                    travel_times = []
                    for event_id in (EVENT1, EVENT2):
                        event = events[event_id]
                        distance = gps2dist_azimuth(
                            event["lat"], event["lon"], station_lat, station_lon
                        )[0] / (1000.0 * 111.0)
                        travel_times.append(
                            first_arrival_time(model, event["depth"], distance, phase)
                        )
                    values[case_name] = travel_times
                if any(v is None for pair in values.values() for v in pair):
                    continue
                centroid_relative = values["centroid"][1] - values["centroid"][0]
                differential_relative = values["differential"][1] - values["differential"][0]
                rows.append(
                    {
                        "array": array_name,
                        "station": station,
                        "phase": phase,
                        "centroid_event2_minus_event1_travel_time_s": centroid_relative,
                        "differential_event2_minus_event1_travel_time_s": differential_relative,
                        "location_correction_s": differential_relative - centroid_relative,
                    }
                )
    comparison = output_root / "comparison"
    comparison.mkdir()
    csv_path = comparison / "predicted_differential_location_timing_effects.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for axis, array_name in zip(axes, ("YKA", "ILAR")):
        array_rows = [row for row in rows if row["array"] == array_name]
        stations = sorted({str(row["station"]) for row in array_rows})
        x = np.arange(len(stations))
        for phase, marker in zip(PHASES, ("o", "s")):
            lookup = {
                str(row["station"]): 1000.0 * float(row["location_correction_s"])
                for row in array_rows
                if row["phase"] == phase
            }
            axis.plot(x, [lookup.get(station, np.nan) for station in stations], marker=marker, label=phase)
        axis.axhline(0.0, color="0.4", linewidth=0.8)
        axis.set_title(array_name)
        axis.set_xticks(x)
        axis.set_xticklabels(stations, rotation=90, fontsize=7)
        axis.set_xlabel("Station")
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Differential-location timing correction (ms)")
    axes[1].legend()
    fig.suptitle(
        "P38 predicted event-2 minus event-1 travel-time change\n"
        "differential locations minus shared centroid (ak135)"
    )
    fig.tight_layout()
    fig.savefig(comparison / "predicted_differential_location_timing_effects.png", dpi=180)
    plt.close(fig)
    return rows


def make_panel(output_root: Path, mode_name: str) -> None:
    cases = ("new_centroid_time_shift", "new_differential_location_time_shift")
    suffixes = ("traces.png", "envelope.png", "Abeam.png")
    fig, axes = plt.subplots(3, 2, figsize=(14, 13))
    for column, case_name in enumerate(cases):
        figures = output_root / "cases" / case_name / mode_name / "figures"
        for row, suffix in enumerate(suffixes):
            matches = sorted(figures.glob(f"*_{suffix}"))
            if len(matches) != 1:
                raise RuntimeError(f"Expected one {suffix} in {figures}, found {len(matches)}")
            image = plt.imread(matches[0])
            axes[row, column].imshow(image)
            axes[row, column].axis("off")
            if row == 0:
                axes[row, column].set_title(case_name.replace("_", " "), fontsize=12)
    fig.suptitle(f"P38 {mode_name}: shared centroid versus differential locations", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_root / "comparison" / f"{mode_name}_centroid_vs_differential.png", dpi=160)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=sorted(baseline.MODES),
        default=list(baseline.MODES),
        help="Array/window modes to run; default: all P38 YKA and ILAR modes.",
    )
    parser.add_argument(
        "--include-relative-offset",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Apply the preferred P38 event-2-minus-event-1 relative location "
            "from aligned_pairs; default: use the shared workbook centroid for both events."
        ),
    )
    args = parser.parse_args()
    baseline.require_inputs(require_relative_location_products=False)
    inputs = read_inputs()
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_root = (
        args.output_root
        or Path(__file__).resolve().parent / "outputs" / f"array_location_test_{timestamp}"
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    provenance = {
        "created": datetime.now().astimezone().isoformat(),
        "objective": "run P38 YKA/ILAR stacks with new workbook timing and an optional relative location offset",
        "include_relative_offset": args.include_relative_offset,
        "inputs": inputs,
        "source_hashes": {
            str(path): baseline.sha256(path)
            for path in (
                baseline.CURRENT_WORKBOOK,
                baseline.LEGACY_WORKBOOK,
                *baseline.P38_DATA_INPUTS,
            )
        },
        "git": baseline.git_snapshot(baseline.ARRAY_CODES_ROOT / "Repeater_sim"),
    }
    (output_root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")

    case_name = (
        "with_relative_offset" if args.include_relative_offset else "without_relative_offset"
    )
    failures = []
    for mode_name in args.modes:
        if run_mode(output_root, case_name, args.include_relative_offset, mode_name, inputs):
            failures.append(f"{case_name}/{mode_name}")

    if not failures:
        rows = predicted_location_effects(output_root, inputs)
        corrections_ms = np.asarray(
            [1000.0 * float(row["location_correction_s"]) for row in rows]
        )
        summary = {
            "output_root": str(output_root),
            "failed_runs": [],
            "completed_runs": len(args.modes),
            "include_relative_offset": args.include_relative_offset,
            "case": case_name,
            "location_correction_ms_min": float(corrections_ms.min()),
            "location_correction_ms_median": float(np.median(corrections_ms)),
            "location_correction_ms_max": float(corrections_ms.max()),
        }
    else:
        summary = {"output_root": str(output_root), "failed_runs": failures}
    (output_root / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
