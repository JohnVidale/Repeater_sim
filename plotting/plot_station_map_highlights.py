#!/usr/bin/env python3
"""Map stations represented in phase measurements and highlight selected codes."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle


DEFAULT_HIGHLIGHTS = ("LPAZ", "VNDA", "CHTO", "KEV", "OTAV", "PMSA", "QSPA", "TRQA", "SJG")


def great_circle_path(
    source_latitude: float,
    source_longitude: float,
    station_latitude: float,
    station_longitude: float,
    points: int = 80,
) -> tuple[np.ndarray, np.ndarray]:
    """Return a split longitude/latitude path along the shorter great circle."""
    def vector(latitude: float, longitude: float) -> np.ndarray:
        latitude_rad = math.radians(latitude)
        longitude_rad = math.radians(longitude)
        return np.array(
            [
                math.cos(latitude_rad) * math.cos(longitude_rad),
                math.cos(latitude_rad) * math.sin(longitude_rad),
                math.sin(latitude_rad),
            ]
        )

    first = vector(source_latitude, source_longitude)
    second = vector(station_latitude, station_longitude)
    angle = math.acos(float(np.clip(np.dot(first, second), -1.0, 1.0)))
    fractions = np.linspace(0.0, 1.0, points)
    if angle < 1e-9:
        vectors = np.repeat(first[None, :], points, axis=0)
    else:
        vectors = np.array(
            [
                math.sin((1.0 - fraction) * angle) / math.sin(angle) * first
                + math.sin(fraction * angle) / math.sin(angle) * second
                for fraction in fractions
            ]
        )
        vectors /= np.linalg.norm(vectors, axis=1)[:, None]
    latitudes = np.degrees(np.arcsin(vectors[:, 2]))
    longitudes = np.degrees(np.arctan2(vectors[:, 1], vectors[:, 0]))
    longitudes[np.where(np.abs(np.diff(longitudes)) > 180.0)[0] + 1] = np.nan
    return longitudes, latitudes


def read_pair_centroids(path: Path) -> list[tuple[float, float]]:
    centroids: list[tuple[float, float]] = []
    if not path.is_file():
        return centroids
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                centroids.append((float(row["common_lat"]), float(row["common_lon"])))
            except (KeyError, TypeError, ValueError):
                continue
    return centroids


def main() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_measurements", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--highlight", nargs="*", default=DEFAULT_HIGHLIGHTS)
    parser.add_argument(
        "--source-summary",
        type=Path,
        default=None,
        help="Median-summary CSV defining the pair-centroid source region.",
    )
    args = parser.parse_args()
    output = args.output or args.phase_measurements.parent / "station_map_highlighted.png"
    highlighted = {code.upper() for code in args.highlight}
    source_summary = args.source_summary or args.phase_measurements.parent / "median_summary.csv"

    # The mapped number is the median fine-search residual after subtracting
    # the pair median: a station-specific differential-time diagnostic, rather
    # than the several-second overall event-pair alignment shift.
    stations: dict[str, dict[str, object]] = {}
    with args.phase_measurements.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("good", "")).strip().lower() != "true":
                continue
            try:
                station = str(row["station_id"])
                entry = stations.setdefault(
                    station,
                    {
                        "latitude": float(row["station_latitude"]),
                        "longitude": float(row["station_longitude"]),
                        "residuals": [],
                    },
                )
                entry["residuals"].append(float(row["residual_lag_seconds"]))
            except (KeyError, TypeError, ValueError):
                continue

    figure, axis = plt.subplots(figsize=(13, 7.5), constrained_layout=True)
    centroids = read_pair_centroids(source_summary)
    source_latitude = source_longitude = None
    if centroids:
        source_latitude = float(np.mean([row[0] for row in centroids]))
        source_longitude = float(np.mean([row[1] for row in centroids]))
        for _, latitude, longitude in [
            (station, data["latitude"], data["longitude"])
            for station, data in stations.items()
        ]:
            longitudes, latitudes = great_circle_path(
                source_latitude, source_longitude, latitude, longitude
            )
            axis.plot(longitudes, latitudes, color="#4c78a8", alpha=0.13, linewidth=0.55, zorder=1)
        centroid_lats = [row[0] for row in centroids]
        centroid_lons = [row[1] for row in centroids]
        padding = 0.12
        axis.add_patch(
            Rectangle(
                (min(centroid_lons) - padding, min(centroid_lats) - padding),
                max(2.0 * padding, max(centroid_lons) - min(centroid_lons) + 2.0 * padding),
                max(2.0 * padding, max(centroid_lats) - min(centroid_lats) + 2.0 * padding),
                facecolor="#4c78a8", edgecolor="#1f4e79", alpha=0.35, linewidth=1.0,
                label="Pair-centroid source region", zorder=3,
            )
        )
        axis.scatter(
            [source_longitude], [source_latitude], s=90, marker="*", color="#1f4e79",
            edgecolor="white", linewidth=0.6, label="Mean source centroid", zorder=5,
        )
    def station_rows(selected_only: bool) -> list[tuple[str, float, float, float]]:
        rows: list[tuple[str, float, float, float]] = []
        for station, data in stations.items():
            is_highlighted = station.split(".")[-1].upper() in highlighted
            if is_highlighted != selected_only:
                continue
            residuals = data["residuals"]
            rows.append(
                (
                    station,
                    float(data["latitude"]),
                    float(data["longitude"]),
                    float(np.median(residuals)),
                )
            )
        return rows

    regular = station_rows(selected_only=False)
    selected = station_rows(selected_only=True)
    if regular:
        axis.scatter([row[2] for row in regular], [row[1] for row in regular], s=24, color="0.70", edgecolor="0.25", linewidth=0.3, label="Other used stations", zorder=2)
    if selected:
        axis.scatter([row[2] for row in selected], [row[1] for row in selected], s=125, marker="*", color="#d62728", edgecolor="black", linewidth=0.6, label="Highlighted stations", zorder=4)
    for station, lat, lon, residual in sorted(regular + selected):
        is_highlighted = station.split(".")[-1].upper() in highlighted
        axis.annotate(
            f"{station} {residual:+.3f} s",
            (lon, lat),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=5.4 if not is_highlighted else 8.5,
            color="#8b0000" if is_highlighted else "0.22",
            fontweight="bold" if is_highlighted else "normal",
            zorder=5,
        )

    axis.set_xlim(-180, 180)
    # Add a small margin so the labels for near-polar stations (especially
    # QSPA) remain inside the figure.
    axis.set_ylim(-95, 95)
    axis.set_xticks(range(-180, 181, 30))
    axis.set_yticks(range(-90, 91, 15))
    axis.set_xlabel("Longitude (degrees)")
    axis.set_ylabel("Latitude (degrees)")
    axis.set_title(
        "Stations used in the phase analysis, source region, and raypaths\n"
        "Labels: station and median residual differential time (s); "
        "highlighted: LPAZ, VNDA, CHTO, KEV, OTAV, PMSA, QSPA, TRQA, SJG"
    )
    axis.grid(True, alpha=0.3)
    axis.axhline(0.0, color="0.5", linewidth=0.5)
    axis.axvline(0.0, color="0.5", linewidth=0.5)
    axis.legend(loc="lower left")
    figure.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(figure)
    print(output)
    print(
        f"Mapped {len(stations)} used stations; highlighted {len(selected)}; "
        f"source centroids {len(centroids)}."
    )
    return output


if __name__ == "__main__":
    main()
