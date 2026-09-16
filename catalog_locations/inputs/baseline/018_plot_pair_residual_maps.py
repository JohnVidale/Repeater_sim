#!/usr/bin/env python3
"""Make one station/residual map for each repeating-earthquake pair."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plot_station_map_highlights import DEFAULT_HIGHLIGHTS, great_circle_path


def read_summaries(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as handle:
        return {row["pair_label"]: row for row in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_measurements", type=Path)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--output-directory", type=Path, default=None)
    parser.add_argument("--highlight", nargs="*", default=DEFAULT_HIGHLIGHTS)
    args = parser.parse_args()
    summary_path = args.summary or args.phase_measurements.parent / "median_summary.csv"
    output_directory = args.output_directory or args.phase_measurements.parent / "pair_residual_maps"
    output_directory.mkdir(parents=True, exist_ok=True)
    summaries = read_summaries(summary_path)
    highlighted = {item.upper() for item in args.highlight}

    measurements: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    with args.phase_measurements.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("good", "").strip().lower() == "true":
                measurements[row["pair_label"]][row["station_id"]].append(row)

    made = 0
    for pair_label, station_rows in sorted(measurements.items()):
        summary = summaries.get(pair_label)
        if not summary:
            continue
        source_lat = float(summary["common_lat"])
        source_lon = float(summary["common_lon"])
        figure, axis = plt.subplots(figsize=(13, 7.5), constrained_layout=True)
        regular: list[tuple[str, float, float, float, int]] = []
        selected: list[tuple[str, float, float, float, int]] = []
        for station, rows in station_rows.items():
            lat = float(rows[0]["station_latitude"])
            lon = float(rows[0]["station_longitude"])
            residual = float(np.median([float(row["residual_lag_seconds"]) for row in rows]))
            item = (station, lat, lon, residual, len(rows))
            if station.split(".")[-1].upper() in highlighted:
                selected.append(item)
            else:
                regular.append(item)
            lons, lats = great_circle_path(source_lat, source_lon, lat, lon)
            axis.plot(lons, lats, color="#4c78a8", alpha=0.16, linewidth=0.6, zorder=1)
        if regular:
            axis.scatter([row[2] for row in regular], [row[1] for row in regular], s=26, color="0.70", edgecolor="0.25", linewidth=0.3, label="Used stations", zorder=2)
        if selected:
            axis.scatter([row[2] for row in selected], [row[1] for row in selected], s=125, marker="*", color="#d62728", edgecolor="black", linewidth=0.6, label="Highlighted stations", zorder=4)
        axis.scatter([source_lon], [source_lat], s=95, marker="*", color="#1f4e79", edgecolor="white", linewidth=0.6, label="Pair centroid", zorder=5)
        for station, lat, lon, residual, count in sorted(regular + selected):
            marked = station.split(".")[-1].upper() in highlighted
            axis.annotate(
                f"{station} {residual:+.3f} s (n={count})", (lon, lat),
                xytext=(4, 4), textcoords="offset points",
                fontsize=5.7 if not marked else 8.4,
                color="#8b0000" if marked else "0.22",
                fontweight="bold" if marked else "normal", zorder=5,
            )
        axis.set_xlim(-180, 180)
        axis.set_ylim(-95, 95)
        axis.set_xticks(range(-180, 181, 30))
        axis.set_yticks(range(-90, 91, 15))
        axis.set_xlabel("Longitude (degrees)")
        axis.set_ylabel("Latitude (degrees)")
        axis.set_title(
            f"{pair_label}: event {summary['event1']} vs {summary['event2']} — accepted residual differential times\n"
            "Labels: station, median residual (s), and number of accepted phase measurements"
        )
        axis.grid(True, alpha=0.3)
        axis.axhline(0.0, color="0.5", linewidth=0.5)
        axis.axvline(0.0, color="0.5", linewidth=0.5)
        axis.legend(loc="lower left")
        output = output_directory / f"{pair_label}_station_residual_map.png"
        figure.savefig(output, dpi=220, bbox_inches="tight")
        plt.close(figure)
        made += 1
    print(f"Created {made} pair residual maps in {output_directory}")


if __name__ == "__main__":
    main()
