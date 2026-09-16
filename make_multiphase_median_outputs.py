from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import time
import warnings
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from obspy import read
from obspy.signal.trigger import aic_simple
from obspy.taup import TauPyModel

import compare_repeater_pwaves as base


PHASES = ("P", "PKiKP", "PKP")
# Retain compatibility with historical workbook rows.
WORKBOOK_PHASES = (*PHASES, "Pdiff")
MARKED_PHASES = (
    "P",
    "pP",
    "sP",
    "PP",
    "PKP",
    "sPKP",
    "pPKP",
    "PKiKP",
    "sPKiKP",
    "pPKiKP",
    "PKIKP",
    "sPKIKP",
    "pPKIKP",
)
PHASE_MARKERS = {"P": "o", "PKiKP": "D", "PKP": "P"}
PROGRESS_STATION_INTERVAL = 10
AUTOMATIC_PICK_FILTER_HZ = (0.7, 4.0)
AUTOMATIC_PICK_SEARCH_SECONDS = (-6.0, 8.0)
AUTOMATIC_PICK_MIN_SNR = 0.5
AUTOMATIC_PICK_NOISE_WINDOW_SECONDS = (-30.0, -10.0)
AUTOMATIC_PICK_SIGNAL_WINDOW_SECONDS = (0.0, 4.0)
AUTOMATIC_PICK_MAX_OFFSET_SECONDS = 5.5
ORIGIN_ALIGNMENT_MIN_SNR = 5.0
PKIKP_MIN_DISTANCE_DEGREES = 110.0


def phase_is_usable_for_shift(phase: str, distance_degrees: float) -> bool:
    """Return whether this phase/station geometry should enter shift summaries."""
    if phase not in PHASES:
        return False
    if phase == "PKiKP":
        return distance_degrees >= PKIKP_MIN_DISTANCE_DEGREES
    return True


def phase_correlation_windows(config: dict[str, Any]) -> dict[str, list[float]]:
    """Use the configured correlation window consistently for every phase."""
    window = [float(value) for value in config["correlation_window_seconds"]]
    return {phase: list(window) for phase in PHASES}


def phase_plot_windows(config: dict[str, Any]) -> dict[str, list[float]]:
    """Use the configured plot window consistently for every phase."""
    window = [float(value) for value in config["plot_window_seconds"]]
    return {phase: list(window) for phase in PHASES}


def phase_shift_summary_y_limits(config: dict[str, Any]) -> tuple[float, float]:
    """Return validated lower and upper limits for phase-shift summaries."""
    limits = tuple(
        float(value)
        for value in config.get("phase_shift_summary_ylim_seconds", [-0.2, 0.2])
    )
    if len(limits) != 2 or limits[0] >= limits[1]:
        raise base.AnalysisError(
            "phase_shift_summary_ylim_seconds must contain increasing limits"
        )
    return limits


def excluded_station_codes_for_pair(
    config: dict[str, Any], pair_label: str
) -> set[str]:
    """Return global and pair-specific stations excluded from solutions."""
    excluded = set(base.excluded_station_codes(config))
    pair_values = config.get("excluded_stations_by_pair", {}).get(pair_label, [])
    excluded.update(
        str(value).strip().upper().split(".")[-1]
        for value in pair_values
        if str(value).strip()
    )
    return excluded


def read_workbook_pair_column(
    workbook_path: Path, column_name: str
) -> dict[str, float]:
    """Read finite numeric values keyed by pair label from the pairs sheet."""
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["pairs"]
        rows = sheet.iter_rows(values_only=True)
        headers = {
            str(value).strip().lower(): index
            for index, value in enumerate(next(rows))
            if value is not None
        }
        normalized_column_name = column_name.strip().lower()
        if "label" not in headers or normalized_column_name not in headers:
            raise base.AnalysisError(
                f"Workbook pairs sheet must contain 'label' and {column_name!r} columns"
            )
        label_index = headers["label"]
        shift_index = headers[normalized_column_name]
        shifts: dict[str, float] = {}
        for row in rows:
            label = row[label_index] if label_index < len(row) else None
            value = row[shift_index] if shift_index < len(row) else None
            if label is None or value is None or str(value).strip() == "":
                continue
            parsed = finite_float(value)
            if parsed is None:
                raise base.AnalysisError(
                    f"Workbook {column_name!r} value for {label!s} is not finite numeric data"
                )
            shifts[str(label).strip()] = parsed
        return shifts
    finally:
        workbook.close()


def read_workbook_time_shifts(workbook_path: Path) -> dict[str, float]:
    return read_workbook_pair_column(workbook_path, "new time shift")


def read_manual_pick_alignment_shifts(
    workbook_path: Path,
) -> dict[tuple[str, str, str], float]:
    """Read pair/station/phase display shifts from a station-status workbook."""
    if not workbook_path.is_file():
        raise base.AnalysisError(
            f"Manual pick-alignment workbook does not exist: {workbook_path}"
        )
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        if "Station status" not in workbook.sheetnames:
            raise base.AnalysisError(
                "Manual pick-alignment workbook must contain a 'Station status' sheet"
            )
        sheet = workbook["Station status"]
        rows = sheet.iter_rows(values_only=True)
        header: dict[str, int] | None = None
        header_row: tuple[Any, ...] | None = None
        for row in rows:
            normalized = {
                str(value).strip().lower(): index
                for index, value in enumerate(row)
                if value is not None and str(value).strip()
            }
            if "station" in normalized and "metric" in normalized:
                header = normalized
                header_row = row
                break
        if header is None or header_row is None:
            raise base.AnalysisError(
                "Manual pick-alignment workbook must contain Station and Metric headers"
            )
        station_index = header["station"]
        metric_index = header["metric"]
        pair_columns = {
            index: str(value).strip()
            for index, value in enumerate(header_row)
            if index not in {station_index, metric_index}
            and value is not None
            and str(value).strip()
        }
        shifts: dict[tuple[str, str, str], float] = {}
        current_station_phase: str | None = None
        for row in rows:
            station_phase_value = (
                row[station_index] if station_index < len(row) else None
            )
            if station_phase_value is not None and str(station_phase_value).strip():
                current_station_phase = str(station_phase_value).strip()
            metric = row[metric_index] if metric_index < len(row) else None
            if (
                current_station_phase is None
                or str(metric).strip().lower()
                != "manual pick alignment shift (s)"
            ):
                continue
            parts = current_station_phase.rsplit(maxsplit=1)
            if len(parts) != 2 or parts[1] not in WORKBOOK_PHASES:
                raise base.AnalysisError(
                    "Invalid station-phase label for manual shift row: "
                    f"{current_station_phase}"
                )
            station_id, phase = parts
            for index, pair_label in pair_columns.items():
                value = row[index] if index < len(row) else None
                if value is None or str(value).strip() == "":
                    continue
                parsed = finite_float(value)
                if parsed is None:
                    raise base.AnalysisError(
                        "Manual pick-alignment shift must be finite numeric data: "
                        f"{pair_label} {station_id} {phase}"
                    )
                key = (pair_label, station_id, phase)
                if key in shifts:
                    raise base.AnalysisError(
                        "Duplicate manual pick-alignment shift: "
                        f"{pair_label} {station_id} {phase}"
                    )
                shifts[key] = parsed
        return shifts
    finally:
        workbook.close()


def read_workbook_manual_exclusions(
    workbook_path: Path,
) -> set[tuple[str, str, str]]:
    """Read phase-specific X statuses from the station acceptance workbook."""
    if not workbook_path.is_file():
        raise base.AnalysisError(
            f"Station acceptance workbook does not exist: {workbook_path}"
        )
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        if "Station status" not in workbook.sheetnames:
            raise base.AnalysisError(
                "Station acceptance workbook must contain a 'Station status' sheet"
            )
        sheet = workbook["Station status"]
        rows = sheet.iter_rows(values_only=True)
        header: dict[str, int] | None = None
        header_row: tuple[Any, ...] | None = None
        for row in rows:
            normalized = {
                str(value).strip().lower(): index
                for index, value in enumerate(row)
                if value is not None and str(value).strip()
            }
            if "station" in normalized and "metric" in normalized:
                header = normalized
                header_row = row
                break
        if header is None or header_row is None:
            raise base.AnalysisError(
                "Station acceptance workbook must contain Station and Metric headers"
            )
        station_index = header["station"]
        metric_index = header["metric"]
        pair_columns = {
            index: str(value).strip()
            for index, value in enumerate(header_row)
            if index not in {station_index, metric_index}
            and value is not None
            and str(value).strip()
        }
        exclusions: set[tuple[str, str, str]] = set()
        for row in rows:
            station_phase = row[station_index] if station_index < len(row) else None
            metric = row[metric_index] if metric_index < len(row) else None
            if station_phase is None or str(metric).strip().lower() != "status":
                continue
            parts = str(station_phase).strip().rsplit(maxsplit=1)
            if len(parts) != 2 or parts[1] not in WORKBOOK_PHASES:
                raise base.AnalysisError(
                    f"Invalid station-phase label in status row: {station_phase!s}"
                )
            station_id, phase = parts
            for index, pair_label in pair_columns.items():
                value = row[index] if index < len(row) else None
                if value is not None and str(value).strip().upper() == "X":
                    exclusions.add((pair_label, station_id, phase))
        return exclusions
    finally:
        workbook.close()


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def pair_consistent_reference_shift(
    rows: list[dict[str, Any]], minimum_count: int = 1
) -> float:
    """Return the median shift from reliable first-pass measurements."""
    shifts = [
        float(row["total_shift_seconds"])
        for row in rows
        if row.get("good") and finite_float(row.get("total_shift_seconds")) is not None
    ]
    if len(shifts) < minimum_count:
        return math.nan
    return float(np.median(shifts))


def l1_p_waveform_alignment_shift(
    rows: list[dict[str, Any]], minimum_count: int = 1
) -> float:
    """Return the L1 inter-event alignment from accepted P differential times."""
    shifts = [
        float(row["total_shift_seconds"])
        for row in rows
        if row.get("phase") == "P"
        and row.get("good")
        and finite_float(row.get("total_shift_seconds")) is not None
    ]
    if len(shifts) < minimum_count:
        return math.nan
    return float(np.median(shifts))


def l1_common_high_snr_p_origin_shift(
    rows: list[dict[str, Any]],
    waveform_alignment_shift_seconds: float,
    minimum_snr: float,
    minimum_count: int = 1,
) -> tuple[float, int]:
    """Fit one common post-alignment shift to high-SNR AIC P onsets."""
    residuals: list[float] = []
    for row in rows:
        if row.get("phase") != "P":
            continue
        if row.get("manual_excluded"):
            continue
        for event_number, preapplied_shift in (
            (1, 0.0),
            (2, waveform_alignment_shift_seconds),
        ):
            accepted_key = f"automatic_pick{event_number}_accepted"
            offset_key = f"automatic_pick{event_number}_offset_s"
            snr_key = f"automatic_pick{event_number}_snr"
            offset = finite_float(row.get(offset_key))
            snr = finite_float(row.get(snr_key))
            if row.get(accepted_key) and offset is not None and snr is not None:
                if snr >= minimum_snr:
                    residuals.append(offset - preapplied_shift)
    if len(residuals) < minimum_count:
        return math.nan, len(residuals)
    return float(np.median(residuals)), len(residuals)


