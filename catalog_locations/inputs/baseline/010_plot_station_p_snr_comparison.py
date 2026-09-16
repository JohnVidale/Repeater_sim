#!/usr/bin/env python3
"""Plot first-event versus second-event P-wave SNR for every station/pair.

Colors follow the ``pairs_purple`` and ``pairs_blue`` groups in the analysis
configuration.  Marker radius increases linearly with measured P-wave
correlation; both SNR axes are logarithmic because quiet records can produce
very large scale/noise ratios.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "analysis_config.json"


def latest_station_results(root: Path) -> Path:
    candidates = list(root.glob("*/station_results.csv"))
    if not candidates:
        raise FileNotFoundError(f"No station_results.csv found beneath {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def marker_area(correlation: float) -> float:
    """Return matplotlib marker area with radius proportional to correlation."""
    radius_points = 2.0 + 7.0 * min(1.0, max(0.0, correlation))
    return math.pi * radius_points**2


def main() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--station-results", type=Path, help="Input CSV; defaults to newest P-analysis result.")
    parser.add_argument("--output", type=Path, help="Output PNG; defaults beside station_results.csv.")
    parser.add_argument(
        "--minimum-snr",
        type=float,
        default=0.0,
        help="Require both event SNR values to exceed this value (default: no SNR cutoff).",
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text())
    station_results = args.station_results or latest_station_results(Path(config["output_root"]))
    suffix = f"_snr_gt_{args.minimum_snr:g}" if args.minimum_snr > 0 else ""
    output = args.output or station_results.parent / f"p_wave_snr_event1_vs_event2{suffix}.png"
    purple = set(map(str, config.get("pairs_purple", [])))
    blue = set(map(str, config.get("pairs_blue", [])))
    colors = {"purple": "#6a3d9a", "blue": "#1f78b4", "other": "#666666"}

    groups: dict[str, list[tuple[float, float, float]]] = {"purple": [], "blue": [], "other": []}
    skipped = 0
    with station_results.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                snr1 = float(row["snr1_scale_over_noise"])
                snr2 = float(row["snr2_scale_over_noise"])
                correlation = float(row["new_correlation"])
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue
            if not all(math.isfinite(value) and value > 0.0 for value in (snr1, snr2)):
                skipped += 1
                continue
            if snr1 <= args.minimum_snr or snr2 <= args.minimum_snr:
                skipped += 1
                continue
            pair = str(row["pair_label"])
            group = "purple" if pair in purple else "blue" if pair in blue else "other"
            groups[group].append((snr1, snr2, correlation))

    all_values = [value for group in groups.values() for row in group for value in row[:2]]
    full_limits = (min(all_values) / 1.8, max(all_values) * 1.8)
    # Near-zero noise estimates make a few ratios extreme; the right panel
    # makes the dense, physically useful population readable without dropping
    # those points from the full panel.
    zoom_limits = tuple(np.percentile(all_values, [1.0, 99.0]))
    zoom_limits = (zoom_limits[0] / 1.35, zoom_limits[1] * 1.35)
    figure, axes = plt.subplots(1, 2, figsize=(16, 7.5), constrained_layout=True)
    for axis, limits, title in (
        (axes[0], full_limits, "Full logarithmic range"),
        (axes[1], zoom_limits, "Central 98% of SNR values"),
    ):
        for group, values in groups.items():
            if not values:
                continue
            x, y, cc = zip(*values)
            axis.scatter(
                x,
                y,
                s=[marker_area(value) for value in cc],
                color=colors[group],
                alpha=0.70,
                edgecolor="black",
                linewidth=0.35,
                zorder=3,
            )
        axis.plot(limits, limits, color="0.25", linestyle="--", linewidth=1.1, label="Equal SNR")
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_xlim(*limits)
        axis.set_ylim(*limits)
        axis.set_aspect("equal", adjustable="box")
        axis.set_title(title)
        axis.set_xlabel("Event 1 P-wave SNR")
        axis.grid(True, which="both", alpha=0.22, zorder=0)
    axes[0].set_ylabel("Event 2 P-wave SNR")
    figure.suptitle(
        "Station P-wave SNR comparison\n"
        "SNR = correlation-window RMS / median pre-P noise RMS; marker radius is proportional to P-wave correlation",
        fontsize=15,
    )
    color_handles = [
        Line2D([], [], marker="o", linestyle="", markersize=9, markerfacecolor=colors["purple"], markeredgecolor="black", label="Purple group"),
        Line2D([], [], marker="o", linestyle="", markersize=9, markerfacecolor=colors["blue"], markeredgecolor="black", label="Blue group"),
    ]
    radius_handles = [
        Line2D([], [], marker="o", linestyle="", markersize=2.0 + 7.0 * cc, markerfacecolor="white", markeredgecolor="black", label=f"P cc = {cc:.1f}")
        for cc in (0.5, 0.75, 1.0)
    ]
    first_legend = axes[0].legend(handles=color_handles, loc="upper left", title="Pair group")
    axes[0].add_artist(first_legend)
    axes[1].legend(handles=radius_handles, loc="lower right", title="Marker radius")
    figure.savefig(output, dpi=220)
    plt.close(figure)

    total = sum(len(values) for values in groups.values())
    print(output)
    print(
        f"Plotted {total} station results with both SNR values > {args.minimum_snr:g}; "
        f"skipped {skipped}."
    )
    print(
        "Counts: " + ", ".join(f"{group}={len(values)}" for group, values in groups.items())
    )
    return output


if __name__ == "__main__":
    main()
