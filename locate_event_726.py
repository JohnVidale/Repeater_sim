#!/usr/bin/env python3
"""Pick teleseismic P arrivals for event 726 and estimate its hypocenter."""

from __future__ import annotations

import csv
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
from obspy import UTCDateTime, read
from obspy.geodetics import gps2dist_azimuth, locations2degrees
from obspy.signal.trigger import aic_simple
from obspy.taup import TauPyModel
from scipy.optimize import least_squares


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "analysis_config.json"
OUTPUT = (
    ROOT
    / "outputs"
    / "019fe3df-32a0-70c0-a5c4-a6cbf8a5b62f"
    / "event_726_hypocenter"
)
EVENT_ID = 726
FILTER_HZ = (0.7, 4.0)
SEARCH_SECONDS = (-6.0, 8.0)
MIN_DISTANCE_DEGREES = 15.0
MAX_DISTANCE_DEGREES = 98.0
MIN_SNR = 2.5
CONSTRAINED_DEPTH_KM = 55.6


@dataclass
class Pick:
    station_id: str
    path: Path
    station_latitude: float
    station_longitude: float
    distance_degrees: float
    predicted_epoch: float
    pick_epoch: float
    pick_offset_seconds: float
    snr: float
    uncertainty_seconds: float
    aic_edge_margin_seconds: float
    sac_t0_seconds: float | None
    trace_start_epoch: float
    sampling_hz: float
    waveform_times: np.ndarray
    waveform: np.ndarray
    accepted: bool
    rejection_reason: str


def normalized_header(row):
    return {
        str(value).strip().lower(): index
        for index, value in enumerate(row)
        if value is not None and str(value).strip()
    }


def load_event() -> tuple[UTCDateTime, float, float, float, Path]:
    config = json.loads(CONFIG_PATH.read_text())
    catalog_path = Path(config["catalog_path"])
    workbook = openpyxl.load_workbook(catalog_path, read_only=True, data_only=True)
    try:
        sheet = workbook["events"]
        rows = sheet.iter_rows(values_only=True)
        header = normalized_header(next(rows))
        for row in rows:
            if int(row[header["index"]]) != EVENT_ID:
                continue
            origin = UTCDateTime(str(row[header["time"]]))
            latitude = float(row[header["lat_best"]])
            longitude = float(row[header["lon_best"]])
            depth_km = float(row[header["depth_best"]])
            waveform_root = Path(config["waveform_root"])
            key = origin.strftime("%Y%m%d_%H%M%S")
            event_dir = waveform_root / key
            if not event_dir.is_dir():
                matches = sorted(waveform_root.glob(f"{key}*"))
                if len(matches) != 1:
                    raise RuntimeError(f"Could not resolve waveform directory for {EVENT_ID}")
                event_dir = matches[0]
            return origin, latitude, longitude, depth_km, event_dir
    finally:
        workbook.close()
    raise RuntimeError(f"Event {EVENT_ID} not found")


def direct_p_time(
    model: TauPyModel,
    latitude: float,
    longitude: float,
    depth_km: float,
    station_latitude: float,
    station_longitude: float,
) -> tuple[float, float] | None:
    distance = float(
        locations2degrees(
            latitude, longitude, station_latitude, station_longitude
        )
    )
    arrivals = model.get_travel_times(
        source_depth_in_km=float(depth_km),
        distance_in_degree=distance,
        phase_list=["P"],
    )
    if not arrivals:
        return None
    return float(arrivals[0].time), distance


def uncertainty_from_snr(snr: float) -> float:
    if snr >= 10.0:
        return 0.20
    if snr >= 6.0:
        return 0.35
    if snr >= 4.0:
        return 0.55
    return 0.85


