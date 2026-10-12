#!/usr/bin/env python3
"""Compare preferred relative-location vectors from two workflow runs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from openpyxl import load_workbook


LOCATION_FILE = "median_relative_location_offsets_p_only_with_bootstrap_uncertainty.csv"
WORKBOOK_FILL_NAMES = {
    "#00B0F0": "Blue label",
    "#7030A0": "Purple label",
    "#FFC000": "Orange label",
}


def read_pair_label_colors(workbook_path: Path, sheet_name: str = "pairs") -> dict[str, str]:
    """Return pair-label colors from the direct RGB fills in column A."""
    workbook = load_workbook(workbook_path, read_only=False, data_only=True)
    try:
        worksheet = workbook[sheet_name]
        colors: dict[str, str] = {}
        for cell in worksheet["A"]:
            pair = str(cell.value or "").strip()
            rgb = cell.fill.fgColor.rgb
            if not pair or cell.fill.fill_type != "solid" or not isinstance(rgb, str):
                continue
            rgb = rgb.upper()
            if len(rgb) == 8:
                rgb = rgb[2:]
            if len(rgb) == 6:
                colors[pair] = f"#{rgb}"
        return colors
    finally:
        workbook.close()


def read_locations(
    run_directory: Path, location_file: str = LOCATION_FILE
) -> dict[str, dict[str, float | str]]:
    path = run_directory / location_file
    rows: dict[str, dict[str, float | str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("status") or "").strip():
                continue
            try:
                rows[str(row["pair"])] = {
                    "east_km": float(row["east_km"]),
                    "north_km": float(row["north_km"]),
                    "east_sigma_km": float(row["east_sigma_km"]),
                    "north_sigma_km": float(row["north_sigma_km"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def add_solution(
    axis: plt.Axes,
    row: dict[str, float | str],
    color: str,
    marker: str,
    label: str,
    zorder: int,
) -> None:
    east = float(row["east_km"])
    north = float(row["north_km"])
    axis.add_patch(
        Ellipse(
            (east, north),
            2 * float(row["east_sigma_km"]),
            2 * float(row["north_sigma_km"]),
            facecolor=color,
            edgecolor=color,
            alpha=0.12,
            linewidth=0.7,
            zorder=zorder,
        )
    )
    axis.scatter(
        east,
        north,
        marker=marker,
        s=38,
        color=color,
        edgecolor="white",
        linewidth=0.45,
        zorder=zorder + 1,
        label=label,
    )


def plot(
    previous: Path,
    current: Path,
    output: Path,
    axis_limit: float | None = None,
    current_only: bool = False,
    location_file: str = LOCATION_FILE,
    fit_label: str = "P-only fit",
    pair_color_workbook: Path | None = None,
    pair_color_sheet: str = "pairs",
    allowed_pair_colors: set[str] | None = None,
    excluded_pairs: set[str] | None = None,
    no_solution_pairs: list[str] | None = None,
) -> None:
    new = read_locations(current, location_file)
    old = {} if current_only else read_locations(previous, location_file)
    pair_values = set(new) if current_only else set(old) & set(new)
    pairs = sorted(pair_values, key=lambda value: (int(value[1:]) if value[1:].isdigit() else value))
    if not pairs:
        raise ValueError("No solved pairs are shared by the two runs")
    pair_colors = (
        read_pair_label_colors(pair_color_workbook, pair_color_sheet)
        if pair_color_workbook is not None
        else {}
    )
    if allowed_pair_colors is not None:
        pairs = [pair for pair in pairs if pair_colors.get(pair) in allowed_pair_colors]
        if not pairs:
            raise ValueError("No solved pairs match the requested label colors")
    if excluded_pairs:
        pairs = [pair for pair in pairs if pair not in excluded_pairs]
        if not pairs:
            raise ValueError("No solved pairs remain after exclusions")

    figure, axis = plt.subplots(figsize=(8.6, 7.4), constrained_layout=True)
    all_coordinates = []
    legend_colors: set[str] = set()
    for pair in pairs:
        after = new[pair]
        after_xy = (float(after["east_km"]), float(after["north_km"]))
        before = old.get(pair)
        before_xy = (
            (float(before["east_km"]), float(before["north_km"]))
            if before is not None
            else after_xy
        )
        after_extent = (
            abs(after_xy[0]) + float(after["east_sigma_km"]),
            abs(after_xy[1]) + float(after["north_sigma_km"]),
        )
        if current_only:
            all_coordinates.append(after_extent)
        else:
            before_extent = (
                abs(before_xy[0]) + float(before["east_sigma_km"]),
                abs(before_xy[1]) + float(before["north_sigma_km"]),
            )
            all_coordinates.extend((before_extent, after_extent))
        if not current_only:
            axis.annotate(
                "",
                xy=after_xy,
                xytext=before_xy,
                arrowprops={"arrowstyle": "->", "color": "0.45", "lw": 0.65, "alpha": 0.7},
                zorder=1,
            )
            add_solution(axis, before, "#e68613", "^", "Previous run" if pair == pairs[0] else "_nolegend_", 2)
        symbol_color = pair_colors.get(pair, "#1f77b4")
        if pair_color_workbook is None:
            legend_label = "Current run" if pair == pairs[0] else "_nolegend_"
        elif symbol_color not in legend_colors:
            legend_label = WORKBOOK_FILL_NAMES.get(symbol_color, "Other/no label fill")
            legend_colors.add(symbol_color)
        else:
            legend_label = "_nolegend_"
        add_solution(axis, after, symbol_color, "o", legend_label, 4)
        axis.annotate(
            pair,
            after_xy,
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=7,
            color=symbol_color,
        )

    if axis_limit is None:
        extent = max(max(abs(value) for value in coordinate) for coordinate in all_coordinates)
        padding = max(0.12, 0.14 * extent)
        axis_limit = extent + padding
    axis.set_xlim(-axis_limit, axis_limit)
    axis.set_ylim(-axis_limit, axis_limit)
    axis.axhline(0, color="0.5", linewidth=0.7)
    axis.axvline(0, color="0.5", linewidth=0.7)
    axis.grid(color="0.9", linewidth=0.7)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Event 2 − event 1 east offset (km)")
    axis.set_ylabel("Event 2 − event 1 north offset (km)")
    axis.set_title(
        (
            "Current relative locations\n"
            if current_only
            else "Relative-location comparison: previous versus current run\n"
        )
        + f"{fit_label}; ellipses are marginal 1σ bootstrap uncertainty"
        + ("\nSymbol colors follow pair-label fills in ICevents_working.xlsx" if pair_color_workbook else "")
    )
    axis.legend(loc="upper left", fontsize=8, frameon=True)
    if no_solution_pairs:
        axis.text(
            0.5,
            0.015,
            "No P-only solution: " + ", ".join(no_solution_pairs),
            transform=axis.transAxes,
            ha="center",
            va="bottom",
            fontsize=8,
            color="0.3",
        )
    figure.savefig(output.with_suffix(".png"), dpi=220)
    figure.savefig(output.with_suffix(".pdf"))
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--axis-limit", type=float)
    parser.add_argument("--current-only", action="store_true")
    parser.add_argument("--location-file", default=LOCATION_FILE)
    parser.add_argument("--fit-label", default="P-only fit")
    parser.add_argument(
        "--pair-color-workbook",
        type=Path,
        help="Excel workbook whose pair-label fills in column A set current symbol colors",
    )
    parser.add_argument("--pair-color-sheet", default="pairs")
    parser.add_argument(
        "--blue-purple-only",
        action="store_true",
        help="Plot only pairs with blue or purple label fills.",
    )
    parser.add_argument(
        "--exclude-pairs",
        nargs="*",
        default=[],
        help="Pair labels to omit from this display only.",
    )
    parser.add_argument(
        "--no-solution-pairs",
        nargs="*",
        default=[],
        help="Pair labels with no solution; shown as a figure note.",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plot(
        args.previous,
        args.current,
        args.output,
        args.axis_limit,
        args.current_only,
        args.location_file,
        args.fit_label,
        args.pair_color_workbook,
        args.pair_color_sheet,
        {"#00B0F0", "#7030A0"} if args.blue_purple_only else None,
        set(args.exclude_pairs),
        args.no_solution_pairs,
    )
    print(args.output.with_suffix(".png"))
    print(args.output.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
