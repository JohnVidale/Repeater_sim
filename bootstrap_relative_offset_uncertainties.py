#!/usr/bin/env python3
"""Bootstrap median relative-location offsets from phase residual measurements."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np
from obspy.taup import TauPyModel
from scipy.optimize import minimize

import compare_repeater_pwaves as base
import fit_relative_offsets as offsets


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def local_fit_median_absolute(
    gradients: np.ndarray, residuals: np.ndarray, start: np.ndarray
) -> np.ndarray:
    bounds = [(-5.0, 5.0), (-5.0, 5.0), (-5.0, 5.0)]

    def objective(offset_km: np.ndarray) -> float:
        fit_residuals = residuals - gradients @ np.asarray(offset_km, dtype=float)
        return float(np.median(np.abs(fit_residuals)))

    result = minimize(
        objective,
        start,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 300, "ftol": 1e-10},
    )
    if result.success or objective(result.x) <= objective(start):
        return np.asarray(result.x, dtype=float)
    return np.asarray(start, dtype=float)


def bootstrap_uncertainty(
    gradients: np.ndarray,
    residuals: np.ndarray,
    total_shifts: np.ndarray,
    best_offset: np.ndarray,
    iterations: int,
    rng: np.random.Generator,
) -> dict[str, float]:
    n = len(residuals)
    offsets_boot = np.empty((iterations, 3), dtype=float)
    origin_shifts = np.empty(iterations, dtype=float)
    for index in range(iterations):
        sample = rng.integers(0, n, size=n)
        offsets_boot[index] = local_fit_median_absolute(
            gradients[sample], residuals[sample], best_offset
        )
        origin_shifts[index] = float(
            np.median(total_shifts[sample] - gradients[sample] @ offsets_boot[index])
        )
    separations = np.sqrt(np.sum(offsets_boot * offsets_boot, axis=1))
    horizontal = np.sqrt(offsets_boot[:, 0] ** 2 + offsets_boot[:, 1] ** 2)
    lower, median, upper = np.percentile(separations, [16.0, 50.0, 84.0])
    horizontal_lower, horizontal_median, horizontal_upper = np.percentile(
        horizontal, [16.0, 50.0, 84.0]
    )
    return {
        "east_sigma_km": float(np.std(offsets_boot[:, 0], ddof=1)),
        "north_sigma_km": float(np.std(offsets_boot[:, 1], ddof=1)),
        "depth_sigma_km": float(np.std(offsets_boot[:, 2], ddof=1)),
        "horizontal_p16_km": float(horizontal_lower),
        "horizontal_p50_km": float(horizontal_median),
        "horizontal_p84_km": float(horizontal_upper),
        "separation_3d_p16_km": float(lower),
        "separation_3d_p50_km": float(median),
        "separation_3d_p84_km": float(upper),
        "separation_3d_minus_sigma_km": float(median - lower),
        "separation_3d_plus_sigma_km": float(upper - median),
        "event2_minus_event1_origin_time_shift_p16_s": float(
            np.percentile(origin_shifts, 16.0)
        ),
        "event2_minus_event1_origin_time_shift_p50_s": float(
            np.percentile(origin_shifts, 50.0)
        ),
        "event2_minus_event1_origin_time_shift_p84_s": float(
            np.percentile(origin_shifts, 84.0)
        ),
        "event2_minus_event1_origin_time_shift_sigma_s": float(
            np.std(origin_shifts, ddof=1)
        ),
    }


def run(
    config_path: Path,
    output: Path,
    iterations: int,
    step_km: float,
    seed: int,
    phase_set: str,
) -> Path:
    if phase_set not in offsets.PHASE_SETS or offsets.PHASE_SETS[phase_set] is None:
        raise ValueError(
            f"phase_set must be one of: "
            f"{', '.join(name for name, phases in offsets.PHASE_SETS.items() if phases is not None)}"
        )
    allowed_phases = offsets.PHASE_SETS[phase_set]
    config = base.load_json(config_path)
    model = TauPyModel(model=str(config["taup_model"]))
    pair_labels = [str(label) for label in config["pairs"]]
    catalog_path = Path(config.get("time_shift_workbook") or config["catalog_path"])
    pairs = base.resolve_catalog(
        catalog_path,
        pair_labels,
        float(config["coordinate_tolerance_degrees"]),
        float(config["coordinate_tolerance_depth_km"]),
    )
    location_overrides = offsets.load_new_pair_locations(catalog_path)
    pairs = {
        label: offsets.apply_pair_location_override(pair, *location_overrides[label])
        if label in location_overrides
        else pair
        for label, pair in pairs.items()
    }
    rows = [
        row
        for row in read_csv(output / "phase_measurements.csv")
        if offsets.truthy(row.get("good"))
    ]
    median_shifts = {
        row["pair_label"]: float(row["pair_median_shift_seconds"])
        for row in read_csv(output / "median_summary.csv")
        if row.get("pair_median_shift_seconds")
    }
    best_offsets = {
        row["pair"]: np.asarray(
            [
                float(row["east_km"]),
                float(row["north_km"]),
                float(row["depth_diff_km"]),
            ],
            dtype=float,
        )
        for row in read_csv(output / f"median_absolute_relative_locations_{phase_set}.csv")
        if row.get("east_km")
    }

    rng = np.random.default_rng(seed)
    summary_rows: list[dict[str, Any]] = []
    for pair_label in pair_labels:
        pair = pairs[pair_label]
        gradients: list[list[float]] = []
        residuals: list[float] = []
        total_shifts: list[float] = []
        for row in rows:
            if row["pair_label"] != pair_label:
                continue
            if row["phase"] not in allowed_phases:
                continue
            if pair_label not in median_shifts:
                continue
            gradient = offsets.travel_time_gradient(model, pair.event2, row, step_km)
            if gradient is None:
                continue
            gradients.append(gradient)
            total_shift = float(row["total_shift_seconds"])
            residuals.append(total_shift - median_shifts[pair_label])
            total_shifts.append(total_shift)
        gradient_array = np.asarray(gradients, dtype=float)
        residual_array = np.asarray(residuals, dtype=float)
        total_shift_array = np.asarray(total_shifts, dtype=float)
        if pair_label not in best_offsets or len(residuals) < 4:
            summary_rows.append(
                {
                    "pair": pair_label,
                    "event1": pair.event1.event_id,
                    "event2": pair.event2.event_id,
                    "n": len(residuals),
                    "status": f"insufficient_{phase_set}_measurements",
                    "location_reference": "new_lat_new_lon"
                    if pair_label in location_overrides
                    else "catalog_path",
                    "phase_set": phase_set,
                    "bootstrap_iterations": iterations,
                }
            )
            continue
        best_offset = best_offsets[pair_label]
        fit_residuals = residual_array - gradient_array @ best_offset
        origin_shift = float(np.median(total_shift_array - gradient_array @ best_offset))
        separation = float(math.sqrt(np.sum(best_offset * best_offset)))
        horizontal = float(math.hypot(best_offset[0], best_offset[1]))
        uncertainty = bootstrap_uncertainty(
            gradient_array,
            residual_array,
            total_shift_array,
            best_offset,
            iterations,
            rng,
        )
        summary_rows.append(
            {
                "pair": pair_label,
                "event1": pair.event1.event_id,
                "event2": pair.event2.event_id,
                "n": len(residuals),
                "east_km": float(best_offset[0]),
                "north_km": float(best_offset[1]),
                "depth_diff_km": float(best_offset[2]),
                "event2_minus_event1_origin_time_shift_s": origin_shift,
                "horizontal_km": horizontal,
                "separation_3d_km": separation,
                **uncertainty,
                "median_abs_fit_residual_s": float(np.median(np.abs(fit_residuals))),
                "residual_rms_s": float(np.sqrt(np.mean(fit_residuals * fit_residuals))),
                "bootstrap_iterations": iterations,
                "location_reference": "new_lat_new_lon"
                if pair_label in location_overrides
                else "catalog_path",
                "phase_set": phase_set,
            }
        )

    destination = (
        output
        / f"median_relative_location_offsets_{phase_set}_with_bootstrap_uncertainty.csv"
    )
    write_csv(destination, summary_rows)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path("analysis_config.json"))
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--step-km", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument(
        "--phase-set",
        choices=[
            name for name, phases in offsets.PHASE_SETS.items() if phases is not None
        ],
        default=offsets.PREFERRED_PHASE_SET,
    )
    args = parser.parse_args()
    print(
        run(
            args.config,
            args.output,
            args.iterations,
            args.step_km,
            args.seed,
            args.phase_set,
        )
    )


if __name__ == "__main__":
    main()
