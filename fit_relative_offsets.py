from __future__ import annotations

import argparse
import csv
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
from obspy.taup import TauPyModel
from scipy.optimize import differential_evolution, minimize

import compare_repeater_pwaves as base


EARTH_KM_PER_DEGREE = 111.195
NO_PKIKP_PHASES = {"P", "PcP", "ScP", "PKP"}
WITH_PKIKP_PHASES = {"P", "PcP", "ScP", "PKP", "PKiKP"}
PREFERRED_PHASE_SET = "no_pkikp"
PHASE_SETS = {
    "no_pkikp": NO_PKIKP_PHASES,
    "with_pkikp": WITH_PKIKP_PHASES,
    "p_only": {"P"},
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def normalized_header(row: tuple[Any, ...]) -> dict[str, int]:
    return {
        str(value).strip().lower(): index
        for index, value in enumerate(row)
        if value is not None and str(value).strip()
    }


def load_new_pair_locations(workbook_path: Path) -> dict[str, tuple[float, float]]:
    """Read optional pair-sheet new_lat/new_lon reference locations."""
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["pairs"]
        rows = sheet.iter_rows(values_only=True)
        header = normalized_header(next(rows))
        required = {"label", "new_lat", "new_lon"}
        if not required.issubset(header):
            return {}
        overrides: dict[str, tuple[float, float]] = {}
        for row in rows:
            label_value = row[header["label"]]
            if label_value is None:
                continue
            latitude = finite_float(row[header["new_lat"]])
            longitude = finite_float(row[header["new_lon"]])
            if latitude is None or longitude is None:
                continue
            overrides[str(label_value).strip()] = (latitude, longitude)
        return overrides
    finally:
        workbook.close()


def apply_pair_location_override(
    pair: base.Pair, latitude: float, longitude: float
) -> base.Pair:
    event1 = replace(
        pair.event1,
        latitude=latitude,
        longitude=longitude,
        depth_km=pair.depth_km,
    )
    event2 = replace(
        pair.event2,
        latitude=latitude,
        longitude=longitude,
        depth_km=pair.depth_km,
    )
    return replace(
        pair,
        event1=event1,
        event2=event2,
        latitude=latitude,
        longitude=longitude,
    )


def shifted_event(
    event: base.Event, east_km: float, north_km: float, depth_km: float
) -> base.Event:
    latitude = float(event.latitude)
    longitude = float(event.longitude)
    cosine_latitude = max(0.05, math.cos(math.radians(latitude)))
    return replace(
        event,
        latitude=latitude + north_km / EARTH_KM_PER_DEGREE,
        longitude=longitude + east_km / (EARTH_KM_PER_DEGREE * cosine_latitude),
        depth_km=max(0.0, float(event.depth_km) + depth_km),
    )


def location_delta(
    latitude: float, longitude: float, east_km: float, north_km: float
) -> tuple[float, float]:
    cosine_latitude = max(0.05, math.cos(math.radians(latitude)))
    return (
        north_km / EARTH_KM_PER_DEGREE,
        east_km / (EARTH_KM_PER_DEGREE * cosine_latitude),
    )


def travel_time(
    model: TauPyModel,
    event: base.Event,
    station_latitude: float,
    station_longitude: float,
    phase: str,
) -> float:
    distance = float(
        base.locations2degrees(
            event.latitude, event.longitude, station_latitude, station_longitude
        )
    )
    arrivals = model.get_travel_times(
        source_depth_in_km=float(event.depth_km),
        distance_in_degree=distance,
        phase_list=[phase],
    )
    exact = [arrival for arrival in arrivals if arrival.name == phase]
    if exact:
        arrivals = exact
    if not arrivals:
        return math.nan
    return float(arrivals[0].time)


def travel_time_gradient(
    model: TauPyModel,
    event: base.Event,
    row: dict[str, str],
    step_km: float,
) -> list[float] | None:
    phase = row["phase"]
    station_latitude = float(row["station_latitude"])
    station_longitude = float(row["station_longitude"])
    gradient: list[float] = []
    for east, north, depth in (
        (step_km, 0.0, 0.0),
        (0.0, step_km, 0.0),
        (0.0, 0.0, step_km),
    ):
        positive = shifted_event(event, east, north, depth)
        negative = shifted_event(event, -east, -north, -depth)
        positive_time = travel_time(
            model, positive, station_latitude, station_longitude, phase
        )
        negative_time = travel_time(
            model, negative, station_latitude, station_longitude, phase
        )
        if not (math.isfinite(positive_time) and math.isfinite(negative_time)):
            return None
        gradient.append((positive_time - negative_time) / (2.0 * step_km))
    return gradient


def fit_median_absolute(gradients: np.ndarray, residuals: np.ndarray) -> np.ndarray:
    bounds = [(-5.0, 5.0), (-5.0, 5.0), (-5.0, 5.0)]

    def objective(offset_km: np.ndarray) -> float:
        fit_residuals = residuals - gradients @ np.asarray(offset_km, dtype=float)
        return float(np.median(np.abs(fit_residuals)))

    global_result = differential_evolution(
        objective,
        bounds=bounds,
        seed=20260813,
        polish=False,
        tol=1e-8,
        updating="immediate",
        workers=1,
    )
    polished = minimize(
        objective,
        global_result.x,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 2000, "ftol": 1e-12},
    )
    if objective(polished.x) <= objective(global_result.x):
        return np.asarray(polished.x, dtype=float)
    return np.asarray(global_result.x, dtype=float)


