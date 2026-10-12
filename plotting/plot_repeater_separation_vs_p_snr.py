#!/usr/bin/env python3
"""Plot resolved repeater separation against accepted-P higher-trace SNR."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mean_accepted_p_higher_snr(measurements: Path) -> dict[str, float]:
    """Use the higher event SNR per accepted P arrival, then mean by pair."""
    values: dict[str, list[float]] = {}
    for row in rows(measurements):
        if row.get("phase") != "P" or row.get("good") != "True":
            continue
        try:
            snr = max(
                float(row["automatic_pick1_snr"]),
                float(row["automatic_pick2_snr"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(snr) and snr > 0:
            values.setdefault(row["pair_label"], []).append(snr)
    return {pair: float(np.mean(pair_values)) for pair, pair_values in values.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "analysis_config.json")
    parser.add_argument("--output-directory", type=Path, default=ROOT / "latest_run")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-pairs", nargs="*", default=[])
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    output_directory = args.output_directory
    separations = {
        row["pair"]: float(row["horizontal_km"])
        for row in rows(
            output_directory
            / "median_relative_location_offsets_p_only_with_bootstrap_uncertainty.csv"
        )
        if row.get("horizontal_km")
    }
    snrs = mean_accepted_p_higher_snr(output_directory / "phase_measurements.csv")
    excluded = set(args.exclude_pairs)
    purple, blue = set(config["pairs_purple"]), set(config["pairs_blue"])
    orange = set(config.get("pairs_orange", []))
    colors = {"orange": "#ffb000", "purple": "#6a3d9a", "blue": "#1f78b4", "other": "#555555"}

    figure, axis = plt.subplots(figsize=(9.5, 6.5), constrained_layout=True)
    plotted_groups: set[str] = set()
    missing: list[str] = []
    for pair in config["pairs"]:
        if pair in excluded:
            continue
        snr, separation = snrs.get(pair), separations.get(pair)
        if snr is None or separation is None or not math.isfinite(separation):
            missing.append(pair)
            continue
        group = "orange" if pair in orange else "purple" if pair in purple else "blue" if pair in blue else "other"
        plotted_groups.add(group)
        axis.scatter(separation, snr, s=86, color=colors[group], edgecolor="black", linewidth=0.6, zorder=3)
        axis.annotate(pair, (separation, snr), xytext=(6, 7), textcoords="offset points", fontsize=9)

    axis.set_xlabel("Preferred horizontal repeater separation (km)")
    axis.set_ylabel("Mean higher-trace SNR of accepted direct-P arrivals")
    axis.set_title("Accepted direct-P higher-trace SNR versus repeater separation")
    axis.grid(True, alpha=0.28, zorder=0)
    handles = [
        Line2D([], [], marker="o", linestyle="", markersize=10, markerfacecolor=colors[group], markeredgecolor="black", label=f"{group.title()} group")
        for group in ("orange", "purple", "blue")
        if group in plotted_groups
    ]
    if handles:
        axis.legend(handles=handles, loc="best")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=220)
    print(args.output)
    print("Not plotted: " + (", ".join(missing) if missing else "none"))


if __name__ == "__main__":
    main()