def pick_trace(
    path: Path,
    model: TauPyModel,
    origin: UTCDateTime,
    latitude: float,
    longitude: float,
    depth_km: float,
) -> Pick | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        trace = read(str(path))[0]
    if str(trace.stats.channel).upper() != "BHZ":
        return None
    sac = trace.stats.sac
    try:
        station_latitude = float(sac.stla)
        station_longitude = float(sac.stlo)
    except (AttributeError, TypeError, ValueError):
        return None
    prediction = direct_p_time(
        model,
        latitude,
        longitude,
        depth_km,
        station_latitude,
        station_longitude,
    )
    if prediction is None:
        return None
    travel_time, distance_degrees = prediction
    if not MIN_DISTANCE_DEGREES <= distance_degrees <= MAX_DISTANCE_DEGREES:
        return None
    predicted_epoch = float(origin) + travel_time

    processed = trace.copy()
    processed.detrend("demean")
    processed.detrend("linear")
    processed.taper(max_percentage=0.05, max_length=2.0, type="cosine")
    processed.filter(
        "bandpass",
        freqmin=FILTER_HZ[0],
        freqmax=FILTER_HZ[1],
        corners=4,
        zerophase=True,
    )
    fs = float(processed.stats.sampling_rate)
    start_epoch = float(processed.stats.starttime)
    data = np.asarray(processed.data, dtype=float)
    relative = start_epoch + np.arange(len(data)) / fs - predicted_epoch
    window_mask = (relative >= SEARCH_SECONDS[0]) & (relative < SEARCH_SECONDS[1])
    indices = np.flatnonzero(window_mask)
    if len(indices) < int(8.0 * fs):
        return None
    segment = data[indices]
    characteristic = np.asarray(aic_simple(segment), dtype=float)
    edge = max(1, int(round(0.5 * fs)))
    interior = characteristic[edge:-edge]
    if not len(interior) or not np.any(np.isfinite(interior)):
        return None
    local_index = edge + int(np.nanargmin(interior))
    pick_index = int(indices[local_index])
    pick_epoch = start_epoch + pick_index / fs
    pick_offset = pick_epoch - predicted_epoch
    edge_margin = min(
        pick_offset - SEARCH_SECONDS[0], SEARCH_SECONDS[1] - pick_offset
    )

    pick_relative = start_epoch + np.arange(len(data)) / fs - pick_epoch
    noise = data[(pick_relative >= -8.0) & (pick_relative < -2.0)]
    signal = data[(pick_relative >= 0.0) & (pick_relative < 4.0)]
    if len(noise) < int(3.0 * fs) or len(signal) < int(2.0 * fs):
        return None
    noise_rms = float(np.sqrt(np.mean(np.square(noise))))
    signal_rms = float(np.sqrt(np.mean(np.square(signal))))
    snr = signal_rms / noise_rms if noise_rms > 0.0 else math.inf
    reasons = []
    if snr < MIN_SNR:
        reasons.append(f"snr<{MIN_SNR:g}")
    if edge_margin < 0.75:
        reasons.append("pick_near_search_edge")
    if abs(pick_offset) > 5.5:
        reasons.append("pick_offset>5.5s")
    sac_t0 = getattr(sac, "t0", None)
    if sac_t0 is not None:
        sac_t0 = float(sac_t0)
        if not math.isfinite(sac_t0) or abs(sac_t0 + 12345.0) < 1.0:
            sac_t0 = None
    station_id = f"{trace.stats.network}.{trace.stats.station}"
    plot_mask = (pick_relative >= -12.0) & (pick_relative < 18.0)
    plot_waveform = data[plot_mask]
    scale = float(np.max(np.abs(plot_waveform))) if len(plot_waveform) else 0.0
    if scale > 0.0:
        plot_waveform = plot_waveform / scale
    return Pick(
        station_id=station_id,
        path=path,
        station_latitude=station_latitude,
        station_longitude=station_longitude,
        distance_degrees=distance_degrees,
        predicted_epoch=predicted_epoch,
        pick_epoch=pick_epoch,
        pick_offset_seconds=pick_offset,
        snr=snr,
        uncertainty_seconds=uncertainty_from_snr(snr),
        aic_edge_margin_seconds=edge_margin,
        sac_t0_seconds=sac_t0,
        trace_start_epoch=start_epoch,
        sampling_hz=fs,
        waveform_times=pick_relative[plot_mask],
        waveform=plot_waveform,
        accepted=not reasons,
        rejection_reason=";".join(reasons),
    )


def travel_times(
    model: TauPyModel,
    picks: list[Pick],
    latitude: float,
    longitude: float,
    depth_km: float,
) -> np.ndarray:
    values = []
    for pick in picks:
        prediction = direct_p_time(
            model,
            latitude,
            longitude,
            depth_km,
            pick.station_latitude,
            pick.station_longitude,
        )
        if prediction is None:
            values.append(np.nan)
        else:
            values.append(prediction[0])
    return np.asarray(values, dtype=float)


