#!/usr/bin/env python3
"""Plot all event-pair measurements separately for every station."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


PAIR_ORDER = (
    "P30", "P31", "P33", "P34", "P35", "P37", "P38", "P39",
    "P51", "P79", "P112", "P123", "P140", "P145", "P321", "P355",
)
PHASE_ORDER = ("P", "Pdiff", "PKiKP", "PKP")
PHASE_COLORS = {
    "P": "tab:blue",
    "Pdiff": "tab:orange",
    "PKiKP": "tab:red",
    "PKP": "tab:purple",
}
STATUS_MARKERS = {"A": "o", "R": "x", "X": "s"}


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() == "true"


def parse_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def measurement_status(row: dict[str, str]) -> str:
    if parse_bool(row.get("manual_excluded")):
        return "X"
    return "A" if parse_bool(row.get("good")) else "R"


def minimum_snr(row: dict[str, str]) -> float | None:
    values = [
        value
        for value in (
            parse_float(row.get("automatic_pick1_snr")),
            parse_float(row.get("automatic_pick2_snr")),
        )
        if value is not None
    ]
    return min(values) if len(values) == 2 else None


def load_measurements(path: Path) -> dict[str, list[dict[str, object]]]:
    by_station: dict[str, list[dict[str, object]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = str(row.get("pair_label", ""))
            phase = str(row.get("phase", ""))
            station = str(row.get("station_id", ""))
            if pair not in PAIR_ORDER or phase not in PHASE_ORDER or not station:
                continue
            by_station[station].append(
                {
                    "pair": pair,
                    "phase": phase,
                    "status": measurement_status(row),
                    "shift": parse_float(row.get("pair_residual_seconds")),
                    "correlation": parse_float(row.get("cc")),
                    "snr": minimum_snr(row),
                    "distance": parse_float(row.get("epicentral_distance_degrees")),
                }
            )
    return dict(by_station)


def load_inventory_stations(path: Path | None) -> set[str]:
    if path is None:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            str(row.get("station_id", ""))
            for row in csv.DictReader(handle)
            if str(row.get("station_id", ""))
        }


def plot_station(
    station: str,
    rows: list[dict[str, object]],
    output_directory: Path,
) -> Path:
    figure, axes = plt.subplots(
        3,
        1,
        figsize=(13, 9),
        sharex=True,
        constrained_layout=True,
        gridspec_kw={"height_ratios": (1.35, 1.0, 1.0)},
    )
    x_by_pair = {pair: index for index, pair in enumerate(PAIR_ORDER)}
    phase_offsets = {phase: (index - 1.5) * 0.13 for index, phase in enumerate(PHASE_ORDER)}

    for row in rows:
        phase = str(row["phase"])
        status = str(row["status"])
        x = x_by_pair[str(row["pair"])] + phase_offsets[phase]
        color = PHASE_COLORS[phase]
        marker = STATUS_MARKERS[status]
        for axis, key in zip(axes, ("shift", "correlation", "snr")):
            value = row[key]
            if value is None:
                continue
            axis.scatter(
                x,
                value,
                color=color,
                marker=marker,
                s=55 if status != "X" else 62,
                linewidth=1.3,
                edgecolors="black" if marker == "s" else None,
                zorder=3,
            )

    axes[0].axhline(0.0, color="0.35", linewidth=0.8, linestyle="--")
    axes[0].axhspan(-0.05, 0.05, color="#E8F3E8", alpha=0.65, zorder=0)
    axes[0].set_ylabel("Differential time shift (s)")
    axes[1].axhline(0.875, color="0.35", linewidth=0.9, linestyle="--")
    axes[1].axhspan(0.0, 0.85, color="#FCE4D6", alpha=0.55, zorder=0)
    axes[1].set_ylim(0.0, 1.02)
    axes[1].set_ylabel("Correlation")
    axes[2].axhline(1.0, color="0.35", linewidth=0.9, linestyle="--")
    axes[2].axhspan(0.0, 1.0, color="#FCE4D6", alpha=0.55, zorder=0)
    snrs = [float(row["snr"]) for row in rows if row["snr"] is not None]
    axes[2].set_ylim(0.0, max(2.0, min(20.0, max(snrs, default=2.0) * 1.08)))
    axes[2].set_ylabel("Minimum SNR")
    axes[2].set_xlabel("Event pair")

    for axis in axes:
        axis.grid(True, alpha=0.22)
        axis.set_xlim(-0.6, len(PAIR_ORDER) - 0.4)
    if not rows:
        axes[0].text(
            0.5,
            0.5,
            "No phase measurements available",
            transform=axes[0].transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color="0.35",
        )
    axes[2].set_xticks(range(len(PAIR_ORDER)), PAIR_ORDER, rotation=45, ha="right")

    distances = [float(row["distance"]) for row in rows if row["distance"] is not None]
    distance_text = f"; distance range {min(distances):.1f}–{max(distances):.1f}°" if distances else ""
    figure.suptitle(
        f"{station}: all measured event pairs{distance_text}\n"
        "phase color; marker status: accepted circle, rejected x, excluded square",
        fontsize=14,
    )
    phase_handles = [
        Line2D([], [], color=PHASE_COLORS[phase], marker="o", linestyle="None", label=phase)
        for phase in PHASE_ORDER
    ]
    status_handles = [
        Line2D(
            [], [], color="0.2", marker=marker, linestyle="None", label=label,
            markerfacecolor="none" if marker == "s" else "0.2",
        )
        for label, marker in (("Accepted", "o"), ("Rejected", "x"), ("Excluded", "s"))
    ]
    axes[0].legend(
        handles=phase_handles + status_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.27),
        ncol=7,
        fontsize=8,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / f"{station.replace('.', '_')}_all_pairs.png"
    figure.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(figure)
    return output


def main() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_measurements", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument(
        "--inventory",
        type=Path,
        help="Optional station inventory; stations without measurements get an explicit empty plot.",
    )
    args = parser.parse_args()
    output_directory = (
        args.output_directory
        or args.phase_measurements.parent / "station_pair_plots"
    )
    by_station = load_measurements(args.phase_measurements)
    stations = set(by_station) | load_inventory_stations(args.inventory)
    if not stations:
        raise RuntimeError("No station measurements were found")
    for station in sorted(stations):
        plot_station(station, by_station.get(station, []), output_directory)
    print(output_directory)
    print(f"Plotted {len(stations)} stations.")
    return output_directory


if __name__ == "__main__":
    main()
