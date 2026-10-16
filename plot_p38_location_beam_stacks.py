#!/usr/bin/env python3
"""Plot P38 event-pair beam-stack superpositions for two location cases."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from obspy import read

EVENTS = (("2006 event", "HD2006-05-29_2dstack.mseed", "tab:green"),
          ("2015 event", "HD2015-05-24_2dstack.mseed", "tab:red"))
# pro7 selects R index 4 and T index 5 on an 11-by-11 beam grid for PKIKP.
BEAM_INDEX = 4 * 11 + 5


def trace(path: Path):
    stream = read(path)
    stack_trace = stream[BEAM_INDEX]
    data = np.asarray(stack_trace.data, dtype=float)
    data /= np.max(np.abs(data))
    return np.arange(data.size) * stack_trace.stats.delta - 50.0, data


def absolute_trace(path: Path, reference_origin):
    """Return a trace on a shared absolute-clock axis, in seconds."""
    stack_trace = read(path)[BEAM_INDEX]
    data = np.asarray(stack_trace.data, dtype=float)
    data /= np.max(np.abs(data))
    time = np.arange(data.size) * stack_trace.stats.delta + (stack_trace.stats.starttime - reference_origin)
    return time, data


def plot_case(axis, root: Path, case: str, mode: str, title: str) -> None:
    folder = root / "cases" / case / mode / "intermediate"
    for label, filename, color in EVENTS:
        time, data = trace(folder / filename)
        axis.plot(time, data, color=color, linewidth=1.0, label=label)
    axis.axhline(0, color="0.7", linewidth=0.7)
    axis.axvline(0, color="0.5", linewidth=0.7)
    axis.set(xlim=(-20, 30), ylim=(-1.1, 1.1), title=title,
             xlabel="Time relative to the explicit event reference (s)")
    axis.grid(alpha=0.2)


def plot_difference(axis, same_root: Path, relative_root: Path, mode: str, title: str) -> None:
    """Plot relative-location minus same-location beam stacks for each event."""
    for label, filename, color in EVENTS:
        time, same = trace(same_root / "cases" / "without_relative_offset" / mode / "intermediate" / filename)
        _, relative = trace(relative_root / "cases" / "with_relative_offset" / mode / "intermediate" / filename)
        axis.plot(time, relative - same, color=color, linewidth=1.0, label=label)
    axis.axhline(0, color="0.3", linewidth=0.7)
    axis.axvline(0, color="0.5", linewidth=0.7)
    axis.set(xlim=(-20, 30), ylim=(-0.25, 0.25), title=title,
             xlabel="Time relative to the explicit event reference (s)")
    axis.grid(alpha=0.2)


def plot_absolute_clock(same_root: Path, relative_root: Path, output: Path) -> None:
    """Compare each event case on its actual MSEED clock, not its own origin frame."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), sharex=True, constrained_layout=True)
    for row, (mode, array) in enumerate((("yka_40s", "YKA"), ("ilar_40s", "ILAR"))):
        for col, (label, filename, color) in enumerate(EVENTS):
            same_path = same_root / "cases" / "without_relative_offset" / mode / "intermediate" / filename
            relative_path = relative_root / "cases" / "with_relative_offset" / mode / "intermediate" / filename
            same_trace = read(same_path)[BEAM_INDEX]
            reference_origin = same_trace.stats.starttime + 50.0
            time, same = absolute_trace(same_path, reference_origin)
            relative_time, relative = absolute_trace(relative_path, reference_origin)
            relative_on_clock = np.interp(time, relative_time, relative)
            axis = axes[row, col]
            axis.plot(time, same, color="0.15", linewidth=1.0, label="coincident source")
            axis.plot(time, relative_on_clock, color=color, linewidth=1.0, alpha=0.8, label="separated source")
            axis.plot(time, relative_on_clock - same, color="tab:blue", linewidth=0.8, label="difference")
            axis.axhline(0, color="0.7", linewidth=0.7)
            axis.axvline(0, color="0.5", linewidth=0.7)
            axis.set(xlim=(-20, 30), ylim=(-1.1, 1.1), title=f"{array}: {label}",
                     xlabel="Seconds from coincident-case origin, using actual MSEED timestamps")
            axis.grid(alpha=0.2)
    axes[0, 0].set_ylabel("Normalized beam-stack amplitude")
    axes[1, 0].set_ylabel("Normalized beam-stack amplitude")
    axes[0, 0].legend(loc="upper right")
    fig.suptitle("P38 location sensitivity on the common absolute clock\nDifference is separated minus coincident; no origin-relative frame change")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def plot_pair_differences(same_root: Path, relative_root: Path, output: Path) -> None:
    """Show pair differences after registering both cases on the MSEED clock."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 8), sharex=True, constrained_layout=True)
    for row, (mode, array) in enumerate((("yka_40s", "YKA"), ("ilar_40s", "ILAR"))):
        def case_path(root: Path, case: str, filename: str) -> Path:
            return root / "cases" / case / mode / "intermediate" / filename

        same_2006_path = case_path(same_root, "without_relative_offset", EVENTS[0][1])
        same_2015_path = case_path(same_root, "without_relative_offset", EVENTS[1][1])
        relative_2006_path = case_path(relative_root, "with_relative_offset", EVENTS[0][1])
        relative_2015_path = case_path(relative_root, "with_relative_offset", EVENTS[1][1])
        reference_2006 = read(same_2006_path)[BEAM_INDEX].stats.starttime + 50.0
        reference_2015 = read(same_2015_path)[BEAM_INDEX].stats.starttime + 50.0
        time, same_2006 = absolute_trace(same_2006_path, reference_2006)
        _, same_2015 = absolute_trace(same_2015_path, reference_2015)
        relative_time_2006, relative_2006_raw = absolute_trace(relative_2006_path, reference_2006)
        relative_time_2015, relative_2015_raw = absolute_trace(relative_2015_path, reference_2015)
        relative_2006 = np.interp(time, relative_time_2006, relative_2006_raw)
        relative_2015 = np.interp(time, relative_time_2015, relative_2015_raw)
        coincident_difference = same_2015 - same_2006
        separated_difference = relative_2015 - relative_2006
        location_effect = separated_difference - coincident_difference
        series = (
            (coincident_difference, "2015 minus 2006: coincident sources", "tab:purple", (-1.5, 1.5)),
            (separated_difference, "2015 minus 2006: distinct sources", "tab:orange", (-1.5, 1.5)),
            (location_effect, "Distinct-source difference minus coincident-source difference", "tab:blue", (-0.25, 0.25)),
        )
        for column, (data, title, color, ylim) in enumerate(series):
            axis = axes[row, column]
            axis.plot(time, data, color=color, linewidth=1.0)
            axis.axhline(0, color="0.3", linewidth=0.7)
            axis.axvline(0, color="0.5", linewidth=0.7)
            axis.set(xlim=(-20, 30), ylim=ylim, title=f"{array}: {title}",
                     xlabel="Seconds from fixed coincident-case origin, using actual MSEED timestamps")
            axis.grid(alpha=0.2)
    axes[0, 0].set_ylabel("Normalized beam-stack difference")
    axes[1, 0].set_ylabel("Normalized beam-stack difference")
    fig.suptitle("P38 PKIKP event-pair differences on the common absolute clock\nEach event normalized independently; source cases registered by actual MSEED timestamps")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("same_root", type=Path); p.add_argument("relative_yka_root", type=Path)
    p.add_argument("relative_ilar_root", type=Path); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--absolute-clock-output", type=Path)
    p.add_argument("--pair-difference-output", type=Path)
    args = p.parse_args()
    fig, axes = plt.subplots(2, 3, figsize=(18, 8), sharex=True, constrained_layout=True)
    for row, (mode, relative_root, array) in enumerate((("yka_40s", args.relative_yka_root, "YKA"), ("ilar_40s", args.relative_ilar_root, "ILAR"))):
        plot_case(axes[row, 0], args.same_root, "without_relative_offset", mode, f"{array}: same location")
        plot_case(axes[row, 1], relative_root, "with_relative_offset", mode, f"{array}: relative location")
        plot_difference(axes[row, 2], args.same_root, relative_root, mode, f"{array}: relative minus same")
    axes[0, 0].legend(loc="upper right")
    axes[0, 0].set_ylabel("Normalized beam-stack amplitude")
    axes[1, 0].set_ylabel("Normalized beam-stack amplitude")
    fig.suptitle("P38 PKIKP beam-stack superposition at requested PKIKP slowness\nEach event normalized independently; no post-stack cross-correlation shift")
    args.output.parent.mkdir(parents=True, exist_ok=True); fig.savefig(args.output, dpi=200); plt.close(fig)
    if args.absolute_clock_output:
        if args.relative_yka_root != args.relative_ilar_root:
            raise ValueError("The common-clock plot requires one relative-location root for both arrays")
        plot_absolute_clock(args.same_root, args.relative_yka_root, args.absolute_clock_output)
    if args.pair_difference_output:
        if args.relative_yka_root != args.relative_ilar_root:
            raise ValueError("The pair-difference plot requires one relative-location root for both arrays")
        plot_pair_differences(args.same_root, args.relative_yka_root, args.pair_difference_output)


if __name__ == "__main__": main()