def absolute_plot_pick_times(
    row: dict[str, Any], waveform_alignment_shift_seconds: float,
    common_origin_shift_seconds: float,
) -> tuple[float | None, float | None]:
    """Place corrected-reference AIC picks on the final plot time axis."""
    common_shift_after_aic = (
        0.0
        if row.get("aic_reference_includes_common_origin_shift", False)
        else float(common_origin_shift_seconds)
    )
    pick1 = (
        float(row["automatic_pick1_offset_s"]) - common_shift_after_aic
        if row.get("automatic_pick1_accepted")
        and row.get("automatic_pick1_offset_s") is not None
        else None
    )
    pick2 = (
        float(row["automatic_pick2_offset_s"])
        - waveform_alignment_shift_seconds
        - common_shift_after_aic
        if row.get("automatic_pick2_accepted")
        and row.get("automatic_pick2_offset_s") is not None
        else None
    )
    return pick1, pick2


def manually_shifted_phase_arrivals(
    arrival1: float, arrival2: float, manual_shift_seconds: float
) -> tuple[float, float]:
    """Apply one station/phase reference correction equally to both events."""
    return (
        float(arrival1) + float(manual_shift_seconds),
        float(arrival2) + float(manual_shift_seconds),
    )


def measurement_phase_arrivals(
    arrival1: float,
    arrival2: float,
    common_origin_shift_seconds: float,
    manual_shift_seconds: float,
) -> tuple[float, float]:
    """Return phase references after pair-wide and station/phase corrections."""
    return manually_shifted_phase_arrivals(
        float(arrival1) + float(common_origin_shift_seconds),
        float(arrival2) + float(common_origin_shift_seconds),
        manual_shift_seconds,
    )


def aic_offsets_required_for_correlation(time_shift_source: str) -> bool:
    """Return whether initial correlation centers depend on individual AIC picks."""
    return time_shift_source not in {"workbook", "none"}


def picks_meet_minimum_snr(
    pick1_snr: float | None,
    pick2_snr: float | None,
    minimum_snr: float,
) -> bool:
    """Apply the SNR criterion independently of AIC timing-offset acceptance."""
    first = finite_float(pick1_snr)
    second = finite_float(pick2_snr)
    return bool(
        first is not None
        and second is not None
        and first >= minimum_snr
        and second >= minimum_snr
    )


def eligible_for_pair_consistent_refinement(
    row: dict[str, Any], time_shift_source: str
) -> bool:
    """Return whether a row should be pair-aligned for measurement or display."""
    return time_shift_source in {"computed", "picked"}


def passes_picked_mode_aic_qc(row: dict[str, Any]) -> bool:
    """Return whether both independent AIC picks passed their SNR/offset QC."""
    return bool(
        row.get("automatic_pick1_accepted")
        and row.get("automatic_pick2_accepted")
    )


def correlation_arrival_offsets(
    time_shift_source: str,
    pick1_offset: float | None,
    pick2_offset: float | None,
    workbook_shift: float | None,
) -> tuple[float, float]:
    """Return event arrival offsets used to center the correlation windows."""
    if time_shift_source == "workbook":
        if workbook_shift is None:
            raise base.AnalysisError("Workbook time shift is required in workbook mode")
        return 0.0, float(workbook_shift)
    if time_shift_source == "none":
        return 0.0, 0.0
    if pick1_offset is None or pick2_offset is None:
        raise base.AnalysisError(
            "Individual AIC offsets are required for computed and picked modes"
        )
    return float(pick1_offset), float(pick2_offset)


def read_workbook_new_pair_locations(
    workbook_path: Path,
) -> dict[str, tuple[float, float, float | None]]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["pairs"]
        rows = sheet.iter_rows(values_only=True)
        headers = {
            str(value).strip().lower(): index
            for index, value in enumerate(next(rows))
            if value is not None and str(value).strip()
        }
        if not {"label", "new_lat", "new_lon"}.issubset(headers):
            return {}
        locations: dict[str, tuple[float, float, float | None]] = {}
        for row in rows:
            label = row[headers["label"]] if headers["label"] < len(row) else None
            if label is None:
                continue
            latitude = finite_float(row[headers["new_lat"]])
            longitude = finite_float(row[headers["new_lon"]])
            if latitude is None or longitude is None:
                continue
            depth = finite_float(row[headers["new_depth"]]) if "new_depth" in headers else None
            locations[str(label).strip()] = (latitude, longitude, depth)
        return locations
    finally:
        workbook.close()


def apply_pair_location_override(
    pair: base.Pair, latitude: float, longitude: float, depth_km: float | None = None
) -> base.Pair:
    depth = pair.depth_km if depth_km is None else depth_km
    event1 = base.Event(
        pair.event1.event_id,
        pair.event1.origin,
        latitude,
        longitude,
        depth,
    )
    event2 = base.Event(
        pair.event2.event_id,
        pair.event2.origin,
        latitude,
        longitude,
        depth,
    )
    return base.Pair(pair.label, event1, event2, latitude, longitude, depth)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def phase_arrival(
    model: TauPyModel,
    event: base.Event,
    station_latitude: float,
    station_longitude: float,
    phase: str,
    cache: dict[tuple[float | int | str, ...], tuple[float | None, float, float | None, float | None]] | None = None,
) -> tuple[float | None, float, float | None, float | None]:
    """Return one TauP arrival, reusing an identical event/station/phase query."""
    cache_key = (
        event.event_id,
        float(event.latitude),
        float(event.longitude),
        float(event.depth_km),
        float(event.origin),
        float(station_latitude),
        float(station_longitude),
        phase,
    )
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    distance = float(
        base.locations2degrees(
            event.latitude,
            event.longitude,
            station_latitude,
            station_longitude,
        )
    )
    arrivals = model.get_travel_times(
        source_depth_in_km=event.depth_km,
        distance_in_degree=distance,
        phase_list=[phase],
    )
    if not arrivals:
        result = (None, distance, None, None)
    else:
        exact = [arrival for arrival in arrivals if arrival.name == phase]
        if exact:
            arrivals = exact
        arrival = arrivals[0]
        result = (
            float(event.origin) + float(arrival.time),
            distance,
            float(arrival.time),
            float(arrival.takeoff_angle),
        )
    if cache is not None:
        cache[cache_key] = result
    return result


def automatic_aic_pick(
    path: Path,
    predicted_epoch: float,
    trace_cache: dict[Path, tuple[float, float, np.ndarray]] | None = None,
    minimum_snr: float = AUTOMATIC_PICK_MIN_SNR,
    noise_window_seconds: tuple[float, float] = AUTOMATIC_PICK_NOISE_WINDOW_SECONDS,
    signal_window_seconds: tuple[float, float] = AUTOMATIC_PICK_SIGNAL_WINDOW_SECONDS,
    search_window_seconds: tuple[float, float] = AUTOMATIC_PICK_SEARCH_SECONDS,
    maximum_absolute_offset_seconds: float = AUTOMATIC_PICK_MAX_OFFSET_SECONDS,
) -> tuple[float | None, float | None, bool, str]:
    """Return a relocation-style AIC pick relative to a predicted phase arrival.

    This is a plot-only QC pick.  Differential timing remains the same-phase
    correlation lag measured elsewhere in this module.
    """
    cached = trace_cache.get(path) if trace_cache is not None else None
    if cached is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                trace = read(str(path))[0].copy()
                trace.detrend("demean")
                trace.detrend("linear")
                trace.taper(max_percentage=0.05, max_length=2.0, type="cosine")
                trace.filter(
                    "bandpass",
                    freqmin=AUTOMATIC_PICK_FILTER_HZ[0],
                    freqmax=AUTOMATIC_PICK_FILTER_HZ[1],
                    corners=4,
                    zerophase=True,
                )
                cached = (
                    float(trace.stats.starttime),
                    float(trace.stats.sampling_rate),
                    np.asarray(trace.data, dtype=float),
                )
            except Exception as exc:
                return None, None, False, f"preprocess_error:{type(exc).__name__}"
        if trace_cache is not None:
            trace_cache[path] = cached
    start_epoch, sampling_hz, data = cached
    relative = start_epoch + np.arange(len(data)) / sampling_hz - predicted_epoch
    indices = np.flatnonzero(
        (relative >= search_window_seconds[0])
        & (relative < search_window_seconds[1])
    )
    if len(indices) < int(8.0 * sampling_hz):
        return None, None, False, "insufficient_search_samples"
    characteristic = np.asarray(aic_simple(data[indices]), dtype=float)
    edge = max(1, int(round(0.5 * sampling_hz)))
    interior = characteristic[edge:-edge]
    if not len(interior) or not np.any(np.isfinite(interior)):
        return None, None, False, "undefined_aic"
    pick_index = int(indices[edge + int(np.nanargmin(interior))])
    pick_epoch = start_epoch + pick_index / sampling_hz
    pick_offset = float(pick_epoch - predicted_epoch)
    pick_relative = start_epoch + np.arange(len(data)) / sampling_hz - pick_epoch
    noise_start, noise_end = noise_window_seconds
    signal_start, signal_end = signal_window_seconds
    noise = data[(pick_relative >= noise_start) & (pick_relative < noise_end)]
    signal = data[(pick_relative >= signal_start) & (pick_relative < signal_end)]
    required_noise_samples = max(
        1, int(round((noise_end - noise_start) * sampling_hz)) - 1
    )
    required_signal_samples = max(
        1, int(round((signal_end - signal_start) * sampling_hz)) - 1
    )
    if len(noise) < required_noise_samples or len(signal) < required_signal_samples:
        return pick_offset, None, False, "insufficient_snr_samples"
    noise_rms = float(np.sqrt(np.mean(np.square(noise))))
    signal_rms = float(np.sqrt(np.mean(np.square(signal))))
    snr = signal_rms / noise_rms if noise_rms > 0.0 else math.inf
    edge_margin = min(
        pick_offset - search_window_seconds[0],
        search_window_seconds[1] - pick_offset,
    )
    reasons = []
    if snr < minimum_snr:
        reasons.append(f"snr<{minimum_snr:g}")
    if edge_margin < 0.75:
        reasons.append("pick_near_search_edge")
    if abs(pick_offset) > maximum_absolute_offset_seconds:
        reasons.append(f"pick_offset>{maximum_absolute_offset_seconds:g}s")
    return pick_offset, snr, not reasons, ";".join(reasons)


def extract_normalized_plot(
    trace1: base.ProcessedTrace,
    trace2: base.ProcessedTrace,
    arrival1: float,
    arrival2: float,
    lag_seconds: float,
    window: list[float],
    normalization_window: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float, bool]:
    requested_relative = base.window_times(window, trace1.sampling_hz)
    first_positions = (
        arrival1 + requested_relative - trace1.start_epoch
    ) * trace1.sampling_hz
    second_positions = (
        arrival2 + requested_relative + lag_seconds - trace2.start_epoch
    ) * trace2.sampling_hz
    available = (
        (first_positions >= -1e-7)
        & (first_positions <= len(trace1.data) - 1 + 1e-7)
        & (second_positions >= -1e-7)
        & (second_positions <= len(trace2.data) - 1 + 1e-7)
    )
    relative = requested_relative[available]
    if not len(relative):
        raise base.AnalysisError(
            "Requested plot window has no samples common to both traces"
        )
    plot_window_clipped = len(relative) != len(requested_relative)
    first_plot = base.extract_relative(trace1, arrival1, relative)
    second_plot = base.extract_relative(trace2, arrival2, relative + lag_seconds)
    normalization_relative = base.window_times(
        normalization_window, trace1.sampling_hz
    )
    first_normalization = base.extract_relative(
        trace1, arrival1, normalization_relative
    )
    second_normalization = base.extract_relative(
        trace2, arrival2, normalization_relative + lag_seconds
    )
    mean1 = float(np.mean(first_normalization))
    mean2 = float(np.mean(second_normalization))
    first_plot = first_plot - mean1
    second_plot = second_plot - mean2
    first_normalization = first_normalization - mean1
    second_normalization = second_normalization - mean2
    scale1 = float(np.sqrt(np.mean(np.square(first_normalization))))
    scale2 = float(np.sqrt(np.mean(np.square(second_normalization))))
    if scale1 <= 0.0 or not math.isfinite(scale1):
        scale1 = 1.0
    if scale2 <= 0.0 or not math.isfinite(scale2):
        scale2 = 1.0
    return (
        relative,
        first_plot / scale1,
        second_plot / scale2,
        scale1,
        scale2,
        plot_window_clipped,
    )


