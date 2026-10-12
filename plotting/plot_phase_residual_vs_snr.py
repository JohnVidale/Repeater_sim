#!/usr/bin/env python3
"""Plot accepted differential-time residuals against trace-pair SNR by phase."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt


PHASE_ORDER = ("P", "PcP", "ScP", "PKiKP", "PKP")
PHASE_COLORS = {
    "P": "#1f77b4",
    "PcP": "#ff7f0e",
    "ScP": "#2ca02c",
    "PKiKP": "#d62728",
    "PKP": "#9467bd",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    values = {phase: ([], []) for phase in PHASE_ORDER}
    with args.measurements.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            phase = str(row.get("phase") or "").strip()
            if phase not in values or str(row.get("good") or "").lower() != "true":
                continue
            try:
                snr = min(
                    float(row["automatic_pick1_snr"]),
                    float(row["automatic_pick2_snr"]),
                )
                residual = float(row["pair_residual_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(snr) and snr > 0.0 and math.isfinite(residual):
                values[phase][0].append(math.log10(snr))
                values[phase][1].append(abs(residual))

    figure, axis = plt.subplots(figsize=(10, 6.5), constrained_layout=True)
    for phase in PHASE_ORDER:
        snrs, residuals = values[phase]
        if not snrs:
            continue
        axis.scatter(
            snrs,
            residuals,
            s=34,
            alpha=0.72,
            color=PHASE_COLORS[phase],
            edgecolor="none",
            label=f"{phase} (n={len(snrs)})",
        )
    axis.grid(True, alpha=0.28)
    axis.set_xlabel("log10(lower SNR of the two event traces)")
    axis.set_ylabel("Absolute differential travel-time residual (s)")
    axis.set_title("Accepted absolute travel-time residual versus log10 SNR")
    axis.legend(title="Phase", frameon=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=220)
    print(args.output)
    print(", ".join(f"{phase}={len(values[phase][0])}" for phase in PHASE_ORDER))


if __name__ == "__main__":
    main()
