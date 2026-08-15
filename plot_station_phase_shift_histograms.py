#!/usr/bin/env python3
"""Make one histogram panel per station for accepted same-phase shifts."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


PHASES = ("P", "PcP", "ScP", "PKP", "PKiKP")
PHASE_COLORS = {
    "P": "tab:blue",
    "PcP": "tab:orange",
    "ScP": "tab:green",
    "PKP": "tab:purple",
    "PKiKP": "tab:red",
}
HIGHLIGHT_STATIONS = {"WMQ", "AAK", "LSZ", "OTAV", "SNZO", "TEIG", "TRQA", "LOHW", "RWWY"}


def main() -> Path:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_measurements", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--include-not-good",
        action="store_true",
        help="Include measurements rejected by the correlation/geometry QC.",
    )
    parser.add_argument(
        "--highlight-stations",
        nargs="*",
        default=sorted(HIGHLIGHT_STATIONS),
        help="Station codes to highlight in the grid (default: the nine requested stations).",
    )
    args = parser.parse_args()
    output = args.output or args.phase_measurements.parent / "station_phase_shift_histograms.png"

    by_station: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with args.phase_measurements.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if not args.include_not_good and str(row.get("good", "")).strip().lower() != "true":
                continue
            phase = str(row.get("phase", ""))
            if phase not in PHASES:
                continue
            try:
                shift = float(row["residual_lag_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(shift):
                by_station[str(row["station_id"])][phase].append(shift)

    stations = sorted(by_station)
    if not stations:
        raise RuntimeError("No usable station-phase shifts were found")
    all_shifts = [value for phases in by_station.values() for values in phases.values() for value in values]
    limit = max(0.05, float(np.max(np.abs(all_shifts))) * 1.08)
    bins = np.linspace(-limit, limit, 17)
    columns = 9
    rows = int(np.ceil(len(stations) / columns))
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(columns * 2.15, rows * 1.75),
        sharex=True,
        sharey=True,
        squeeze=False,
        constrained_layout=True,
    )
    axes_flat = axes.ravel()
    highlight = {value.upper() for value in args.highlight_stations}
    for axis, station in zip(axes_flat, stations):
        phases = by_station[station]
        for phase in PHASES:
            values = phases.get(phase, [])
            if values:
                axis.hist(
                    values,
                    bins=bins,
                    histtype="step",
                    linewidth=1.2,
                    color=PHASE_COLORS[phase],
                    label=phase,
                )
        axis.axvline(0.0, color="0.35", linewidth=0.6)
        station_code = station.split(".")[-1].upper()
        if station_code in highlight:
            axis.set_facecolor("#fff1b8")
            for spine in axis.spines.values():
                spine.set_color("#d62728")
                spine.set_linewidth(1.8)
            title_prefix = "★ "
        else:
            title_prefix = ""
        axis.set_title(
            f"{title_prefix}{station} (n={sum(len(v) for v in phases.values())})",
            fontsize=8,
            color="#b22222" if title_prefix else "black",
        )
        axis.grid(True, axis="y", alpha=0.22)
        axis.tick_params(labelsize=7)
    for axis in axes_flat[len(stations):]:
        axis.set_visible(False)
    for axis in axes[-1, :]:
        axis.set_xlabel("Residual shift (s)", fontsize=8)
    for axis in axes[:, 0]:
        axis.set_ylabel("Count", fontsize=8)
    handles = [
        plt.Line2D([], [], color=PHASE_COLORS[phase], linewidth=1.5, label=phase)
        for phase in PHASES
    ]
    figure.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.985),
        ncol=len(PHASES),
        fontsize=9,
    )
    figure.suptitle(
        "Accepted same-phase differential shifts by station\n"
        "histograms show residual shift after the pair-wide time shift; "
        "yellow/red panels mark the nine stations of interest",
        fontsize=14,
        y=1.04,
    )
    figure.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(figure)
    print(output)
    print(f"Plotted {len(stations)} stations and {len(all_shifts)} accepted shifts.")
    return output


if __name__ == "__main__":
    main()
