#!/usr/bin/env python3
"""Plot phase-residual distributions by station-acceptance status."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr


PHASE_ORDER = ("P", "PcP", "ScP", "PKiKP", "PKP")
STATUS_ORDER = ("A", "R", "X", "B")
STATUS_COLORS = {
    "A": "#1f77b4",  # accepted
    "R": "#7f7f7f",  # automatic rejection
    "X": "#d62728",  # manual exclusion
    "B": "#e377c2",  # anomalous but well-defined shift
}
PHASE_COLORS = {
    "P": "#1f77b4",
    "PcP": "#ff7f0e",
    "ScP": "#2ca02c",
    "PKiKP": "#d62728",
    "PKP": "#9467bd",
}


def status(row: dict[str, str]) -> str:
    manual = str(row.get("manual_status") or "").strip().upper()
    if manual in {"X", "B"}:
        return manual
    return "A" if str(row.get("good") or "").strip().lower() == "true" else "R"


def read_values(
    path: Path, field: str
) -> dict[str, dict[str, list[float]]]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            phase = str(row.get("phase") or "").strip()
            if phase not in PHASE_ORDER:
                continue
            try:
                residual = float(row[field])
            except (KeyError, TypeError, ValueError):
                continue
            values[phase][status(row)].append(residual)
    return values


def gaussian_l1_ecdf_fit(samples: np.ndarray) -> tuple[float, float]:
    """Fit Gaussian location and scale by L1 distance to the empirical CDF."""
    ordered = np.sort(np.asarray(samples, dtype=float))
    if len(ordered) < 2:
        return float(ordered[0]), 0.0
    empirical_cdf = (np.arange(len(ordered), dtype=float) + 0.5) / len(ordered)
    median = float(np.median(ordered))
    iqr = float(np.percentile(ordered, 75.0) - np.percentile(ordered, 25.0))
    initial_sigma = iqr / 1.3489795003921634
    if initial_sigma <= 0.0:
        initial_sigma = float(np.std(ordered, ddof=1))
    span = max(float(ordered[-1] - ordered[0]), 1.0e-4)
    initial_sigma = max(initial_sigma, span / 100.0, 1.0e-6)

    def objective(parameters: np.ndarray) -> float:
        mean, sigma = parameters
        model_cdf = ndtr((ordered - mean) / sigma)
        return float(np.mean(np.abs(empirical_cdf - model_cdf)))

    result = minimize(
        objective,
        np.asarray([median, initial_sigma]),
        method="Powell",
        bounds=[
            (float(ordered[0] - span), float(ordered[-1] + span)),
            (1.0e-6, 10.0 * span),
        ],
    )
    mean, sigma = result.x if result.success else (median, initial_sigma)
    return float(mean), float(sigma)


def plot(
    measurements: Path,
    output: Path,
    quantity: str,
    normalization: str,
    x_limits: tuple[float, float] | None = None,
    bin_count: int = 40,
) -> None:
    residual_limits = x_limits or (-0.5, 0.5)
    field, bins, xlabel, title = (
        (
            "pair_residual_seconds",
            np.linspace(*residual_limits, bin_count + 1),
            "Differential time, pair residual (s)",
            "Differential-time residual distributions by acceptance status",
        )
        if quantity == "residual"
        else (
            "epicentral_distance_degrees",
            np.linspace(0, 180, 37),
            "Epicentral distance (degrees)",
            "Epicentral-distance distributions by acceptance status",
        )
    )
    use_density = normalization == "density"
    values = read_values(measurements, field)
    figure, axes = plt.subplots(2, 3, figsize=(13, 7.5), sharex=True, sharey=False, constrained_layout=True)
    for axis, phase in zip(axes.flat, PHASE_ORDER):
        for state in STATUS_ORDER:
            samples = values[phase].get(state, [])
            if not samples:
                continue
            axis.hist(
                samples,
                bins=bins,
                density=use_density,
                histtype="step",
                linewidth=1.6,
                color=STATUS_COLORS[state],
                label=f"{state} (n={len(samples)})",
            )
        if quantity == "residual":
            axis.axvline(0, color="0.35", linewidth=0.8)
        axis.set_title(phase)
        axis.grid(axis="y", color="0.9", linewidth=0.7)
        axis.legend(fontsize=8, frameon=False, loc="upper left")
    axes.flat[-1].set_visible(False)
    for axis in axes[1, :2]:
        axis.set_xlabel(xlabel)
    for axis in axes[:, 0]:
        axis.set_ylabel("Probability density" if use_density else "Measurement count")
    figure.suptitle(
        f"{title}\n"
        "A = accepted; R = automatic rejection; X = manual exclusion; B = anomalous shift"
    )
    figure.savefig(output.with_suffix(".png"), dpi=220)
    figure.savefig(output.with_suffix(".pdf"))
    plt.close(figure)


def plot_accepted_overlay(
    measurements: Path,
    output: Path,
    x_limits: tuple[float, float] | None = None,
    bin_count: int = 40,
    gaussian_fit: bool = False,
    gaussian_fit_mode: str = "moment",
) -> None:
    """Plot accepted measurements from every phase in one count-normalized panel."""
    histogram_limits = x_limits or (-0.5, 0.5)
    bins = np.linspace(*histogram_limits, bin_count + 1)
    bin_width = bins[1] - bins[0]
    values = read_values(measurements, "pair_residual_seconds")
    figure, (axis, fit_axis) = plt.subplots(
        2, 1, figsize=(10, 8), sharex=True, constrained_layout=True
    )
    for phase in PHASE_ORDER:
        samples = values[phase].get("A", [])
        if not samples:
            continue
        sample_values = np.asarray(samples, dtype=float)
        if gaussian_fit and gaussian_fit_mode == "l1_ecdf":
            mean, std = gaussian_l1_ecdf_fit(sample_values)
            method_label = "L1-CDF"
        else:
            mean = float(np.mean(sample_values))
            std = float(np.std(sample_values, ddof=1)) if len(sample_values) > 1 else 0.0
            method_label = "moment"
        axis.hist(
            sample_values,
            bins=bins,
            histtype="step",
            linewidth=1.8,
            color=PHASE_COLORS[phase],
            label=(
                f"{phase} (A; n={len(samples)}, {method_label} "
                f"μ={mean:+.3f}, σ={std:.3f} s)"
            ),
        )
        if gaussian_fit and std > 0.0:
            x_values = np.linspace(*histogram_limits, 500)
            normalized_gaussian = np.exp(-0.5 * ((x_values - mean) / std) ** 2)
            fit_axis.plot(
                x_values,
                normalized_gaussian,
                color=PHASE_COLORS[phase],
                linewidth=1.8,
                label=f"{phase} ({method_label} σ={std:.3f} s)",
            )
    axis.axvline(0, color="0.35", linewidth=0.8)
    axis.grid(axis="y", color="0.9", linewidth=0.7)
    axis.set_ylabel("Measurement count")
    axis.set_title("Accepted differential-time residuals by phase")
    if x_limits is not None:
        axis.set_xlim(*x_limits)
    axis.legend(frameon=False, loc="upper left")
    fit_axis.axvline(0, color="0.35", linewidth=0.8)
    fit_axis.grid(axis="y", color="0.9", linewidth=0.7)
    fit_axis.set_xlabel("Differential time, pair residual (s)")
    fit_axis.set_ylabel("Gaussian amplitude\n(normalized peak = 1)")
    fit_axis.set_ylim(0, 1.08)
    fit_axis.set_title(
        "L1 empirical-CDF Gaussian fits at common peak amplitude"
        if gaussian_fit_mode == "l1_ecdf"
        else "Moment Gaussian fits at common peak amplitude"
    )
    if x_limits is not None:
        fit_axis.set_xlim(*x_limits)
    if gaussian_fit:
        fit_axis.legend(frameon=False, loc="upper left")
    figure.savefig(output.with_suffix(".png"), dpi=220)
    figure.savefig(output.with_suffix(".pdf"))
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quantity", choices=("residual", "distance"), default="residual")
    parser.add_argument(
        "--normalization",
        choices=("density", "count"),
        default="density",
        help="Use separately normalized densities or raw measurement counts.",
    )
    parser.add_argument(
        "--x-limits",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="Horizontal limits for differential-time plots.",
    )
    parser.add_argument(
        "--bins",
        type=int,
        default=40,
        help="Number of bins for --accepted-overlay (default: 40).",
    )
    parser.add_argument(
        "--gaussian-fit",
        action="store_true",
        help="Overlay count-scaled Gaussian fits for --accepted-overlay.",
    )
    parser.add_argument(
        "--gaussian-fit-mode",
        choices=("moment", "l1_ecdf"),
        default="moment",
        help="Estimate Gaussian parameters from moments or by L1 empirical-CDF fit.",
    )
    parser.add_argument(
        "--accepted-overlay",
        action="store_true",
        help="Plot only accepted measurements, with all phases overlaid in one panel.",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.accepted_overlay:
        x_limits = tuple(args.x_limits) if args.x_limits is not None else None
        plot_accepted_overlay(
            args.measurements,
            args.output,
            x_limits,
            args.bins,
            args.gaussian_fit,
            args.gaussian_fit_mode,
        )
    else:
        x_limits = tuple(args.x_limits) if args.x_limits is not None else None
        plot(
            args.measurements,
            args.output,
            args.quantity,
            args.normalization,
            x_limits,
            args.bins,
        )
    print(args.output.with_suffix(".png"))
    print(args.output.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