def display_shift(row: dict[str, Any]) -> float:
    if row.get("display_alignment_shift_seconds") not in (None, ""):
        return float(row["display_alignment_shift_seconds"])
    if row.get("fine_search_center_seconds") not in (None, ""):
        return float(row["residual_lag_seconds"])
    preapplied = row.get("preapplied_time_shift")
    if isinstance(preapplied, str):
        preapplied = preapplied.strip().lower() == "true"
    if preapplied:
        return float(row["residual_lag_seconds"])
    return float(row["lag_seconds"])


def acceptance_label(row: dict[str, Any]) -> str:
    """Return the compact plot status requested for waveform rows."""
    if bool(row.get("manual_excluded")):
        return "X"
    return "Acc" if bool(row.get("good")) else "Rej"


def event1_trace_color(row: dict[str, Any]) -> str:
    """Draw manually excluded event-1 traces in black for immediate recognition."""
    return "black" if bool(row.get("manual_excluded")) else "tab:blue"


def format_residual_seconds(value: float) -> str:
    """Format a signed timing residual with three significant digits."""
    return f"{float(value):+#.3g}"


def phase_trace_information(row: dict[str, Any]) -> str:
    """Return the upper-right annotation for one phase waveform row."""
    plot_cc = float(row.get("display_alignment_cc", row["cc"]))
    residual = finite_float(row.get("pair_residual_seconds"))
    if residual is None:
        residual = display_shift(row)
    return (
        f"{row['station_id']}  "
        f"dist={float(row['epicentral_distance_degrees']):.1f}\N{DEGREE SIGN}  "
        f"az={float(row['azimuth_degrees']):.1f}\N{DEGREE SIGN}  "
        f"CC={plot_cc:.2f}  resid={format_residual_seconds(residual)}s  "
        f"{acceptance_label(row)}"
    )


def phase_plot_sort_key(row: dict[str, Any]) -> tuple[float, str]:
    """Sort phase traces by increasing distance, then station for stable ties."""
    return float(row["epicentral_distance_degrees"]), str(row["station_id"])


MAX_TRACES_PER_PHASE_PLOT = 20
MAX_PAIRS_PER_STATION_WAVEFORM_PLOT = 20