def fit_offsets(config_path: Path, output: Path, step_km: float) -> None:
    config = base.load_json(config_path)
    model = TauPyModel(model=str(config["taup_model"]))
    pair_labels = [str(label) for label in config["pairs"]]
    catalog_workbook_path = Path(config.get("time_shift_workbook") or config["catalog_path"])
    pairs = base.resolve_catalog(
        catalog_workbook_path,
        pair_labels,
        float(config["coordinate_tolerance_degrees"]),
        float(config["coordinate_tolerance_depth_km"]),
    )
    location_overrides = {}
    if catalog_workbook_path:
        location_overrides = load_new_pair_locations(catalog_workbook_path)
        pairs = {
            label: apply_pair_location_override(pair, *location_overrides[label])
            if label in location_overrides
            else pair
            for label, pair in pairs.items()
        }
    rows = [
        row
        for row in read_csv(output / "phase_measurements.csv")
        if truthy(row.get("good"))
    ]
    median_shifts = {
        row["pair_label"]: float(row["pair_median_shift_seconds"])
        for row in read_csv(output / "median_summary.csv")
        if row.get("pair_median_shift_seconds")
    }

    summary_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for pair_label in pair_labels:
        pair = pairs[pair_label]
        pair_rows = [row for row in rows if row["pair_label"] == pair_label]
        for phase_set, allowed_phases in PHASE_SETS.items():
            selected_rows = [
                row
                for row in pair_rows
                if allowed_phases is None or row["phase"] in allowed_phases
            ]
            gradients: list[list[float]] = []
            residuals: list[float] = []
            total_shifts: list[float] = []
            used_rows: list[dict[str, str]] = []
            for row in selected_rows:
                gradient = travel_time_gradient(model, pair.event2, row, step_km)
                if gradient is None:
                    continue
                if pair_label not in median_shifts:
                    continue
                total_shift = float(row["total_shift_seconds"])
                residual = total_shift - median_shifts[pair_label]
                gradients.append(gradient)
                residuals.append(residual)
                total_shifts.append(total_shift)
                used_rows.append(row)

            count = len(residuals)
            common = {
                "pair_label": pair_label,
                "event1": pair.event1.event_id,
                "event2": pair.event2.event_id,
                "phase_set": phase_set,
                "method": "median_absolute_finite_difference",
                "common_lat": pair.latitude,
                "common_lon": pair.longitude,
                "common_depth_km": pair.depth_km,
                "common_location_source": "new_lat_new_lon"
                if pair_label in location_overrides
                else "catalog_path",
                "n": count,
            }
            if count < 4:
                summary_rows.append(
                    {
                        **common,
                        "median_shift_seconds": "",
                        "east_km": "",
                        "north_km": "",
                        "depth_diff_km": "",
                        "delta_lat_degrees": "",
                        "delta_lon_degrees": "",
                        "event1_lat": "",
                        "event1_lon": "",
                        "event1_depth_km": "",
                        "event1_origin_time_shift_s": "",
                        "event2_lat": "",
                        "event2_lon": "",
                        "event2_depth_km": "",
                        "event2_origin_time_shift_s": "",
                        "event2_minus_event1_origin_time_shift_s": "",
                        "horizontal_km": "",
                        "separation_3d_km": "",
                        "median_abs_fit_residual_s": "",
                        "residual_rms_s": "",
                    }
                )
                continue

            gradient_array = np.asarray(gradients, dtype=float)
            residual_array = np.asarray(residuals, dtype=float)
            total_shift_array = np.asarray(total_shifts, dtype=float)
            offset = fit_median_absolute(gradient_array, residual_array)
            predicted = gradient_array @ offset
            fit_residuals = residual_array - predicted
            east, north, depth = [float(value) for value in offset]
            delta_lat, delta_lon = location_delta(pair.latitude, pair.longitude, east, north)
            event1_lat = pair.latitude - 0.5 * delta_lat
            event1_lon = pair.longitude - 0.5 * delta_lon
            event1_depth = pair.depth_km - 0.5 * depth
            event2_lat = pair.latitude + 0.5 * delta_lat
            event2_lon = pair.longitude + 0.5 * delta_lon
            event2_depth = pair.depth_km + 0.5 * depth
            origin_shift = float(np.median(total_shift_array - predicted))
            horizontal = math.hypot(east, north)
            separation = math.sqrt(east * east + north * north + depth * depth)
            summary_rows.append(
                {
                    **common,
                    "median_shift_seconds": median_shifts[pair_label],
                    "east_km": east,
                    "north_km": north,
                    "depth_diff_km": depth,
                    "delta_lat_degrees": delta_lat,
                    "delta_lon_degrees": delta_lon,
                    "event1_lat": event1_lat,
                    "event1_lon": event1_lon,
                    "event1_depth_km": event1_depth,
                    "event1_origin_time_shift_s": -0.5 * origin_shift,
                    "event2_lat": event2_lat,
                    "event2_lon": event2_lon,
                    "event2_depth_km": event2_depth,
                    "event2_origin_time_shift_s": 0.5 * origin_shift,
                    "event2_minus_event1_origin_time_shift_s": origin_shift,
                    "horizontal_km": horizontal,
                    "separation_3d_km": separation,
                    "median_abs_fit_residual_s": float(
                        np.median(np.abs(fit_residuals))
                    ),
                    "residual_rms_s": float(
                        np.sqrt(np.mean(fit_residuals * fit_residuals))
                    ),
                }
            )
            for row, predicted_shift, fit_residual in zip(
                used_rows, predicted, fit_residuals
            ):
                prediction_rows.append(
                    {
                        "pair_label": pair_label,
                        "station_id": row["station_id"],
                        "phase": row["phase"],
                        "phase_set": phase_set,
                        "observed_residual_shift_s": float(
                            row["total_shift_seconds"]
                        )
                        - median_shifts[pair_label],
                        "predicted_location_shift_s": float(predicted_shift),
                        "event2_minus_event1_origin_time_shift_s": origin_shift,
                        "predicted_total_shift_s": origin_shift
                        + float(predicted_shift),
                        "fit_residual_s": float(fit_residual),
                        "cc": float(row["cc"]),
                        "azimuth_degrees": float(row["azimuth_degrees"]),
                        "takeoff_angle_degrees": float(
                            row["takeoff_angle_degrees"]
                        ),
                        "epicentral_distance_degrees": float(
                            row["epicentral_distance_degrees"]
                        ),
                    }
                )

    write_csv(output / "relative_location_offsets_from_median_residuals.csv", summary_rows)
    write_csv(output / "relative_location_offset_predictions.csv", prediction_rows)
    preferred_rows = [
        row for row in summary_rows if row["phase_set"] == PREFERRED_PHASE_SET
    ]
    write_csv(
        output / "median_absolute_relative_locations.csv",
        [
            {
                "pair": row["pair_label"],
                "event1": row["event1"],
                "event2": row["event2"],
                "n": row["n"],
                "east_km": row["east_km"],
                "north_km": row["north_km"],
                "depth_diff_km": row["depth_diff_km"],
                "delta_lat_degrees": row["delta_lat_degrees"],
                "delta_lon_degrees": row["delta_lon_degrees"],
                "event1_lat": row["event1_lat"],
                "event1_lon": row["event1_lon"],
                "event1_depth_km": row["event1_depth_km"],
                "event1_origin_time_shift_s": row["event1_origin_time_shift_s"],
                "event2_lat": row["event2_lat"],
                "event2_lon": row["event2_lon"],
                "event2_depth_km": row["event2_depth_km"],
                "event2_origin_time_shift_s": row["event2_origin_time_shift_s"],
                "event2_minus_event1_origin_time_shift_s": row[
                    "event2_minus_event1_origin_time_shift_s"
                ],
                "horizontal_km": row["horizontal_km"],
                "separation_3d_km": row["separation_3d_km"],
                "median_abs_fit_residual_s": row["median_abs_fit_residual_s"],
                "residual_rms_s": row["residual_rms_s"],
            }
            for row in preferred_rows
        ],
    )
    for phase_set in ("no_pkikp", "with_pkikp", "p_only"):
        phase_rows = [row for row in summary_rows if row["phase_set"] == phase_set]
        write_csv(
            output / f"median_absolute_relative_locations_{phase_set}.csv",
            [
                {
                    "pair": row["pair_label"],
                    "event1": row["event1"],
                    "event2": row["event2"],
                    "phase_set": row["phase_set"],
                    "n": row["n"],
                    "east_km": row["east_km"],
                    "north_km": row["north_km"],
                    "depth_diff_km": row["depth_diff_km"],
                    "delta_lat_degrees": row["delta_lat_degrees"],
                    "delta_lon_degrees": row["delta_lon_degrees"],
                    "event1_lat": row["event1_lat"],
                    "event1_lon": row["event1_lon"],
                    "event1_depth_km": row["event1_depth_km"],
                    "event1_origin_time_shift_s": row[
                        "event1_origin_time_shift_s"
                    ],
                    "event2_lat": row["event2_lat"],
                    "event2_lon": row["event2_lon"],
                    "event2_depth_km": row["event2_depth_km"],
                    "event2_origin_time_shift_s": row[
                        "event2_origin_time_shift_s"
                    ],
                    "event2_minus_event1_origin_time_shift_s": row[
                        "event2_minus_event1_origin_time_shift_s"
                    ],
                    "horizontal_km": row["horizontal_km"],
                    "separation_3d_km": row["separation_3d_km"],
                    "median_abs_fit_residual_s": row["median_abs_fit_residual_s"],
                    "residual_rms_s": row["residual_rms_s"],
                }
                for row in phase_rows
            ],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path("analysis_config.json"))
    parser.add_argument("--step-km", type=float, default=0.2)
    args = parser.parse_args()
    fit_offsets(args.config, args.output, args.step_km)
    print(args.output / "median_absolute_relative_locations.csv")
    print(args.output / "relative_location_offsets_from_median_residuals.csv")
    print(args.output / "relative_location_offset_predictions.csv")


if __name__ == "__main__":
    main()
