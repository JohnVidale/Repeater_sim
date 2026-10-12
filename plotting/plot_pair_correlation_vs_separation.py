#!/usr/bin/env python3
"""Plot a direct-P correlation summary against preferred relative separation."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def direct_p_correlations(
    output_directory: Path, statistic: str
) -> dict[str, float]:
    """Return a consistent direct-P correlation statistic for each pair.

    Non-median options intentionally consider only accepted (``good``) P rows,
    matching the population summarized by ``phase_summary.csv``.
    """
    if statistic == "median":
        return {
            row["pair_label"]: float(row["median_cc"])
            for row in rows(output_directory / "phase_summary.csv")
            if row["phase"] == "P" and row.get("median_cc")
        }
    correlations: dict[str, list[float]] = {}
    for row in rows(output_directory / "phase_measurements.csv"):
        if row.get("phase") != "P" or row.get("good") != "True":
            continue
        try:
            correlations.setdefault(row["pair_label"], []).append(float(row["cc"]))
        except (KeyError, TypeError, ValueError):
            continue
    if statistic == "maximum":
        return {pair: max(values) for pair, values in correlations.items()}
    return {
        pair: sum(sorted(values, reverse=True)[:3]) / min(3, len(values))
        for pair, values in correlations.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "analysis_config.json")
    parser.add_argument("--output-directory", type=Path, default=ROOT / "latest_run")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--x-max", type=float)
    parser.add_argument("--y-min", type=float, default=0.84)
    parser.add_argument(
        "--correlation-statistic",
        choices=("median", "maximum", "top3_mean"),
        default="median",
        help="Use the median, highest, or mean of the three highest accepted direct-P correlations.",
    )
    parser.add_argument(
        "--unresolved-pairs",
        nargs="*",
        default=[],
        help="Pairs with no resolved separation; show their correlations on the y-axis.",
    )
    parser.add_argument(
        "--exclude-pairs",
        nargs="*",
        default=[],
        help="Pair labels to omit from this display only.",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    output_dir = args.output_directory
    output = args.output or output_dir / "pair_correlation_vs_relative_separation.png"
    locations = {
        row["pair"]: row
        for row in rows(output_dir / "median_relative_location_offsets_p_only_with_bootstrap_uncertainty.csv")
    }
    correlations = direct_p_correlations(output_dir, args.correlation_statistic)
    purple, blue = set(config["pairs_purple"]), set(config["pairs_blue"])
    orange = set(config.get("pairs_orange", []))
    unresolved_pairs = set(args.unresolved_pairs)
    excluded_pairs = set(args.exclude_pairs)
    colors = {"orange": "#ffb000", "purple": "#6a3d9a", "blue": "#1f78b4", "other": "#555555"}
    figure, axis = plt.subplots(figsize=(9.5, 6.5), constrained_layout=True)
    missing = []
    unresolved_plotted = []
    unresolved_label_offsets = [(7, 8), (7, -12), (7, 22)]
    plotted_groups: set[str] = set()
    for pair in config["pairs"]:
        if pair in excluded_pairs:
            continue
        row = locations.get(pair, {})
        separation = row.get("horizontal_km") or row.get("separation_3d_km")
        if pair not in correlations:
            missing.append(pair)
            continue
        group = "orange" if pair in orange else "purple" if pair in purple else "blue" if pair in blue else "other"
        y = correlations[pair]
        plotted_groups.add(group)
        if pair in unresolved_pairs:
            label_offset = unresolved_label_offsets[
                len(unresolved_plotted) % len(unresolved_label_offsets)
            ]
            axis.scatter(
                0.0,
                y,
                s=86,
                marker="s",
                facecolor="none",
                edgecolor=colors[group],
                linewidth=1.5,
                zorder=4,
            )
            axis.annotate(
                f"{pair} unresolved",
                (0.0, y),
                xytext=label_offset,
                textcoords="offset points",
                fontsize=9,
                color=colors[group],
            )
            unresolved_plotted.append(pair)
            continue
        if not separation:
            missing.append(pair)
            continue
        x = float(separation)
        axis.scatter(x, y, s=86, color=colors[group], edgecolor="black", linewidth=0.6, zorder=3)
        axis.annotate(pair, (x, y), xytext=(6, 7), textcoords="offset points", fontsize=9)
    axis.set_xlabel("Preferred horizontal repeater separation (km)")
    statistic_label = {
        "median": "Median direct-P correlation",
        "maximum": "Highest accepted direct-P correlation",
        "top3_mean": "Mean of top three accepted direct-P correlations",
    }[args.correlation_statistic]
    axis.set_ylabel(statistic_label)
    axis.set_title(f"{statistic_label} versus relative separation")
    if args.x_max is not None:
        axis.set_xlim(0.0, args.x_max)
    axis.set_ylim(args.y_min, 1.005)
    axis.grid(True, alpha=0.28, zorder=0)
    legend_groups = ("orange", "purple", "blue")
    handles = [
        Line2D(
            [], [], marker="o", linestyle="", markersize=10,
            markerfacecolor=colors[group], markeredgecolor="black",
            label=f"{group.title()} group",
        )
        for group in legend_groups
        if group in plotted_groups
    ]
    if unresolved_plotted:
        handles.append(
            Line2D(
                [], [], marker="s", linestyle="", markersize=9,
                markerfacecolor="none", markeredgecolor="#333333",
                label="Unresolved separation (on y-axis)",
            )
        )
    axis.legend(handles=handles, loc="lower left")
    figure.savefig(output, dpi=220)
    print(output)
    print("Not plotted: " + (", ".join(missing) if missing else "none"))


if __name__ == "__main__":
    main()
