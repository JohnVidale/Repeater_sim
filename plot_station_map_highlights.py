#!/usr/bin/env python3
"""Map stations represented in phase measurements and highlight selected codes."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


DEFAULT_HIGHLIGHTS = ("LPAZ", "VNDA", "CHTO", "KEV", "OTAV", "PMSA", "QSPA", "TRQA", "SJG")


def main() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_measurements", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--highlight", nargs="*", default=DEFAULT_HIGHLIGHTS)
    args = parser.parse_args()
    output = args.output or args.phase_measurements.parent / "station_map_highlighted.png"
    highlighted = {code.upper() for code in args.highlight}

    stations: dict[str, tuple[float, float]] = {}
    with args.phase_measurements.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("good", "")).strip().lower() != "true":
                continue
            try:
                stations[str(row["station_id"])] = (
                    float(row["station_latitude"]),
                    float(row["station_longitude"]),
                )
            except (KeyError, TypeError, ValueError):
                continue

    figure, axis = plt.subplots(figsize=(13, 7.5), constrained_layout=True)
    regular = [(station, lat, lon) for station, (lat, lon) in stations.items() if station.split(".")[-1].upper() not in highlighted]
    selected = [(station, lat, lon) for station, (lat, lon) in stations.items() if station.split(".")[-1].upper() in highlighted]
    if regular:
        axis.scatter([row[2] for row in regular], [row[1] for row in regular], s=24, color="0.70", edgecolor="0.25", linewidth=0.3, label="Other used stations", zorder=2)
    if selected:
        axis.scatter([row[2] for row in selected], [row[1] for row in selected], s=125, marker="*", color="#d62728", edgecolor="black", linewidth=0.6, label="Highlighted stations", zorder=4)
        for station, lat, lon in sorted(selected):
            axis.annotate(station, (lon, lat), xytext=(5, 5), textcoords="offset points", fontsize=9, color="#8b0000", fontweight="bold", zorder=5)

    axis.set_xlim(-180, 180)
    # Add a small margin so the labels for near-polar stations (especially
    # QSPA) remain inside the figure.
    axis.set_ylim(-95, 95)
    axis.set_xticks(range(-180, 181, 30))
    axis.set_yticks(range(-90, 91, 15))
    axis.set_xlabel("Longitude (degrees)")
    axis.set_ylabel("Latitude (degrees)")
    axis.set_title("Stations used in the phase analysis\nHighlighted: LPAZ, VNDA, CHTO, KEV, OTAV, PMSA, QSPA, TRQA, SJG")
    axis.grid(True, alpha=0.3)
    axis.axhline(0.0, color="0.5", linewidth=0.5)
    axis.axvline(0.0, color="0.5", linewidth=0.5)
    axis.legend(loc="lower left")
    figure.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(figure)
    print(output)
    print(f"Mapped {len(stations)} used stations; highlighted {len(selected)}.")
    return output


if __name__ == "__main__":
    main()