def fit_location(
    model: TauPyModel,
    picks: list[Pick],
    initial: tuple[float, float, float, float],
    fixed_depth_km: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    origin_reference = initial[3]
    observed_relative = np.asarray(
        [pick.pick_epoch - origin_reference for pick in picks], dtype=float
    )
    weights = np.asarray([pick.uncertainty_seconds for pick in picks], dtype=float)

    if fixed_depth_km is None:
        x0 = np.asarray([initial[0], initial[1], initial[2], 0.0], dtype=float)
        lower = np.asarray([-60.0, -31.0, 0.1, -20.0])
        upper = np.asarray([-53.0, -23.0, 150.0, 20.0])

        def unpack(x):
            return float(x[0]), float(x[1]), float(x[2]), float(x[3])

    else:
        x0 = np.asarray([initial[0], initial[1], 0.0], dtype=float)
        lower = np.asarray([-60.0, -31.0, -20.0])
        upper = np.asarray([-53.0, -23.0, 20.0])

        def unpack(x):
            return float(x[0]), float(x[1]), float(fixed_depth_km), float(x[2])

    def residuals(x):
        latitude, longitude, depth_km, origin_offset = unpack(x)
        predicted = travel_times(model, picks, latitude, longitude, depth_km)
        residual = observed_relative - (origin_offset + predicted)
        residual[~np.isfinite(residual)] = 1000.0
        return residual / weights

    solution = least_squares(
        residuals,
        x0,
        bounds=(lower, upper),
        loss="soft_l1",
        f_scale=2.0,
        max_nfev=150,
        xtol=1e-7,
        ftol=1e-7,
        gtol=1e-7,
    )
    latitude, longitude, depth_km, origin_offset = unpack(solution.x)
    origin_epoch = origin_reference + origin_offset
    predicted_relative = origin_offset + travel_times(
        model, picks, latitude, longitude, depth_km
    )
    residual = observed_relative - predicted_relative
    dof = max(1, len(picks) - len(solution.x))
    weighted_variance = float(np.sum(np.square(residuals(solution.x))) / dof)
    covariance = np.linalg.pinv(solution.jac.T @ solution.jac) * weighted_variance
    parameter_sigma = np.sqrt(np.maximum(0.0, np.diag(covariance)))
    return (
        np.asarray([latitude, longitude, depth_km, origin_epoch]),
        residual,
        parameter_sigma,
        solution.x,
    )


def robust_fit(
    model: TauPyModel,
    picks: list[Pick],
    initial: tuple[float, float, float, float],
    fixed_depth_km: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[Pick], list[Pick]]:
    kept = list(picks)
    removed: list[Pick] = []
    for _ in range(4):
        solution, residual, sigma, _ = fit_location(
            model, kept, initial, fixed_depth_km
        )
        center = float(np.median(residual))
        mad = float(np.median(np.abs(residual - center)))
        threshold = max(2.0, 3.5 * 1.4826 * mad)
        bad = np.abs(residual - center) > threshold
        if not np.any(bad) or len(kept) - int(np.sum(bad)) < 12:
            return solution, residual, sigma, kept, removed
        removed.extend([pick for pick, reject in zip(kept, bad) if reject])
        kept = [pick for pick, reject in zip(kept, bad) if not reject]
    solution, residual, sigma, _ = fit_location(
        model, kept, initial, fixed_depth_km
    )
    return solution, residual, sigma, kept, removed


def location_summary(
    name: str,
    solution: np.ndarray,
    residual: np.ndarray,
    sigma: np.ndarray,
    picks: list[Pick],
    removed: list[Pick],
) -> dict:
    latitude, longitude, depth_km, origin_epoch = map(float, solution)
    return {
        "solution": name,
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "depth_km": depth_km,
        "origin_time_utc": str(UTCDateTime(origin_epoch)),
        "picks_used": len(picks),
        "location_outliers_removed": len(removed),
        "residual_rms_seconds": float(np.sqrt(np.mean(np.square(residual)))),
        "residual_median_seconds": float(np.median(residual)),
        "residual_mad_seconds": float(
            np.median(np.abs(residual - np.median(residual)))
        ),
        "formal_parameter_sigma": sigma.tolist(),
    }


def jackknife_fixed_depth(
    model: TauPyModel,
    picks: list[Pick],
    solution: np.ndarray,
) -> tuple[dict, np.ndarray]:
    initial = tuple(map(float, solution))
    locations = []
    for omitted in range(len(picks)):
        subset = [pick for index, pick in enumerate(picks) if index != omitted]
        jackknife_solution, _, _, _ = fit_location(
            model, subset, initial, CONSTRAINED_DEPTH_KM
        )
        locations.append(jackknife_solution)
    array = np.asarray(locations, dtype=float)
    horizontal_km = np.asarray(
        [
            gps2dist_azimuth(solution[0], solution[1], row[0], row[1])[0] / 1000.0
            for row in array
        ]
    )
    azimuths = sorted(
        gps2dist_azimuth(
            solution[0],
            solution[1],
            pick.station_latitude,
            pick.station_longitude,
        )[1]
        for pick in picks
    )
    gaps = [
        (azimuths[(index + 1) % len(azimuths)] - azimuths[index]) % 360.0
        for index in range(len(azimuths))
    ]
    summary = {
        "replicates": len(array),
        "latitude_std_deg": float(np.std(array[:, 0], ddof=1)),
        "longitude_std_deg": float(np.std(array[:, 1], ddof=1)),
        "origin_time_std_seconds": float(np.std(array[:, 3], ddof=1)),
        "horizontal_shift_median_km": float(np.median(horizontal_km)),
        "horizontal_shift_max_km": float(np.max(horizontal_km)),
        "maximum_station_azimuth_gap_deg": float(max(gaps)),
    }
    return summary, array


def write_pick_table(
    picks: list[Pick],
    fixed_solution: np.ndarray,
    fixed_kept: list[Pick],
    model: TauPyModel,
) -> None:
    kept_ids = {id(pick) for pick in fixed_kept}
    latitude, longitude, depth_km, origin_epoch = map(float, fixed_solution)
    residual_by_id = {}
    for pick, travel_time in zip(
        fixed_kept,
        travel_times(model, fixed_kept, latitude, longitude, depth_km),
    ):
        residual_by_id[id(pick)] = pick.pick_epoch - (origin_epoch + travel_time)
    fields = [
        "station_id",
        "station_latitude",
        "station_longitude",
        "distance_degrees_initial",
        "pick_time_utc",
        "pick_offset_from_initial_prediction_seconds",
        "snr",
        "pick_uncertainty_seconds",
        "sac_t0_seconds_from_catalog_origin",
        "picker_accepted",
        "used_in_fixed_depth_location",
        "fixed_depth_residual_seconds",
        "rejection_reason",
        "waveform_path",
    ]
    with (OUTPUT / "event_726_p_picks.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pick in sorted(picks, key=lambda item: item.distance_degrees):
            writer.writerow(
                {
                    "station_id": pick.station_id,
                    "station_latitude": pick.station_latitude,
                    "station_longitude": pick.station_longitude,
                    "distance_degrees_initial": pick.distance_degrees,
                    "pick_time_utc": str(UTCDateTime(pick.pick_epoch)),
                    "pick_offset_from_initial_prediction_seconds": pick.pick_offset_seconds,
                    "snr": pick.snr,
                    "pick_uncertainty_seconds": pick.uncertainty_seconds,
                    "sac_t0_seconds_from_catalog_origin": pick.sac_t0_seconds,
                    "picker_accepted": pick.accepted,
                    "used_in_fixed_depth_location": id(pick) in kept_ids,
                    "fixed_depth_residual_seconds": residual_by_id.get(id(pick)),
                    "rejection_reason": pick.rejection_reason,
                    "waveform_path": str(pick.path),
                }
            )


def plot_record_section(picks: list[Pick]) -> None:
    accepted = sorted(
        [pick for pick in picks if pick.accepted], key=lambda item: item.distance_degrees
    )
    figure, axis = plt.subplots(figsize=(12, max(8, 0.16 * len(accepted))))
    for row, pick in enumerate(accepted):
        axis.plot(pick.waveform_times, pick.waveform + row, color="black", linewidth=0.45)
        axis.plot(0.0, row, marker="|", color="red", markersize=6)
        axis.text(18.2, row, f"{pick.station_id} {pick.distance_degrees:.1f}°", fontsize=5, va="center")
    axis.axvline(0.0, color="red", linewidth=0.8, label="automatic P pick")
    axis.set_xlim(-12.0, 24.0)
    axis.set_ylim(-1.0, len(accepted) + 1.0)
    axis.set_xlabel("Time relative to automatic P pick (s)")
    axis.set_ylabel("Accepted traces, sorted by epicentral distance")
    axis.set_title(f"Event {EVENT_ID}: accepted 0.7–4 Hz BHZ P picks")
    axis.set_yticks([])
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    figure.savefig(OUTPUT / "event_726_p_pick_record_section.png", dpi=180)
    plt.close(figure)


def plot_residuals(picks: list[Pick], residual: np.ndarray) -> None:
    figure, (axis1, axis2) = plt.subplots(1, 2, figsize=(12, 5))
    distances = np.asarray([pick.distance_degrees for pick in picks])
    snrs = np.asarray([pick.snr for pick in picks])
    scatter = axis1.scatter(distances, residual, c=np.log10(snrs), cmap="viridis", s=24)
    axis1.axhline(0.0, color="black", linewidth=0.8)
    axis1.set_xlabel("Epicentral distance (deg)")
    axis1.set_ylabel("Observed minus calculated P (s)")
    axis1.set_title("Fixed-depth location residuals")
    figure.colorbar(scatter, ax=axis1, label="log10(SNR)")
    axis2.hist(residual, bins=18, color="#4C78A8", edgecolor="white")
    axis2.axvline(0.0, color="black", linewidth=0.8)
    axis2.set_xlabel("Observed minus calculated P (s)")
    axis2.set_ylabel("Stations")
    axis2.set_title("Residual distribution")
    figure.tight_layout()
    figure.savefig(OUTPUT / "event_726_location_residuals.png", dpi=180)
    plt.close(figure)


def plot_jackknife(solution: np.ndarray, jackknife: np.ndarray) -> None:
    figure, axis = plt.subplots(figsize=(6.5, 6.0))
    axis.scatter(
        jackknife[:, 1],
        jackknife[:, 0],
        color="#4C78A8",
        alpha=0.75,
        label="leave-one-station-out",
    )
    axis.scatter(
        solution[1],
        solution[0],
        marker="*",
        s=180,
        color="#E45756",
        edgecolor="black",
        linewidth=0.5,
        label="all accepted picks",
    )
    axis.set_xlabel("Longitude (deg)")
    axis.set_ylabel("Latitude (deg)")
    axis.set_title("Event 726 fixed-depth location stability")
    axis.grid(alpha=0.25)
    axis.legend()
    axis.set_aspect(1.0 / max(0.2, math.cos(math.radians(solution[0]))))
    figure.tight_layout()
    figure.savefig(OUTPUT / "event_726_location_jackknife.png", dpi=180)
    plt.close(figure)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    origin, initial_lat, initial_lon, initial_depth, event_dir = load_event()
    model = TauPyModel("ak135")
    picks = []
    for path in sorted(event_dir.glob("*.sac")):
        pick = pick_trace(
            path, model, origin, initial_lat, initial_lon, initial_depth
        )
        if pick is not None:
            picks.append(pick)
    accepted = [pick for pick in picks if pick.accepted]
    if len(accepted) < 15:
        raise RuntimeError(f"Only {len(accepted)} automatic picks passed QC")

    initial = (initial_lat, initial_lon, initial_depth, float(origin))
    fixed = robust_fit(model, accepted, initial, CONSTRAINED_DEPTH_KM)
    free = robust_fit(model, accepted, initial, None)
    fixed_solution, fixed_residual, fixed_sigma, fixed_kept, fixed_removed = fixed
    free_solution, free_residual, free_sigma, free_kept, free_removed = free
    jackknife_summary, jackknife_locations = jackknife_fixed_depth(
        model, fixed_kept, fixed_solution
    )
    summary = {
        "event_id": EVENT_ID,
        "method": {
            "phase": "direct P",
            "taup_model": "ak135",
            "filter_hz": FILTER_HZ,
            "picker": "AIC minimum in predicted-P search window",
            "search_seconds_relative_to_initial_prediction": SEARCH_SECONDS,
            "minimum_snr": MIN_SNR,
            "distance_range_degrees": [MIN_DISTANCE_DEGREES, MAX_DISTANCE_DEGREES],
            "location_loss": "soft_l1",
            "outlier_rule": "max(2.0 s, 3.5 scaled MAD)",
        },
        "initial_common_location": {
            "latitude_deg": initial_lat,
            "longitude_deg": initial_lon,
            "depth_km": initial_depth,
            "origin_time_utc": str(origin),
        },
        "waveform_records": len(list(event_dir.glob("*.sac"))),
        "eligible_direct_p_records": len(picks),
        "automatic_picks_passing_qc": len(accepted),
        "fixed_depth_solution": location_summary(
            f"depth fixed at {CONSTRAINED_DEPTH_KM:.1f} km",
            fixed_solution,
            fixed_residual,
            fixed_sigma,
            fixed_kept,
            fixed_removed,
        ),
        "free_depth_solution": location_summary(
            "depth free",
            free_solution,
            free_residual,
            free_sigma,
            free_kept,
            free_removed,
        ),
        "fixed_depth_leave_one_out": jackknife_summary,
        "cautions": [
            "These are automatic single-component picks and require visual review before catalog adoption.",
            "The 1-D ak135 model does not represent station/path corrections.",
            "Teleseismic direct-P times have a strong depth-origin-time tradeoff; prefer the constrained-depth solution for interpretation.",
        ],
    }
    (OUTPUT / "event_726_hypocenter_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    write_pick_table(picks, fixed_solution, fixed_kept, model)
    plot_record_section(picks)
    plot_residuals(fixed_kept, fixed_residual)
    plot_jackknife(fixed_solution, jackknife_locations)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