def plotted_waveforms(row: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Return the display-scaled waveforms used by both plot orientations."""
    plot1 = np.asarray(row["plot1"], dtype=float)
    plot2 = np.asarray(row["plot2"], dtype=float)
    if bool(row["good"]):
        return plot1, plot2
    display_scale = max(
        float(np.nanpercentile(np.abs(plot1), 95)),
        float(np.nanpercentile(np.abs(plot2), 95)),
        np.finfo(float).eps,
    )
    return 1.8 * plot1 / display_scale, 1.8 * plot2 / display_scale


def plot_phase_waveforms(
    output: Path,
    pair: base.Pair,
    phase: str,
    rows: list[dict[str, Any]],
    threshold: float,
    correlation_window: list[float],
    *,
    accepted_only: bool = False,
) -> None:
    output_directory = output / (
        "phase_plots_A_only" if accepted_only else "phase_plots"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    plotted = sorted(
        [
            row
            for row in rows
            if row["phase"] == phase
            and row.get("absolute_plot_available", True)
            and (
                not accepted_only
                or (bool(row.get("good")) and not bool(row.get("manual_excluded")))
            )
        ],
        key=phase_plot_sort_key,
    )
    if not plotted:
        return
    for page_number, start in enumerate(
        range(0, len(plotted), MAX_TRACES_PER_PHASE_PLOT), start=1
    ):
        page_rows = plotted[start : start + MAX_TRACES_PER_PHASE_PLOT]
        height = max(5.0, 1.0 + 0.52 * len(page_rows))
        figure, axis = plt.subplots(figsize=(12, height), constrained_layout=True)
        for index, row in enumerate(page_rows):
            baseline = (len(page_rows) - 1 - index) * 5.0
            accepted = bool(row["good"])
            trace_alpha = 1.0 if accepted else 0.55
            # A rejected AIC pick can place the correlation window on a
            # near-zero portion of a trace. Scale rejected traces from their
            # displayed waveform, solely for readable QC.
            plot1, plot2 = plotted_waveforms(row)
            axis.plot(
                row["plot_time"], plot1 + baseline, color=event1_trace_color(row),
                linewidth=0.7, linestyle="-", alpha=trace_alpha,
            )
            axis.plot(
                row["plot_time"], plot2 + baseline, color="tab:red",
                linewidth=0.7, linestyle="-", alpha=trace_alpha,
            )
            x_min = float(row["plot_time"][0])
            x_max = float(row["plot_time"][-1])
            for marked_phase, marked_time in row.get("marked_phase_times", {}).items():
                if x_min <= marked_time <= x_max:
                    axis.vlines(
                        marked_time,
                        baseline - 2.15,
                        baseline + 2.15,
                        color="black",
                        linewidth=0.75,
                        alpha=0.82,
                    )
                    axis.text(
                        marked_time,
                        baseline + 2.45,
                        marked_phase,
                        color="black",
                        fontsize=7,
                        rotation=90,
                        ha="center",
                        va="bottom",
                        bbox={
                            "facecolor": "white",
                            "edgecolor": "none",
                            "alpha": 0.72,
                            "pad": 0.4,
                        },
                    )
            for event_label, pick_time, color in (
                ("E1 AIC", row.get("automatic_pick1_plot_time"), "tab:blue"),
                ("E2 AIC", row.get("automatic_pick2_plot_time"), "tab:red"),
            ):
                if pick_time is None or not x_min <= float(pick_time) <= x_max:
                    continue
                axis.vlines(
                    float(pick_time),
                    baseline - 2.15,
                    baseline + 2.15,
                    color=color,
                    linewidth=1.15,
                    linestyle="--",
                    alpha=0.95,
                    label=event_label if index == 0 else None,
                )
            axis.text(
                x_max - 0.01 * (x_max - x_min),
                baseline + 2.15,
                phase_trace_information(row),
                color="0.15" if accepted else "0.38",
                fontsize=7,
                ha="right",
                va="top",
                bbox={
                    "facecolor": "white",
                    "edgecolor": "none",
                    "alpha": 1.0,
                    "pad": 1.0,
                },
                clip_on=True,
            )
        axis.axvspan(
            float(correlation_window[0]),
            float(correlation_window[1]),
            color="0.8",
            alpha=0.25,
        )
        axis.axvline(0.0, color="0.3", linewidth=0.6)
        axis.set_yticks([])
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, loc="upper left", fontsize=7, framealpha=0.85)
        waveform_alignment_shift = finite_float(
            page_rows[0].get("plot_waveform_alignment_shift_seconds")
        )
        common_origin_shift = finite_float(
            page_rows[0].get("plot_common_origin_shift_seconds")
        )
        common_shift_source = str(
            page_rows[0].get("plot_common_time_shift_source", "high_snr_picks")
        )
        origin_fit_min_snr = finite_float(
            page_rows[0].get("plot_origin_fit_min_snr")
        )
        axis.set_xlabel(f"Time relative to predicted {phase} (s)")
        if waveform_alignment_shift is None or common_origin_shift is None:
            alignment_text = "absolute-time alignment unavailable; "
        elif common_shift_source == "workbook":
            alignment_text = (
                f"P waveform shift={waveform_alignment_shift:+.3f}s; workbook "
                f"common shift={common_origin_shift:+.3f}s; "
            )
        elif common_shift_source == "none":
            alignment_text = (
                f"P waveform shift={waveform_alignment_shift:+.3f}s; "
                "common shift=0.000s (none); "
            )
        elif origin_fit_min_snr is not None:
            alignment_text = (
                f"P waveform shift={waveform_alignment_shift:+.3f}s; common L1 "
                f"onset shift={common_origin_shift:+.3f}s (SNR≥{origin_fit_min_snr:g}); "
            )
        else:
            alignment_text = "absolute-time alignment unavailable; "
        exclusion_text = (
            "; black event-1 traces are solution-excluded"
            if any(row.get("manual_excluded") for row in page_rows)
            else ""
        )
        axis.set_title(
            f"{pair.label} {phase}: event {pair.event1.event_id} blue vs "
            f"{pair.event2.event_id} red; rows {start + 1}–{start + len(page_rows)} of {len(plotted)}\n"
            f"{alignment_text}absolute-time traces; dashed lines are accepted AIC picks"
            f"{exclusion_text}"
            f"{'; accepted traces only' if accepted_only else ''}"
        )
        suffix = "" if len(plotted) <= MAX_TRACES_PER_PHASE_PLOT else f"_{page_number:02d}"
        figure.savefig(
            output_directory / f"{pair.label}_{phase}{suffix}.png",
            dpi=180,
            bbox_inches="tight",
        )
        plt.close(figure)


def station_pair_trace_information(row: dict[str, Any]) -> str:
    """Return the right-side label for a station-centric waveform row."""
    plot_cc = float(row.get("display_alignment_cc", row["cc"]))
    residual = finite_float(row.get("pair_residual_seconds"))
    if residual is None:
        residual = display_shift(row)
    return (
        f"{row['pair_label']}  {row['event1']}–{row['event2']}  "
        f"dist={float(row['epicentral_distance_degrees']):.1f}\N{DEGREE SIGN}  "
        f"CC={plot_cc:.2f}  resid={format_residual_seconds(residual)}s  "
        f"{acceptance_label(row)}"
    )


def plot_station_waveform_comparisons(
    output: Path,
    rows: list[dict[str, Any]],
    pair_labels: list[str],
    phase_windows: dict[str, list[float]],
    *,
    accepted_only: bool = False,
) -> int:
    """Make one all-pair waveform comparison for every station and phase."""
    output_directory = output / (
        "station_waveform_plots_A_only"
        if accepted_only
        else "station_waveform_plots"
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    pair_order = {label: index for index, label in enumerate(pair_labels)}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if not row.get("absolute_plot_available", True):
            continue
        if accepted_only and (
            not bool(row.get("good")) or bool(row.get("manual_excluded"))
        ):
            continue
        key = str(row["station_id"]), str(row["phase"])
        grouped.setdefault(key, []).append(row)

    plot_count = 0
    phase_order = {phase: index for index, phase in enumerate(PHASES)}
    for (station_id, phase), station_rows in sorted(
        grouped.items(),
        key=lambda item: (item[0][0], phase_order.get(item[0][1], 99)),
    ):
        plotted = sorted(
            station_rows,
            key=lambda row: pair_order.get(str(row["pair_label"]), len(pair_order)),
        )
        for page_number, start in enumerate(
            range(0, len(plotted), MAX_PAIRS_PER_STATION_WAVEFORM_PLOT), start=1
        ):
            page_rows = plotted[start : start + MAX_PAIRS_PER_STATION_WAVEFORM_PLOT]
            height = max(5.0, 1.0 + 0.58 * len(page_rows))
            figure, axis = plt.subplots(figsize=(13, height), constrained_layout=True)
            for index, row in enumerate(page_rows):
                baseline = (len(page_rows) - 1 - index) * 5.0
                accepted = bool(row["good"])
                trace_alpha = 1.0 if accepted else 0.55
                plot1, plot2 = plotted_waveforms(row)
                plot_time = np.asarray(row["plot_time"], dtype=float)
                axis.plot(
                    plot_time,
                    plot1 + baseline,
                    color=event1_trace_color(row),
                    linewidth=0.7,
                    alpha=trace_alpha,
                )
                axis.plot(
                    plot_time,
                    plot2 + baseline,
                    color="tab:red",
                    linewidth=0.7,
                    alpha=trace_alpha,
                )
                x_min = float(plot_time[0])
                x_max = float(plot_time[-1])
                for marked_phase, marked_time in row.get("marked_phase_times", {}).items():
                    if x_min <= float(marked_time) <= x_max:
                        axis.vlines(
                            float(marked_time), baseline - 2.15, baseline + 2.15,
                            color="black", linewidth=0.75, alpha=0.82,
                        )
                        axis.text(
                            float(marked_time), baseline + 2.45, marked_phase,
                            color="black", fontsize=7, rotation=90,
                            ha="center", va="bottom",
                            bbox={
                                "facecolor": "white", "edgecolor": "none",
                                "alpha": 0.72, "pad": 0.4,
                            },
                        )
                for pick_time, color in (
                    (row.get("automatic_pick1_plot_time"), "tab:blue"),
                    (row.get("automatic_pick2_plot_time"), "tab:red"),
                ):
                    if pick_time is not None and x_min <= float(pick_time) <= x_max:
                        axis.vlines(
                            float(pick_time), baseline - 2.15, baseline + 2.15,
                            color=color, linewidth=1.15, linestyle="--", alpha=0.95,
                        )
                axis.text(
                    x_max - 0.01 * (x_max - x_min),
                    baseline + 2.15,
                    station_pair_trace_information(row),
                    color="0.15" if accepted else "0.38",
                    fontsize=7,
                    ha="right",
                    va="top",
                    bbox={
                        "facecolor": "white", "edgecolor": "none",
                        "alpha": 1.0, "pad": 1.0,
                    },
                    clip_on=True,
                )
            correlation_window = phase_windows[phase]
            axis.axvspan(
                float(correlation_window[0]),
                float(correlation_window[1]),
                color="0.8",
                alpha=0.25,
            )
            axis.axvline(0.0, color="0.3", linewidth=0.6)
            axis.set_yticks([])
            axis.set_xlabel(f"Time relative to predicted {phase} (s)")
            exclusion_text = (
                "; black event-1 traces are solution-excluded"
                if any(row.get("manual_excluded") for row in page_rows)
                else ""
            )
            axis.set_title(
                f"{station_id} {phase}: event-pair waveform comparisons; "
                f"rows {start + 1}–{start + len(page_rows)} of {len(plotted)}\n"
                "event 1 blue and event 2 red; absolute-time traces; dashed lines "
                f"are accepted AIC picks{exclusion_text}"
                f"{'; accepted traces only' if accepted_only else ''}"
            )
            safe_station = station_id.replace(".", "_")
            suffix = (
                ""
                if len(plotted) <= MAX_PAIRS_PER_STATION_WAVEFORM_PLOT
                else f"_{page_number:02d}"
            )
            figure.savefig(
                output_directory / f"{safe_station}_{phase}{suffix}.png",
                dpi=180,
                bbox_inches="tight",
            )
            plt.close(figure)
            plot_count += 1
    return plot_count


def plot_median_residual_geometry(
    output: Path,
    pair_label: str,
    rows: list[dict[str, Any]],
    median_shift: float,
    threshold: float,
) -> None:
    if not rows:
        return
    residual_values = np.array([float(row["residual_shift_seconds"]) for row in rows])
    max_abs = max(0.05, float(np.nanpercentile(np.abs(residual_values), 95)))
    residual_norm = Normalize(vmin=-max_abs, vmax=max_abs)
    cc_norm = Normalize(vmin=threshold, vmax=1.0)
    residual_mappable = ScalarMappable(norm=residual_norm, cmap="coolwarm")
    cc_mappable = ScalarMappable(norm=cc_norm, cmap="viridis")

    polar_figure, polar_axis = plt.subplots(
        figsize=(10, 9),
        subplot_kw={"projection": "polar"},
        constrained_layout=True,
    )
    polar_axis.set_theta_zero_location("N")
    polar_axis.set_theta_direction(-1)
    max_radius = max(10.0, math.ceil(max(row["takeoff_angle_degrees"] for row in rows) / 10.0) * 10.0)
    polar_axis.set_ylim(0.0, max_radius)
    polar_axis.set_rlabel_position(135)
    for phase in PHASES:
        phase_rows = [row for row in rows if row["phase"] == phase]
        if not phase_rows:
            continue
        theta = np.radians([row["azimuth_degrees"] for row in phase_rows])
        radius = [row["takeoff_angle_degrees"] for row in phase_rows]
        polar_axis.scatter(
            theta,
            radius,
            c=[row["residual_shift_seconds"] for row in phase_rows],
            cmap="coolwarm",
            norm=residual_norm,
            s=85,
            marker=PHASE_MARKERS[phase],
            edgecolor="black",
            linewidth=0.35,
            label=f"{phase} n={len(phase_rows)}",
        )
        for row in phase_rows:
            polar_axis.text(
                math.radians(row["azimuth_degrees"]),
                row["takeoff_angle_degrees"] + 1.5,
                format_residual_seconds(row["residual_shift_seconds"]),
                color=cc_mappable.to_rgba(row["cc"]),
                fontsize=6,
                fontweight="bold" if row["cc"] >= 0.9 else "normal",
                ha="center",
                va="center",
            )
    polar_axis.set_title(
        f"{pair_label}: median shift {median_shift:+.2f} s",
        pad=24,
    )
    polar_axis.legend(loc="upper right", bbox_to_anchor=(1.2, 1.15), fontsize=8)
    residual_bar = polar_figure.colorbar(residual_mappable, ax=polar_axis, shrink=0.75, pad=0.08)
    residual_bar.set_label("Residual shift (s)")
    cc_bar = polar_figure.colorbar(cc_mappable, ax=polar_axis, shrink=0.75, pad=0.16)
    cc_bar.set_label("Correlation of printed number")
    polar_figure.savefig(
        output / "median_residual_geometry_plots" / f"{pair_label}_polar_azimuth_takeoff_residuals.png",
        dpi=180,
        bbox_inches="tight",
    )
    plt.close(polar_figure)


def plot_shift_summary(
    output: Path,
    pair_label: str,
    rows: list[dict[str, Any]],
    median_shift: float,
    y_limits_seconds: tuple[float, float] | None = None,
) -> None:
    good = [
        row
        for row in rows
        if row["good"]
        and finite_float(row.get("pair_residual_seconds")) is not None
    ]
    if not good:
        return
    plotted = [
        row
        for row in rows
        if (
            row["good"]
            and finite_float(row.get("pair_residual_seconds")) is not None
        )
        or (
            row.get("manual_excluded")
            and finite_float(row.get("pair_residual_seconds")) is not None
            and finite_float(row.get("cc")) is not None
        )
    ]
    preapplied = any(
        (
            row.get("preapplied_time_shift").strip().lower() == "true"
            if isinstance(row.get("preapplied_time_shift"), str)
            else bool(row.get("preapplied_time_shift"))
        )
        for row in good
    )
    reference_shift = 0.0 if preapplied else median_shift
    fine_centered = any(row.get("fine_search_center_seconds") not in (None, "") for row in good)
    y_label = (
        "residual shift after pair-wide shift (s)"
        if fine_centered
        else "residual shift after pre-applied time shift (s)"
        if preapplied
        else "event2 shift relative to prediction (s)"
    )
    title_suffix = (
        "dashed line = 0 s residual"
        if preapplied or fine_centered
        else f"dashed line = median {median_shift:+.2f} s"
    )
    figure, (axis1, axis2) = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    colors = {
        "P": "tab:blue",
        "PKiKP": "tab:red",
        "PKP": "tab:purple",
    }
    for phase in PHASES:
        phase_rows = [row for row in plotted if row["phase"] == phase]
        if not phase_rows:
            continue
        for manual_excluded, marker, size, alpha in (
            (False, "o", 28, 0.85),
            (True, "x", 48, 0.95),
        ):
            subset = [
                row
                for row in phase_rows
                if bool(row.get("manual_excluded")) == manual_excluded
            ]
            if not subset:
                continue
            label = f"{phase} excluded" if manual_excluded else phase
            axis1.scatter(
                [row["azimuth_degrees"] for row in subset],
                [row["pair_residual_seconds"] for row in subset],
                label=label,
                s=size,
                marker=marker,
                color=colors[phase],
                alpha=alpha,
            )
            axis2.scatter(
                [row["epicentral_distance_degrees"] for row in subset],
                [row["pair_residual_seconds"] for row in subset],
                label=label,
                s=size,
                marker=marker,
                color=colors[phase],
                alpha=alpha,
            )
    for axis in (axis1, axis2):
        axis.axhline(reference_shift, color="0.5", linewidth=0.8, linestyle="--")
        if y_limits_seconds is not None:
            axis.set_ylim(*y_limits_seconds)
        axis.set_ylabel(y_label)
        axis.grid(True, alpha=0.25)
        axis.legend(ncol=5, fontsize=8)
    axis1.set_xlabel("Azimuth (deg)")
    axis2.set_xlabel("Distance (deg)")
    figure.suptitle(f"{pair_label}: same-phase differential shifts; {title_suffix}")
    figure.savefig(output / "phase_plots" / f"{pair_label}_phase_shift_summary.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


def run(
    config_path: Path = Path("analysis_config.json"),
    time_shift_source_override: str | None = None,
) -> Path:
    config = base.load_json(config_path)
    centroid_mode = str(config.get("centroid_location_mode", "fixed_depth")).strip().lower()
    if centroid_mode not in {"free_hypocenter", "fixed_depth", "catalog_fixed"}:
        raise base.AnalysisError(
            "centroid_location_mode must be 'free_hypocenter', 'fixed_depth', or 'catalog_fixed'"
        )
    time_shift_source = str(
        time_shift_source_override or config.get("time_shift_source", "computed")
    )
    if time_shift_source not in {"computed", "workbook", "picked", "none"}:
        raise base.AnalysisError(
            "time_shift_source must be 'computed', 'workbook', 'picked', or 'none'"
        )
    common_time_shift_source = str(
        config.get("common_time_shift_source", "high_snr_picks")
    ).strip().lower()
    if common_time_shift_source not in {"high_snr_picks", "workbook", "none"}:
        raise base.AnalysisError(
            "common_time_shift_source must be 'high_snr_picks', 'workbook', or 'none'"
        )
    configured_time_shift_workbook = config.get("time_shift_workbook")
    time_shift_workbook = (
        Path(str(configured_time_shift_workbook))
        if configured_time_shift_workbook
        else None
    )
    configured_manual_pick_alignment_workbook = config.get(
        "manual_pick_alignment_workbook"
    )
    manual_pick_alignment_workbook = (
        Path(str(configured_manual_pick_alignment_workbook))
        if configured_manual_pick_alignment_workbook
        else None
    )
    threshold = float(config["selection_correlation_threshold"])
    write_a_only_plot_versions = bool(
        config.get("write_a_only_plot_versions", False)
    )
    automatic_pick_min_snr = float(
        config.get("automatic_pick_min_snr", AUTOMATIC_PICK_MIN_SNR)
    )
    automatic_pick_search_seconds = tuple(
        float(value)
        for value in config.get(
            "automatic_pick_search_seconds", AUTOMATIC_PICK_SEARCH_SECONDS
        )
    )
    automatic_pick_max_offset_seconds = float(
        config.get(
            "automatic_pick_max_offset_seconds",
            AUTOMATIC_PICK_MAX_OFFSET_SECONDS,
        )
    )
    if (
        len(automatic_pick_search_seconds) != 2
        or automatic_pick_search_seconds[0] >= automatic_pick_search_seconds[1]
    ):
        raise base.AnalysisError(
            "automatic_pick_search_seconds must contain increasing start/end values"
        )
    if automatic_pick_max_offset_seconds <= 0.0:
        raise base.AnalysisError(
            "automatic_pick_max_offset_seconds must be positive"
        )
    origin_alignment_min_snr = float(
        config.get("origin_alignment_min_snr", ORIGIN_ALIGNMENT_MIN_SNR)
    )
    automatic_pick_noise_window_seconds = tuple(
        float(value)
        for value in config.get(
            "automatic_pick_noise_window_seconds",
            AUTOMATIC_PICK_NOISE_WINDOW_SECONDS,
        )
    )
    if (
        len(automatic_pick_noise_window_seconds) != 2
        or automatic_pick_noise_window_seconds[0]
        >= automatic_pick_noise_window_seconds[1]
    ):
        raise base.AnalysisError(
            "automatic_pick_noise_window_seconds must contain increasing start/end values"
        )
    summary_y_limits = phase_shift_summary_y_limits(config)
    started = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path("outputs") / f"multiphase_median_cc{threshold:g}_{time_shift_source}_{started}"
    (output / "phase_plots").mkdir(parents=True)
    (output / "median_residual_geometry_plots").mkdir()

    model = TauPyModel(model=str(config["taup_model"]))
    arrival_cache: dict[
        tuple[float | int | str, ...],
        tuple[float | None, float, float | None, float | None],
    ] = {}
    automatic_pick_trace_cache: dict[Path, tuple[float, float, np.ndarray]] = {}
    pair_labels = [str(label) for label in config["pairs"]]
    catalog_workbook = time_shift_workbook or Path(config["catalog_path"])
    pairs = base.resolve_catalog(
        catalog_workbook,
        pair_labels,
        float(config["coordinate_tolerance_degrees"]),
        float(config["coordinate_tolerance_depth_km"]),
    )
    new_pair_locations = (
        read_workbook_new_pair_locations(catalog_workbook)
        if centroid_mode != "catalog_fixed"
        else {}
    )
    pairs = {
        label: apply_pair_location_override(pair, *new_pair_locations[label])
        if label in new_pair_locations
        else pair
        for label, pair in pairs.items()
    }
    waveform_root = Path(config["waveform_root"])
    workbook_time_shifts: dict[str, float] = {}
    if time_shift_source == "workbook":
        workbook_time_shifts = read_workbook_time_shifts(
            time_shift_workbook or Path(config["catalog_path"])
        )
    workbook_common_time_shifts: dict[str, float] = {}
    manual_pick_alignment_shifts: dict[tuple[str, str, str], float] = {}
    workbook_manual_exclusions: set[tuple[str, str, str]] = set()
    if manual_pick_alignment_workbook is not None:
        workbook_manual_exclusions = read_workbook_manual_exclusions(
            manual_pick_alignment_workbook
        )
        # Station/phase corrections describe the waveform itself, so they must
        # remain active while a new common shift is being estimated.  Tying
        # them to workbook common-shift mode made calibration previews ignore
        # the reviewed manual corrections they were intended to honor.
        manual_pick_alignment_shifts = read_manual_pick_alignment_shifts(
            manual_pick_alignment_workbook
        )
    if common_time_shift_source == "workbook":
        workbook_common_time_shifts = read_workbook_pair_column(
            time_shift_workbook or Path(config["catalog_path"]),
            "pick align shift",
        )
    preapply_time_shifts = time_shift_source == "workbook"
    lag_search_seconds = (
        float(config["residual_lag_search_seconds"])
        if preapply_time_shifts or time_shift_source == "picked"
        else float(config["lag_search_seconds"])
    )

    phase_windows = phase_correlation_windows(config)
    plot_windows = phase_plot_windows(config)

    measurement_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    phase_summary_rows: list[dict[str, Any]] = []
    median_summary_rows: list[dict[str, Any]] = []
    residual_geometry_rows: list[dict[str, Any]] = []
    station_waveform_rows: list[dict[str, Any]] = []

    total_pairs = len(pair_labels)
    print(
        f"Multiphase run: {total_pairs} pairs, {len(PHASES)} measured phases, "
        f"time_shift_source={time_shift_source}",
        flush=True,
    )

    for pair_number, pair_label in enumerate(pair_labels, start=1):
        pair_start = time.perf_counter()
        pair = pairs[pair_label]
        workbook_pair_shift = workbook_time_shifts.get(pair_label)
        if time_shift_source == "workbook" and workbook_pair_shift is None:
            raise base.AnalysisError(
                f"{pair_label}: no 'new time shift' value found in workbook"
            )
        measurement_common_origin_shift = 0.0
        if common_time_shift_source == "workbook":
            if pair_label not in workbook_common_time_shifts:
                raise base.AnalysisError(
                    f"{pair_label}: no 'pick align shift' value found in workbook"
                )
            measurement_common_origin_shift = workbook_common_time_shifts[pair_label]
        index1 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event1))
        index2 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event2))
        excluded = excluded_station_codes_for_pair(config, pair_label)
        station_ids = sorted(set(index1).intersection(index2))
        pair_plot_rows: list[dict[str, Any]] = []
        trace_cache: dict[str, tuple[Path, Path, base.ProcessedTrace, base.ProcessedTrace]] = {}
        pair_exception_start = len(exception_rows)
        print(
            f"Pair {pair_number}/{total_pairs} {pair_label}: "
            f"{len(station_ids)} common stations; measuring phases...",
            flush=True,
        )

        for station_number, station_id in enumerate(station_ids, start=1):
            configured_station_excluded = base.station_is_excluded(
                station_id, excluded
            )
            if (
                station_number == 1
                or station_number == len(station_ids)
                or station_number % PROGRESS_STATION_INTERVAL == 0
            ):
                print(
                    f"  {pair_label}: station {station_number}/{len(station_ids)} "
                    f"{station_id}",
                    flush=True,
                )
            try:
                path1, path2 = base.choose_trace_pair(
                    index1[station_id],
                    index2[station_id],
                    float(config["station_coordinate_tolerance_degrees"]),
                )
                trace1 = base.preprocess_trace(path1, config)
                trace2 = base.preprocess_trace(path2, config)
                trace_cache[station_id] = (path1, path2, trace1, trace2)
            except Exception as exc:
                exception_rows.append(
                    {
                        "pair_label": pair_label,
                        "station_id": station_id,
                        "phase": "",
                        "exception": type(exc).__name__,
                        "details": str(exc)[:200],
                    }
                )
                continue

            azimuth = float(
                base.gps2dist_azimuth(
                    pair.latitude,
                    pair.longitude,
                    trace1.station_latitude,
                    trace1.station_longitude,
                )[1]
            )
            for phase in PHASES:
                try:
                    manual_excluded = configured_station_excluded or (
                        pair_label,
                        station_id,
                        phase,
                    ) in workbook_manual_exclusions
                    arrival1, distance1, travel1, takeoff = phase_arrival(
                        model, pair.event1, trace1.station_latitude, trace1.station_longitude, phase,
                        arrival_cache,
                    )
                    arrival2, distance2, travel2, _ = phase_arrival(
                        model, pair.event2, trace2.station_latitude, trace2.station_longitude, phase,
                        arrival_cache,
                    )
                    if arrival1 is None or arrival2 is None:
                        exception_rows.append(
                            {
                                "pair_label": pair_label,
                                "station_id": station_id,
                                "phase": phase,
                                "exception": "no_tauP_arrival",
                                "details": "",
                            }
                        )
                        continue
                    distance_degrees = 0.5 * (distance1 + distance2)
                    if not phase_is_usable_for_shift(phase, distance_degrees):
                        continue
                    manual_pick_alignment_shift = manual_pick_alignment_shifts.get(
                        (pair_label, station_id, phase), 0.0
                    )
                    measurement_arrival1, measurement_arrival2 = measurement_phase_arrivals(
                        arrival1,
                        arrival2,
                        measurement_common_origin_shift,
                        manual_pick_alignment_shift,
                    )
                    pick1_offset, pick1_snr, pick1_accepted, pick1_reason = automatic_aic_pick(
                        path1,
                        measurement_arrival1,
                        automatic_pick_trace_cache,
                        automatic_pick_min_snr,
                        automatic_pick_noise_window_seconds,
                        search_window_seconds=automatic_pick_search_seconds,
                        maximum_absolute_offset_seconds=automatic_pick_max_offset_seconds,
                    )
                    pick2_offset, pick2_snr, pick2_accepted, pick2_reason = automatic_aic_pick(
                        path2,
                        measurement_arrival2,
                        automatic_pick_trace_cache,
                        automatic_pick_min_snr,
                        automatic_pick_noise_window_seconds,
                        search_window_seconds=automatic_pick_search_seconds,
                        maximum_absolute_offset_seconds=automatic_pick_max_offset_seconds,
                    )
                    if (
                        not (pick1_accepted and pick2_accepted)
                        and aic_offsets_required_for_correlation(time_shift_source)
                    ):
                        plot_arrival1 = measurement_arrival1 + (pick1_offset or 0.0)
                        plot_arrival2 = measurement_arrival2 + (pick2_offset or 0.0)
                        plot_time, plot1, plot2, plot_scale1, plot_scale2, plot_window_clipped = extract_normalized_plot(
                            trace1,
                            trace2,
                            plot_arrival1,
                            plot_arrival2,
                            0.0,
                            plot_windows[phase],
                            phase_windows[phase],
                        )
                        rejected_reason = (
                            "rejected: automatic AIC pick; "
                            f"event1={pick1_reason or 'accepted'}; "
                            f"event2={pick2_reason or 'accepted'}"
                        )
                        pair_plot_rows.append(
                            {
                                "pair_label": pair_label,
                                "event1": pair.event1.event_id,
                                "event2": pair.event2.event_id,
                                "phase": phase,
                                "station_id": station_id,
                                "station_latitude": trace1.station_latitude,
                                "station_longitude": trace1.station_longitude,
                                "epicentral_distance_degrees": distance_degrees,
                                "azimuth_degrees": azimuth,
                                "takeoff_angle_degrees": takeoff,
                                "predicted_travel_time1_s": travel1,
                                "predicted_travel_time2_s": travel2,
                                "manual_pick_alignment_shift_seconds": (
                                    manual_pick_alignment_shift
                                ),
                                "lag_seconds": 0.0,
                                "applied_time_shift_seconds": 0.0,
                                "preapplied_time_shift": False,
                                "residual_lag_seconds": 0.0,
                                "total_shift_seconds": 0.0,
                                "cc": math.nan,
                                "boundary": False,
                                "phase_geometry_usable": True,
                                "manual_excluded": manual_excluded,
                                "solution_eligible": False,
                                "good": False,
                                "rejection_reason": rejected_reason,
                                "automatic_pick1_offset_s": pick1_offset,
                                "automatic_pick1_snr": pick1_snr,
                                "automatic_pick1_accepted": pick1_accepted,
                                "automatic_pick1_reason": pick1_reason,
                                "automatic_pick2_offset_s": pick2_offset,
                                "automatic_pick2_snr": pick2_snr,
                                "automatic_pick2_accepted": pick2_accepted,
                                "automatic_pick2_reason": pick2_reason,
                                "minimum_snr_passed": picks_meet_minimum_snr(
                                    pick1_snr,
                                    pick2_snr,
                                    automatic_pick_min_snr,
                                ),
                                "aic_reference_includes_common_origin_shift": (
                                    common_time_shift_source == "workbook"
                                ),
                                "trace1_path": str(path1),
                                "trace2_path": str(path2),
                                "plot_scale1_correlation_window_rms": plot_scale1,
                                "plot_scale2_correlation_window_rms": plot_scale2,
                                "plot_window_clipped": plot_window_clipped,
                                "plot_time": plot_time,
                                "plot1": plot1,
                                "plot2": plot2,
                                "marked_phase_times": {},
                                "automatic_pick1_plot_time": 0.0 if pick1_accepted else None,
                                "automatic_pick2_plot_time": 0.0 if pick2_accepted else None,
                            }
                        )
                        exception_rows.append(
                            {
                                "pair_label": pair_label,
                                "station_id": station_id,
                                "phase": phase,
                                "exception": "automatic_phase_pick_rejected",
                                "details": (
                                    f"event1={pick1_reason or 'accepted'}; "
                                    f"event2={pick2_reason or 'accepted'}"
                                ),
                            }
                        )
                        continue
                    if pick1_offset is None or pick2_offset is None:
                        if aic_offsets_required_for_correlation(time_shift_source):
                            raise base.AnalysisError(
                                "Correlation mode requires an automatic phase-pick offset"
                            )
                    arrival1_offset, arrival2_offset = correlation_arrival_offsets(
                        time_shift_source,
                        pick1_offset,
                        pick2_offset,
                        workbook_pair_shift,
                    )
                    correlation_arrival1 = measurement_arrival1 + arrival1_offset
                    correlation_arrival2 = measurement_arrival2 + arrival2_offset
                    applied_time_shift = arrival2_offset - arrival1_offset
                    if time_shift_source == "none":
                        lag, cc, _, _, _ = base.signed_lag_correlation(
                            trace1,
                            trace2,
                            correlation_arrival1,
                            correlation_arrival2,
                            phase_windows[phase],
                            0.0,
                        )
                        boundary = False
                    else:
                        lag, cc, boundary, _, _ = base.signed_lag_correlation(
                            trace1,
                            trace2,
                            correlation_arrival1,
                            correlation_arrival2,
                            phase_windows[phase],
                            lag_search_seconds,
                        )
                    plot_time, plot1, plot2, plot_scale1, plot_scale2, plot_window_clipped = extract_normalized_plot(
                        trace1,
                        trace2,
                        correlation_arrival1,
                        correlation_arrival2,
                        lag,
                        plot_windows[phase],
                        phase_windows[phase],
                    )
                    total_shift = applied_time_shift + float(lag)
                    marked_phase_times: dict[str, float] = {}
                    for marked_phase in MARKED_PHASES:
                        marked_arrival, _, _, _ = phase_arrival(
                            model,
                            pair.event1,
                            trace1.station_latitude,
                            trace1.station_longitude,
                            marked_phase,
                            arrival_cache,
                        )
                        if marked_arrival is None:
                            continue
                        relative_marked_time = float(marked_arrival - correlation_arrival1)
                        if plot_time[0] <= relative_marked_time <= plot_time[-1]:
                            marked_phase_times[marked_phase] = relative_marked_time
                    phase_geometry_usable = True
                    minimum_snr_passed = picks_meet_minimum_snr(
                        pick1_snr,
                        pick2_snr,
                        automatic_pick_min_snr,
                    )
                    good = bool(
                        cc >= threshold
                        and not boundary
                        and phase_geometry_usable
                        and minimum_snr_passed
                        and not manual_excluded
                    )
                    row = {
                        "pair_label": pair_label,
                        "event1": pair.event1.event_id,
                        "event2": pair.event2.event_id,
                        "phase": phase,
                        "station_id": station_id,
                        "station_latitude": trace1.station_latitude,
                        "station_longitude": trace1.station_longitude,
                        "epicentral_distance_degrees": distance_degrees,
                        "azimuth_degrees": azimuth,
                        "takeoff_angle_degrees": takeoff,
                        "predicted_travel_time1_s": travel1,
                        "predicted_travel_time2_s": travel2,
                        "manual_pick_alignment_shift_seconds": (
                            manual_pick_alignment_shift
                        ),
                        "lag_seconds": total_shift,
                        "applied_time_shift_seconds": applied_time_shift,
                        "preapplied_time_shift": False,
                        "residual_lag_seconds": float(lag),
                        "total_shift_seconds": total_shift,
                        "cc": float(cc),
                        "boundary": bool(boundary),
                        "phase_geometry_usable": phase_geometry_usable,
                        "manual_excluded": manual_excluded,
                        "solution_eligible": not manual_excluded,
                        "good": good,
                        "rejection_reason": (
                            "manual station exclusion; measured and plotted only"
                            if manual_excluded
                            else ""
                        ),
                        "automatic_pick1_offset_s": pick1_offset,
                        "automatic_pick1_snr": pick1_snr,
                        "automatic_pick1_accepted": pick1_accepted,
                        "automatic_pick1_reason": pick1_reason,
                        "automatic_pick2_offset_s": pick2_offset,
                        "automatic_pick2_snr": pick2_snr,
                        "automatic_pick2_accepted": pick2_accepted,
                        "automatic_pick2_reason": pick2_reason,
                        "minimum_snr_passed": minimum_snr_passed,
                        "aic_reference_includes_common_origin_shift": (
                            common_time_shift_source == "workbook"
                        ),
                        "trace1_path": str(path1),
                        "trace2_path": str(path2),
                        "plot_scale1_correlation_window_rms": plot_scale1,
                        "plot_scale2_correlation_window_rms": plot_scale2,
                        "plot_window_clipped": plot_window_clipped,
                    }
                    measurement_rows.append(row)
                    pair_plot_row = dict(row)
                    pair_plot_row.update(
                        {
                            "plot_time": plot_time,
                            "plot1": plot1,
                            "plot2": plot2,
                            "marked_phase_times": marked_phase_times,
                            # Plot time is referenced to event 1's picked
                            # arrival; event 2's picked arrival lies one
                            # residual correlation lag earlier on this axis.
                            "automatic_pick1_plot_time": 0.0,
                            "automatic_pick2_plot_time": -float(lag),
                        }
                    )
                    pair_plot_rows.append(pair_plot_row)
                except Exception as exc:
                    exception_rows.append(
                        {
                            "pair_label": pair_label,
                            "station_id": station_id,
                            "phase": phase,
                            "exception": type(exc).__name__,
                            "details": str(exc)[:200],
                        }
                    )

        # Computed and picked modes use a two-stage search.  Reliable first-pass
        # measurements establish a common pair shift.  Re-correlating around
        # that reference prevents an independently picked station from being
        # trapped on an adjacent narrow-band waveform cycle.  Picked mode still
        # honors the AIC acceptance checks; computed mode retains its existing
        # behavior of evaluating every available station/phase in the fine pass.
        minimum_reference_count = (
            int(config.get("minimum_pair_stations", 2))
            if time_shift_source == "picked"
            else 1
        )
        computed_median_shift = pair_consistent_reference_shift(
            pair_plot_rows, minimum_reference_count
        )
        best_display_alignments: dict[tuple[str, str], dict[str, Any]] = {}
        if (
            time_shift_source in {"computed", "picked"}
            and math.isfinite(computed_median_shift)
        ):
            refinement_passes = 2 if time_shift_source == "picked" else 1
            search_center = computed_median_shift
            for _ in range(refinement_passes):
                for row in pair_plot_rows:
                    if not eligible_for_pair_consistent_refinement(
                        row, time_shift_source
                    ):
                        continue
                    try:
                        _, _, trace1, trace2 = trace_cache[row["station_id"]]
                        arrival1, _, travel1, takeoff = phase_arrival(
                            model,
                            pair.event1,
                            trace1.station_latitude,
                            trace1.station_longitude,
                            row["phase"],
                            arrival_cache,
                        )
                        arrival2, _, travel2, _ = phase_arrival(
                            model,
                            pair.event2,
                            trace2.station_latitude,
                            trace2.station_longitude,
                            row["phase"],
                            arrival_cache,
                        )
                        manual_pick_alignment_shift = manual_pick_alignment_shifts.get(
                            (pair_label, row["station_id"], row["phase"]), 0.0
                        )
                        arrival1, arrival2 = measurement_phase_arrivals(
                            arrival1,
                            arrival2,
                            measurement_common_origin_shift,
                            manual_pick_alignment_shift,
                        )
                        fine_lag, cc, boundary, _, _ = base.signed_lag_correlation(
                            trace1,
                            trace2,
                            arrival1,
                            arrival2 + search_center,
                            phase_windows[row["phase"]],
                            float(config["residual_lag_search_seconds"]),
                        )
                        (
                            plot_time,
                            plot1,
                            plot2,
                            plot_scale1,
                            plot_scale2,
                            plot_window_clipped,
                        ) = extract_normalized_plot(
                            trace1,
                            trace2,
                            arrival1,
                            arrival2 + search_center,
                            fine_lag,
                            plot_windows[row["phase"]],
                            phase_windows[row["phase"]],
                        )
                        display_key = (row["station_id"], row["phase"])
                        prior_display = best_display_alignments.get(display_key)
                        if prior_display is None or cc > prior_display["cc"]:
                            best_display_alignments[display_key] = {
                                "cc": float(cc),
                                "total_shift_seconds": search_center + float(fine_lag),
                                "plot_time": plot_time,
                                "plot1": plot1,
                                "plot2": plot2,
                                "plot_scale1": plot_scale1,
                                "plot_scale2": plot_scale2,
                                "plot_window_clipped": plot_window_clipped,
                                "automatic_pick2_plot_time": (
                                    float(row["automatic_pick2_offset_s"])
                                    - search_center
                                    - float(fine_lag)
                                    if row.get("automatic_pick2_accepted")
                                    and row.get("automatic_pick2_offset_s") is not None
                                    else None
                                ),
                            }
                        row.update(
                            {
                                "lag_seconds": search_center + float(fine_lag),
                                "applied_time_shift_seconds": search_center,
                                "fine_search_center_seconds": search_center,
                                "residual_lag_seconds": float(fine_lag),
                                "total_shift_seconds": search_center + float(fine_lag),
                                "cc": float(cc),
                                "boundary": bool(boundary),
                                "good": bool(
                                    cc >= threshold
                                    and not boundary
                                    and row["phase_geometry_usable"]
                                    and not row.get("manual_excluded", False)
                                    and (
                                        time_shift_source != "picked"
                                        or passes_picked_mode_aic_qc(row)
                                    )
                                ),
                                "predicted_travel_time1_s": travel1,
                                "predicted_travel_time2_s": travel2,
                                "takeoff_angle_degrees": takeoff,
                                "plot_scale1_correlation_window_rms": plot_scale1,
                                "plot_scale2_correlation_window_rms": plot_scale2,
                                "plot_window_clipped": plot_window_clipped,
                            }
                        )
                        row["plot_time"] = plot_time
                        row["plot1"] = plot1
                        row["plot2"] = plot2
                        row["automatic_pick2_plot_time"] = (
                            float(row["automatic_pick2_offset_s"])
                            - search_center
                            - float(fine_lag)
                            if row.get("automatic_pick2_accepted")
                            and row.get("automatic_pick2_offset_s") is not None
                            else None
                        )
                    except Exception as exc:
                        row["good"] = False
                        exception_rows.append(
                            {
                                "pair_label": pair_label,
                                "station_id": row["station_id"],
                                "phase": row["phase"],
                                "exception": type(exc).__name__,
                                "details": f"fine search: {str(exc)[:160]}",
                            }
                        )
                if time_shift_source == "picked":
                    refined_median_shift = pair_consistent_reference_shift(
                        pair_plot_rows, minimum_reference_count
                    )
                    if math.isfinite(refined_median_shift):
                        computed_median_shift = refined_median_shift
                        search_center = refined_median_shift

            # A rejected row can have a much stronger adjacent-cycle peak than
            # the pair-consistent measurement.  Show that best waveform overlay
            # for visual QC, but keep the pair-consistent measurement fields and
            # good=False so it cannot enter location or bootstrap calculations.
            residual_limit = float(config["residual_lag_search_seconds"])
            for row in pair_plot_rows:
                if row["good"]:
                    continue
                best_display = best_display_alignments.get(
                    (row["station_id"], row["phase"])
                )
                if best_display is None or not math.isfinite(computed_median_shift):
                    continue
                cycle_offset = (
                    float(best_display["total_shift_seconds"])
                    - computed_median_shift
                )
                if (
                    abs(cycle_offset) <= residual_limit
                    or float(best_display["cc"]) <= float(row["cc"])
                ):
                    continue
                row["plot_time"] = best_display["plot_time"]
                row["plot1"] = best_display["plot1"]
                row["plot2"] = best_display["plot2"]
                row["plot_scale1_correlation_window_rms"] = best_display[
                    "plot_scale1"
                ]
                row["plot_scale2_correlation_window_rms"] = best_display[
                    "plot_scale2"
                ]
                row["plot_window_clipped"] = best_display["plot_window_clipped"]
                row["automatic_pick2_plot_time"] = best_display[
                    "automatic_pick2_plot_time"
                ]
                row["display_alignment_only"] = True
                row["display_alignment_shift_seconds"] = best_display[
                    "total_shift_seconds"
                ]
                row["display_alignment_cc"] = best_display["cc"]
                row["display_alignment_cycle_offset_seconds"] = cycle_offset
                row["display_alignment_reason"] = (
                    "higher-CC adjacent cycle is inconsistent with pair median; "
                    "display only"
                )

        # First align event 2 to event 1 with the L1 median accepted P waveform
        # shift.  Then translate both aligned events by one common shift so
        # their onsets center on the predicted arrival.  In workbook common-
        # shift mode, add the optional station/phase manual display correction.
        if time_shift_source == "none":
            p_waveform_alignment_shift = 0.0
        elif time_shift_source == "workbook":
            p_waveform_alignment_shift = float(workbook_pair_shift)
        else:
            p_waveform_alignment_shift = l1_p_waveform_alignment_shift(
                pair_plot_rows, minimum_reference_count
            )
        if common_time_shift_source == "none":
            common_origin_shift, origin_fit_pick_count = 0.0, 0
        elif common_time_shift_source == "workbook":
            common_origin_shift = measurement_common_origin_shift
            origin_fit_pick_count = 0
        else:
            common_origin_shift, origin_fit_pick_count = (
                l1_common_high_snr_p_origin_shift(
                    pair_plot_rows,
                    p_waveform_alignment_shift,
                    origin_alignment_min_snr,
                    minimum_reference_count,
                )
                if math.isfinite(p_waveform_alignment_shift)
                else (math.nan, 0)
            )
        if math.isfinite(p_waveform_alignment_shift) and math.isfinite(
            common_origin_shift
        ):
            for row in pair_plot_rows:
                manual_pick_alignment_shift = finite_float(
                    row.get("manual_pick_alignment_shift_seconds")
                ) or 0.0
                _, _, trace1, trace2 = trace_cache[row["station_id"]]
                arrival1, _, _, _ = phase_arrival(
                    model,
                    pair.event1,
                    trace1.station_latitude,
                    trace1.station_longitude,
                    row["phase"],
                    arrival_cache,
                )
                arrival2, _, _, _ = phase_arrival(
                    model,
                    pair.event2,
                    trace2.station_latitude,
                    trace2.station_longitude,
                    row["phase"],
                    arrival_cache,
                )
                if arrival1 is None or arrival2 is None:
                    continue
                try:
                    display_arrival1, display_arrival2 = (
                        manually_shifted_phase_arrivals(
                            arrival1 + common_origin_shift,
                            arrival2
                            + p_waveform_alignment_shift
                            + common_origin_shift,
                            manual_pick_alignment_shift,
                        )
                    )
                    plot_time, plot1, plot2, plot_scale1, plot_scale2, plot_window_clipped = (
                        extract_normalized_plot(
                            trace1,
                            trace2,
                            display_arrival1,
                            display_arrival2,
                            0.0,
                            plot_windows[row["phase"]],
                            phase_windows[row["phase"]],
                        )
                    )
                except base.AnalysisError as exc:
                    row["absolute_plot_available"] = False
                    exception_rows.append(
                        {
                            "pair_label": pair_label,
                            "station_id": row["station_id"],
                            "phase": row["phase"],
                            "exception": "absolute_plot_window_unavailable",
                            "details": str(exc)[:200],
                        }
                    )
                    continue
                marked_phase_times: dict[str, float] = {}
                for marked_phase in MARKED_PHASES:
                    marked_arrival, _, _, _ = phase_arrival(
                        model,
                        pair.event1,
                        trace1.station_latitude,
                        trace1.station_longitude,
                        marked_phase,
                        arrival_cache,
                    )
                    if marked_arrival is None:
                        continue
                    relative_marked_time = float(marked_arrival - arrival1)
                    if plot_time[0] <= relative_marked_time <= plot_time[-1]:
                        marked_phase_times[marked_phase] = relative_marked_time
                pick1_plot_time, pick2_plot_time = absolute_plot_pick_times(
                    row,
                    p_waveform_alignment_shift,
                    common_origin_shift,
                )
                row.update(
                    {
                        "plot_time": plot_time,
                        "plot1": plot1,
                        "plot2": plot2,
                        "plot_scale1_correlation_window_rms": plot_scale1,
                        "plot_scale2_correlation_window_rms": plot_scale2,
                        "plot_window_clipped": plot_window_clipped,
                        "marked_phase_times": marked_phase_times,
                        "automatic_pick1_plot_time": pick1_plot_time,
                        "automatic_pick2_plot_time": pick2_plot_time,
                        "plot_waveform_alignment_shift_seconds": (
                            p_waveform_alignment_shift
                        ),
                        "plot_common_origin_shift_seconds": common_origin_shift,
                        "plot_manual_pick_alignment_shift_seconds": manual_pick_alignment_shift,
                        "plot_common_time_shift_source": common_time_shift_source,
                        "plot_origin_fit_min_snr": origin_alignment_min_snr,
                        "absolute_plot_available": True,
                        "plot_alignment_mode": (
                            f"relative_{time_shift_source}_common_"
                            f"{common_time_shift_source}"
                        ),
                    }
                )
                for key in (
                    "display_alignment_only",
                    "display_alignment_shift_seconds",
                    "display_alignment_cc",
                    "display_alignment_cycle_offset_seconds",
                    "display_alignment_reason",
                ):
                    row.pop(key, None)

        # Replace this pair's broad-pass measurement rows with the refined
        # rows so CSV consumers see the fine residuals too.
        measurement_rows[:] = [
            row for row in measurement_rows if row["pair_label"] != pair_label
        ]
        measurement_rows.extend(
            {
                key: value
                for key, value in row.items()
                if key not in {"plot_time", "plot1", "plot2", "marked_phase_times"}
            }
            for row in pair_plot_rows
        )
        station_waveform_rows.extend(pair_plot_rows)

        good_rows = [row for row in pair_plot_rows if row["good"]]
        measured_count = len(pair_plot_rows)
        good_count = len(good_rows)
        exception_count = len(exception_rows) - pair_exception_start
        if time_shift_source == "computed":
            # Keep the broad estimate as the pair reference; the fine pass
            # must not move the common shift itself.
            computed_median_shift = computed_median_shift
        if time_shift_source == "workbook":
            if pair_label not in workbook_time_shifts:
                raise base.AnalysisError(
                    f"{pair_label}: no 'new time shift' value found in workbook"
                )
            median_shift = workbook_time_shifts[pair_label]
        elif time_shift_source == "none":
            median_shift = 0.0
        else:
            median_shift = computed_median_shift
        for row in pair_plot_rows:
            total_shift = finite_float(row.get("total_shift_seconds"))
            if total_shift is not None and math.isfinite(median_shift):
                row["pair_residual_seconds"] = total_shift - median_shift
        # Refresh this pair's exported measurement rows after assigning the
        # explicit pair-median residual used by plots and diagnostic tables.
        measurement_rows[:] = [
            row for row in measurement_rows if row["pair_label"] != pair_label
        ]
        measurement_rows.extend(
            {
                key: value
                for key, value in row.items()
                if key not in {"plot_time", "plot1", "plot2", "marked_phase_times"}
            }
            for row in pair_plot_rows
        )
        for row in good_rows:
            residual = row["total_shift_seconds"] - median_shift
            residual_geometry_rows.append(
                {
                    "pair_label": pair_label,
                    "event1": row["event1"],
                    "event2": row["event2"],
                    "phase": row["phase"],
                    "station_id": row["station_id"],
                    "azimuth_degrees": row["azimuth_degrees"],
                    "takeoff_angle_degrees": row["takeoff_angle_degrees"],
                    "lag_seconds": row["lag_seconds"],
                    "applied_time_shift_seconds": row["applied_time_shift_seconds"],
                    "preapplied_time_shift": row["preapplied_time_shift"],
                    "residual_lag_seconds": row["residual_lag_seconds"],
                    "total_shift_seconds": row["total_shift_seconds"],
                    "pair_median_shift_seconds": median_shift,
                    "residual_shift_seconds": residual,
                    "cc": row["cc"],
                    "epicentral_distance_degrees": row["epicentral_distance_degrees"],
                }
            )
        residuals = np.array([row["total_shift_seconds"] - median_shift for row in good_rows], dtype=float)
        median_summary_rows.append(
            {
                "pair_label": pair_label,
                "event1": pair.event1.event_id,
                "event2": pair.event2.event_id,
                "common_lat": pair.latitude,
                "common_lon": pair.longitude,
                "common_depth_km": pair.depth_km,
                "good_count": len(good_rows),
                "computed_median_shift_seconds": computed_median_shift if good_rows else "",
                "p_l1_waveform_alignment_shift_seconds": (
                    p_waveform_alignment_shift
                    if math.isfinite(p_waveform_alignment_shift)
                    else ""
                ),
                "common_l1_high_snr_p_origin_shift_seconds": (
                    common_origin_shift
                    if common_time_shift_source == "high_snr_picks"
                    and math.isfinite(common_origin_shift)
                    else ""
                ),
                "common_time_shift_seconds": (
                    common_origin_shift
                    if math.isfinite(common_origin_shift)
                    else ""
                ),
                "common_time_shift_source": common_time_shift_source,
                "origin_alignment_min_snr": origin_alignment_min_snr,
                "origin_fit_p_pick_count": origin_fit_pick_count,
                "time_shift_source": time_shift_source,
                "pair_median_shift_seconds": median_shift if good_rows else "",
                "residual_median_abs_seconds": float(np.median(np.abs(residuals))) if len(residuals) else "",
                "residual_mad_seconds": float(np.median(np.abs(residuals - np.median(residuals)))) if len(residuals) else "",
                "residual_rms_seconds": float(np.sqrt(np.mean(residuals * residuals))) if len(residuals) else "",
                "residual_min_seconds": float(np.min(residuals)) if len(residuals) else "",
                "residual_max_seconds": float(np.max(residuals)) if len(residuals) else "",
            }
        )

        for phase in PHASES:
            plot_phase_waveforms(
                output,
                pair,
                phase,
                pair_plot_rows,
                threshold,
                phase_windows[phase],
            )
            if write_a_only_plot_versions:
                plot_phase_waveforms(
                    output,
                    pair,
                    phase,
                    pair_plot_rows,
                    threshold,
                    phase_windows[phase],
                    accepted_only=True,
                )
            rows_for_phase = [row for row in pair_plot_rows if row["phase"] == phase]
            good_for_phase = [row for row in rows_for_phase if row["good"]]
            values = np.array([row["total_shift_seconds"] for row in good_for_phase], dtype=float)
            ccs = np.array([row["cc"] for row in good_for_phase], dtype=float)
            phase_summary_rows.append(
                {
                    "pair_label": pair_label,
                    "event1": pair.event1.event_id,
                    "event2": pair.event2.event_id,
                    "phase": phase,
                    "measured_count": len(rows_for_phase),
                    "good_count": len(good_for_phase),
                    "median_traveltime_difference_s": float(np.median(values)) if len(values) else "",
                    "uncertainty_mad_s": float(np.median(np.abs(values - np.median(values)))) if len(values) else "",
                    "mean_traveltime_difference_s": float(np.mean(values)) if len(values) else "",
                    "uncertainty_std_s": float(np.std(values, ddof=1)) if len(values) > 1 else "",
                    "median_cc": float(np.median(ccs)) if len(ccs) else "",
                }
            )
        plot_shift_summary(
            output,
            pair_label,
            pair_plot_rows,
            median_shift,
            summary_y_limits,
        )
        plot_median_residual_geometry(
            output,
            pair_label,
            [row for row in residual_geometry_rows if row["pair_label"] == pair_label],
            median_shift,
            threshold,
        )
        elapsed = time.perf_counter() - pair_start
        print(
            f"Pair {pair_number}/{total_pairs} {pair_label}: "
            f"done in {elapsed:.1f}s; measured={measured_count}, "
            f"good={good_count}, exceptions={exception_count}, "
            f"median_shift={median_shift:+.4f}s",
            flush=True,
        )

    print("Writing CSV summaries and all-pairs residual plot...", flush=True)
    plot_all_pairs_residuals(output, pair_labels, residual_geometry_rows, median_summary_rows, threshold)
    station_waveform_plot_count = plot_station_waveform_comparisons(
        output,
        station_waveform_rows,
        pair_labels,
        phase_windows,
    )
    print(
        f"Created {station_waveform_plot_count} station-phase waveform comparison plots.",
        flush=True,
    )
    if write_a_only_plot_versions:
        a_only_station_plot_count = plot_station_waveform_comparisons(
            output,
            station_waveform_rows,
            pair_labels,
            phase_windows,
            accepted_only=True,
        )
        print(
            f"Created {a_only_station_plot_count} accepted-only station-phase "
            "waveform comparison plots.",
            flush=True,
        )

    write_csv(output / "phase_measurements.csv", measurement_rows)
    write_csv(output / "phase_summary.csv", phase_summary_rows)
    write_csv(output / "median_summary.csv", median_summary_rows)
    write_csv(output / "median_residual_geometry.csv", residual_geometry_rows)
    write_csv(output / "exceptions.csv", exception_rows)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "created": dt.datetime.now().isoformat(),
                "config_path": str(config_path.resolve()),
                "correlation_threshold": threshold,
                "time_shift_source": time_shift_source,
                "common_time_shift_source": common_time_shift_source,
                "time_shift_workbook": str(time_shift_workbook) if time_shift_workbook else "",
                "manual_pick_alignment_workbook": (
                    str(manual_pick_alignment_workbook)
                    if manual_pick_alignment_workbook
                    else ""
                ),
                "manual_pick_alignment_shift_count": len(
                    manual_pick_alignment_shifts
                ),
                "catalog_workbook": str(catalog_workbook),
                "pair_location_source": (
                    "catalog_ehb" if centroid_mode == "catalog_fixed"
                    else "relocated_centroid_when_available"
                ),
                "centroid_location_mode": centroid_mode,
                "preapplied_time_shifts": preapply_time_shifts,
                "lag_search_seconds": lag_search_seconds,
                "phase_plot_normalization": (
                    "each trace demeaned by its own phase correlation/search "
                    "window mean, then divided by its own demeaned RMS amplitude "
                    "within that same window"
                ),
                "phase_plot_time_alignment": (
                    {
                        "none": "event 2 remains at its unshifted predicted phase arrival",
                        "workbook": (
                            "event 2 aligned to event 1 by the workbook "
                            "'new time shift' value"
                        ),
                        "computed": (
                            "event 2 aligned to event 1 by the computed pair-consistent "
                            "waveform time"
                        ),
                        "picked": (
                            "event 2 aligned to event 1 by the picked pair-consistent "
                            "waveform time"
                        ),
                    }[time_shift_source]
                    + "; "
                    + {
                        "none": "no common shift applied",
                        "workbook": (
                            "both events shifted by the workbook 'pick align shift' value, "
                            "plus any station/phase manual pick-alignment shift"
                        ),
                        "high_snr_picks": (
                            "both events shifted by the L1 median high-SNR AIC P onset residual"
                        ),
                    }[common_time_shift_source]
                    + "; workbook common-origin and manual station/phase shifts "
                    "are applied before AIC, SNR, correlation-window, and "
                    "differential-time measurement"
                ),
                "phase_plot_boundary_handling": (
                    "measurement uses the full configured correlation window; "
                    "display traces are clipped to the samples common to both "
                    "files when the requested plot window reaches a file boundary"
                ),
                "station_waveform_plots": (
                    "one plot per measured station and phase, with available event pairs "
                    "as rows and the same absolute-time display alignment as phase plots"
                ),
                "a_only_plot_versions": write_a_only_plot_versions,
                "origin_alignment_min_snr": origin_alignment_min_snr,
                "phase_shift_summary_ylim_seconds": summary_y_limits,
                "printed_residual_significant_digits": 3,
                "phase_selection_rules": {
                    "Pdiff": (
                        "excluded from measurement, plotting, and fitting"
                    ),
                    "PKiKP": "epicentral_distance_degrees >= 110; smaller distances ignored",
                    "PKIKP": "marked on plots only; not measured or fit",
                },
                "automatic_plot_qc_picks": {
                    "phases": list(PHASES),
                    "method": "AIC minimum after 0.7-4 Hz zero-phase filtering",
                    "search_seconds_relative_to_predicted_arrival": automatic_pick_search_seconds,
                    "minimum_snr": automatic_pick_min_snr,
                    "noise_window_seconds_relative_to_aic_pick": (
                        automatic_pick_noise_window_seconds
                    ),
                    "signal_window_seconds_relative_to_aic_pick": (
                        AUTOMATIC_PICK_SIGNAL_WINDOW_SECONDS
                    ),
                    "maximum_absolute_offset_seconds": automatic_pick_max_offset_seconds,
                    "use": (
                        "computed/picked modes may use AIC offsets for initial "
                        "window centers; workbook/none modes measure correlation "
                        "even when AIC timing-offset QC fails because their window "
                        "centers do not depend on those offsets; minimum AIC SNR "
                        "remains an independent acceptance criterion"
                    ),
                },
                "pairs": pair_labels,
                "phases": PHASES,
                "marked_phases": MARKED_PHASES,
                "excluded_stations": sorted(base.excluded_station_codes(config)),
                "excluded_stations_by_pair": config.get(
                    "excluded_stations_by_pair", {}
                ),
                "excluded_station_handling": (
                    "measure correlation and residual and include in waveform and "
                    "phase-shift plots, but set good=false so excluded stations do "
                    "not enter pair medians, location fits, or bootstraps"
                ),
                "summary_method": (
                    "zero-shift waveform comparison at predicted phase arrivals; "
                    "relative-location fitting is disabled"
                    if time_shift_source == "none"
                    else "reliable first-pass pair median followed by pair-consistent "
                    "station refinement; no L1 location fit"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def plot_all_pairs_residuals(
    output: Path,
    pair_labels: list[str],
    residual_rows: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    threshold: float,
) -> None:
    summary_by_pair = {row["pair_label"]: row for row in summaries}
    polar_figure, axes = plt.subplots(
        4,
        2,
        figsize=(14, 16),
        subplot_kw={"projection": "polar"},
        constrained_layout=True,
    )
    axes = axes.ravel()
    cc_norm = Normalize(vmin=threshold, vmax=1.0)
    cc_mappable = ScalarMappable(norm=cc_norm, cmap="viridis")
    for axis, pair_label in zip(axes, pair_labels):
        pair_rows = [row for row in residual_rows if row["pair_label"] == pair_label]
        axis.set_theta_zero_location("N")
        axis.set_theta_direction(-1)
        if not pair_rows:
            axis.set_title(pair_label)
            continue
        max_radius = max(10.0, math.ceil(max(row["takeoff_angle_degrees"] for row in pair_rows) / 10.0) * 10.0)
        axis.set_ylim(0.0, max_radius)
        axis.set_rlabel_position(135)
        residual_values = np.array([row["residual_shift_seconds"] for row in pair_rows])
        max_abs = max(0.05, float(np.nanpercentile(np.abs(residual_values), 95)))
        residual_norm = Normalize(vmin=-max_abs, vmax=max_abs)
        for phase in PHASES:
            phase_rows = [row for row in pair_rows if row["phase"] == phase]
            if not phase_rows:
                continue
            axis.scatter(
                np.radians([row["azimuth_degrees"] for row in phase_rows]),
                [row["takeoff_angle_degrees"] for row in phase_rows],
                c=[row["residual_shift_seconds"] for row in phase_rows],
                cmap="coolwarm",
                norm=residual_norm,
                s=35,
                marker=PHASE_MARKERS[phase],
                edgecolor="black",
                linewidth=0.25,
                label=phase,
            )
            for row in phase_rows:
                if row["cc"] < max(0.75, threshold):
                    continue
                axis.text(
                    math.radians(row["azimuth_degrees"]),
                    row["takeoff_angle_degrees"] + 1.2,
                    format_residual_seconds(row["residual_shift_seconds"]),
                    color=cc_mappable.to_rgba(row["cc"]),
                    fontsize=5,
                    ha="center",
                    va="center",
                )
        summary = summary_by_pair[pair_label]
        axis.set_title(
            f"{pair_label}\nmedian {summary['pair_median_shift_seconds']:+.2f}s; "
            f"MAD {summary['residual_mad_seconds']:.2f}s",
            fontsize=10,
        )
    handles, labels = axes[0].get_legend_handles_labels()
    polar_figure.legend(handles, labels, loc="outside lower center", ncol=5)
    cc_bar = polar_figure.colorbar(cc_mappable, ax=axes.tolist(), shrink=0.5, pad=0.02)
    cc_bar.set_label("Correlation of printed numbers")
    polar_figure.suptitle(
        "Median-subtracted residual shifts",
        fontsize=14,
    )
    polar_figure.savefig(
        output / "median_residual_geometry_plots" / "all_pairs_polar_azimuth_takeoff_residuals.png",
        dpi=180,
        bbox_inches="tight",
    )
    plt.close(polar_figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("analysis_config.json"))
    parser.add_argument(
        "--time-shift-source",
        choices=("computed", "workbook", "picked", "none"),
        default=None,
        help="Override analysis_config.json time_shift_source for this run.",
    )
    args = parser.parse_args()
    output = run(args.config, args.time_shift_source)
    print(f"OUTPUT {output.resolve()}")
    print(f"phase plots {len(list((output / 'phase_plots').glob('*.png')))}")
    print(f"residual plots {len(list((output / 'median_residual_geometry_plots').glob('*.png')))}")


if __name__ == "__main__":
    main()
