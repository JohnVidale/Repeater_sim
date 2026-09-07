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
AUTOMATIC_PICK_MIN_SNR = 2.5
AUTOMATIC_PICK_MAX_OFFSET_SECONDS = 5.5


def phase_is_usable_for_shift(phase: str, distance_degrees: float) -> bool:
    """Return whether this phase/station geometry should enter shift summaries."""
    if phase not in PHASES:
        return False
    if phase == "PKiKP":
        return distance_degrees > 100.0
    return True


def read_workbook_time_shifts(workbook_path: Path) -> dict[str, float]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["pairs"]
        rows = sheet.iter_rows(values_only=True)
        headers = {
            str(value).strip().lower(): index
            for index, value in enumerate(next(rows))
            if value is not None
        }
        label_index = headers["label"]
        shift_index = headers["new time shift"]
        shifts: dict[str, float] = {}
        for row in rows:
            label = row[label_index] if label_index < len(row) else None
            value = row[shift_index] if shift_index < len(row) else None
            if label is None or value is None or str(value).strip() == "":
                continue
            shifts[str(label).strip()] = float(value)
        return shifts
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
        (relative >= AUTOMATIC_PICK_SEARCH_SECONDS[0])
        & (relative < AUTOMATIC_PICK_SEARCH_SECONDS[1])
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
    noise = data[(pick_relative >= -8.0) & (pick_relative < -2.0)]
    signal = data[(pick_relative >= 0.0) & (pick_relative < 4.0)]
    if len(noise) < int(3.0 * sampling_hz) or len(signal) < int(2.0 * sampling_hz):
        return pick_offset, None, False, "insufficient_snr_samples"
    noise_rms = float(np.sqrt(np.mean(np.square(noise))))
    signal_rms = float(np.sqrt(np.mean(np.square(signal))))
    snr = signal_rms / noise_rms if noise_rms > 0.0 else math.inf
    edge_margin = min(
        pick_offset - AUTOMATIC_PICK_SEARCH_SECONDS[0],
        AUTOMATIC_PICK_SEARCH_SECONDS[1] - pick_offset,
    )
    reasons = []
    if snr < AUTOMATIC_PICK_MIN_SNR:
        reasons.append(f"snr<{AUTOMATIC_PICK_MIN_SNR:g}")
    if edge_margin < 0.75:
        reasons.append("pick_near_search_edge")
    if abs(pick_offset) > AUTOMATIC_PICK_MAX_OFFSET_SECONDS:
        reasons.append(f"pick_offset>{AUTOMATIC_PICK_MAX_OFFSET_SECONDS:g}s")
    return pick_offset, snr, not reasons, ";".join(reasons)


def extract_normalized_plot(
    trace1: base.ProcessedTrace,
    trace2: base.ProcessedTrace,
    arrival1: float,
    arrival2: float,
    lag_seconds: float,
    window: list[float],
    normalization_window: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    relative = base.window_times(window, trace1.sampling_hz)
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
    return relative, first_plot / scale1, second_plot / scale2, scale1, scale2


def display_shift(row: dict[str, Any]) -> float:
    if row.get("fine_search_center_seconds") not in (None, ""):
        return float(row["residual_lag_seconds"])
    preapplied = row.get("preapplied_time_shift")
    if isinstance(preapplied, str):
        preapplied = preapplied.strip().lower() == "true"
    if preapplied:
        return float(row["residual_lag_seconds"])
    return float(row["lag_seconds"])


MAX_TRACES_PER_PHASE_PLOT = 20


def plot_phase_waveforms(
    output: Path,
    pair: base.Pair,
    phase: str,
    rows: list[dict[str, Any]],
    threshold: float,
) -> None:
    plotted = sorted(
        [row for row in rows if row["phase"] == phase],
        key=lambda row: (
            not bool(row["good"]),
            -float(row["epicentral_distance_degrees"]),
        ),
    )
    if not plotted:
        return
    for page_number, start in enumerate(
        range(0, len(plotted), MAX_TRACES_PER_PHASE_PLOT), start=1
    ):
        page_rows = plotted[start : start + MAX_TRACES_PER_PHASE_PLOT]
        height = max(5.0, 1.0 + 0.52 * len(page_rows))
        figure, axis = plt.subplots(figsize=(12, height), constrained_layout=True)
        row_labels: list[str] = []
        baselines: list[float] = []
        for index, row in enumerate(page_rows):
            baseline = (len(page_rows) - 1 - index) * 5.0
            accepted = bool(row["good"])
            baselines.append(baseline)
            trace_alpha = 1.0 if accepted else 0.55
            plot1 = np.asarray(row["plot1"], dtype=float)
            plot2 = np.asarray(row["plot2"], dtype=float)
            if not accepted:
                # A rejected AIC pick can place the correlation window on a
                # near-zero portion of a trace.  Scale rejected traces from
                # their displayed waveform instead, solely for readable QC.
                display_scale = max(
                    float(np.nanpercentile(np.abs(plot1), 95)),
                    float(np.nanpercentile(np.abs(plot2), 95)),
                    np.finfo(float).eps,
                )
                plot1 = 1.8 * plot1 / display_scale
                plot2 = 1.8 * plot2 / display_scale
            axis.plot(
                row["plot_time"], plot1 + baseline, color="tab:blue",
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
            status = "accepted" if accepted else "rejected (display-normalized)"
            row_labels.append(
                f"{row['station_id']}  CC={row['cc']:.2f}  "
                f"shift={display_shift(row):+.2f}s  {status}"
            )
        axis.axvspan(-10.0, 20.0, color="0.8", alpha=0.25)
        axis.axvline(0.0, color="0.3", linewidth=0.6)
        axis.set_yticks(baselines, row_labels, fontsize=7)
        for tick, row in zip(axis.get_yticklabels(), page_rows):
            tick.set_color("0.15" if bool(row["good"]) else "0.38")
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, loc="upper right", fontsize=7, framealpha=0.85)
        axis.set_xlabel(f"Time relative to picked {phase} (s)")
        axis.set_title(
            f"{pair.label} {phase}: event {pair.event1.event_id} blue vs "
            f"{pair.event2.event_id} red; rows {start + 1}–{start + len(page_rows)} of {len(plotted)}; "
            "solid traces; dashed lines are accepted AIC picks"
        )
        suffix = "" if len(plotted) <= MAX_TRACES_PER_PHASE_PLOT else f"_{page_number:02d}"
        figure.savefig(
            output / "phase_plots" / f"{pair.label}_{phase}{suffix}.png",
            dpi=180,
            bbox_inches="tight",
        )
        plt.close(figure)


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
                f"{row['residual_shift_seconds']:+.2f}",
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
    shift_limit_seconds: float | None = None,
) -> None:
    good = [row for row in rows if row["good"]]
    if not good:
        return
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
    colors = {"P": "tab:blue", "PKiKP": "tab:red", "PKP": "tab:purple"}
    for phase in PHASES:
        phase_rows = [row for row in good if row["phase"] == phase]
        if not phase_rows:
            continue
        axis1.scatter(
            [row["azimuth_degrees"] for row in phase_rows],
            [display_shift(row) for row in phase_rows],
            label=phase,
            s=28,
            color=colors[phase],
            alpha=0.85,
        )
        axis2.scatter(
            [row["epicentral_distance_degrees"] for row in phase_rows],
            [display_shift(row) for row in phase_rows],
            label=phase,
            s=28,
            color=colors[phase],
            alpha=0.85,
        )
    for axis in (axis1, axis2):
        axis.axhline(reference_shift, color="0.5", linewidth=0.8, linestyle="--")
        if shift_limit_seconds is not None:
            axis.set_ylim(-float(shift_limit_seconds), float(shift_limit_seconds))
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
    if time_shift_source not in {"computed", "workbook", "picked"}:
        raise base.AnalysisError(
            "time_shift_source must be 'computed', 'workbook', or 'picked'"
        )
    configured_time_shift_workbook = config.get("time_shift_workbook")
    time_shift_workbook = (
        Path(str(configured_time_shift_workbook))
        if configured_time_shift_workbook
        else None
    )
    threshold = float(config["selection_correlation_threshold"])
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
    preapply_time_shifts = time_shift_source == "workbook"
    lag_search_seconds = (
        float(config["residual_lag_search_seconds"])
        if preapply_time_shifts or time_shift_source == "picked"
        else float(config["lag_search_seconds"])
    )

    phase_windows = {phase: [-10.0, 20.0] for phase in PHASES}
    phase_windows["P"] = list(config["correlation_window_seconds"])
    phase_windows["PKiKP"] = [-5.0, 10.0]
    plot_windows = {phase: [-20.0, 60.0] for phase in PHASES}
    plot_windows["P"] = list(config["plot_window_seconds"])

    measurement_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    phase_summary_rows: list[dict[str, Any]] = []
    median_summary_rows: list[dict[str, Any]] = []
    residual_geometry_rows: list[dict[str, Any]] = []

    total_pairs = len(pair_labels)
    print(
        f"Multiphase run: {total_pairs} pairs, {len(PHASES)} measured phases, "
        f"time_shift_source={time_shift_source}",
        flush=True,
    )

    for pair_number, pair_label in enumerate(pair_labels, start=1):
        pair_start = time.perf_counter()
        pair = pairs[pair_label]
        index1 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event1))
        index2 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event2))
        excluded = base.excluded_station_codes(config)
        station_ids = [
            station_id
            for station_id in sorted(set(index1).intersection(index2))
            if not base.station_is_excluded(station_id, excluded)
        ]
        pair_plot_rows: list[dict[str, Any]] = []
        trace_cache: dict[str, tuple[Path, Path, base.ProcessedTrace, base.ProcessedTrace]] = {}
        pair_exception_start = len(exception_rows)
        print(
            f"Pair {pair_number}/{total_pairs} {pair_label}: "
            f"{len(station_ids)} common stations; measuring phases...",
            flush=True,
        )

        for station_number, station_id in enumerate(station_ids, start=1):
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
                    pick1_offset, pick1_snr, pick1_accepted, pick1_reason = automatic_aic_pick(
                        path1, arrival1, automatic_pick_trace_cache
                    )
                    pick2_offset, pick2_snr, pick2_accepted, pick2_reason = automatic_aic_pick(
                        path2, arrival2, automatic_pick_trace_cache
                    )
                    if not (pick1_accepted and pick2_accepted):
                        plot_arrival1 = arrival1 + (pick1_offset or 0.0)
                        plot_arrival2 = arrival2 + (pick2_offset or 0.0)
                        plot_time, plot1, plot2, plot_scale1, plot_scale2 = extract_normalized_plot(
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
                                "epicentral_distance_degrees": 0.5 * (distance1 + distance2),
                                "azimuth_degrees": azimuth,
                                "takeoff_angle_degrees": takeoff,
                                "predicted_travel_time1_s": travel1,
                                "predicted_travel_time2_s": travel2,
                                "lag_seconds": 0.0,
                                "applied_time_shift_seconds": 0.0,
                                "preapplied_time_shift": False,
                                "residual_lag_seconds": 0.0,
                                "total_shift_seconds": 0.0,
                                "cc": math.nan,
                                "boundary": False,
                                "phase_geometry_usable": phase_is_usable_for_shift(
                                    phase, 0.5 * (distance1 + distance2)
                                ),
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
                                "trace1_path": str(path1),
                                "trace2_path": str(path2),
                                "plot_scale1_correlation_window_rms": plot_scale1,
                                "plot_scale2_correlation_window_rms": plot_scale2,
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
                        raise base.AnalysisError("Accepted automatic phase pick lacks an offset")
                    correlation_arrival1 = arrival1 + pick1_offset
                    correlation_arrival2 = arrival2 + pick2_offset
                    applied_time_shift = pick2_offset - pick1_offset
                    lag, cc, boundary, _, _ = base.signed_lag_correlation(
                        trace1,
                        trace2,
                        correlation_arrival1,
                        correlation_arrival2,
                        phase_windows[phase],
                        lag_search_seconds,
                    )
                    plot_time, plot1, plot2, plot_scale1, plot_scale2 = extract_normalized_plot(
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
                    distance_degrees = 0.5 * (distance1 + distance2)
                    phase_geometry_usable = phase_is_usable_for_shift(
                        phase, distance_degrees
                    )
                    good = bool(cc >= threshold and not boundary and phase_geometry_usable)
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
                        "lag_seconds": total_shift,
                        "applied_time_shift_seconds": applied_time_shift,
                        "preapplied_time_shift": False,
                        "residual_lag_seconds": float(lag),
                        "total_shift_seconds": total_shift,
                        "cc": float(cc),
                        "boundary": bool(boundary),
                        "phase_geometry_usable": phase_geometry_usable,
                        "good": good,
                        "automatic_pick1_offset_s": pick1_offset,
                        "automatic_pick1_snr": pick1_snr,
                        "automatic_pick1_accepted": pick1_accepted,
                        "automatic_pick1_reason": pick1_reason,
                        "automatic_pick2_offset_s": pick2_offset,
                        "automatic_pick2_snr": pick2_snr,
                        "automatic_pick2_accepted": pick2_accepted,
                        "automatic_pick2_reason": pick2_reason,
                        "trace1_path": str(path1),
                        "trace2_path": str(path2),
                        "plot_scale1_correlation_window_rms": plot_scale1,
                        "plot_scale2_correlation_window_rms": plot_scale2,
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

        # Computed mode uses a two-stage search.  The first pass above finds
        # the broad pair shift.  Re-run every station/phase around that common
        # shift using the configured residual window, then retain only the
        # fine residuals for location and station-differential products.
        computed_median_shift = (
            float(np.median([row["total_shift_seconds"] for row in pair_plot_rows if row["good"]]))
            if any(row["good"] for row in pair_plot_rows)
            else math.nan
        )
        if time_shift_source == "computed" and math.isfinite(computed_median_shift):
            for row in pair_plot_rows:
                try:
                    _, _, trace1, trace2 = trace_cache[row["station_id"]]
                    arrival1, _, travel1, takeoff = phase_arrival(
                        model, pair.event1, trace1.station_latitude, trace1.station_longitude,
                        row["phase"], arrival_cache,
                    )
                    arrival2, _, travel2, _ = phase_arrival(
                        model, pair.event2, trace2.station_latitude, trace2.station_longitude,
                        row["phase"], arrival_cache,
                    )
                    fine_lag, cc, boundary, _, _ = base.signed_lag_correlation(
                        trace1,
                        trace2,
                        arrival1,
                        arrival2 + computed_median_shift,
                        phase_windows[row["phase"]],
                        float(config["residual_lag_search_seconds"]),
                    )
                    plot_time, plot1, plot2, plot_scale1, plot_scale2 = extract_normalized_plot(
                        trace1,
                        trace2,
                        arrival1,
                        arrival2 + computed_median_shift,
                        fine_lag,
                        plot_windows[row["phase"]],
                        phase_windows[row["phase"]],
                    )
                    row.update(
                        {
                            "lag_seconds": computed_median_shift + float(fine_lag),
                            "applied_time_shift_seconds": computed_median_shift,
                            "fine_search_center_seconds": computed_median_shift,
                            "residual_lag_seconds": float(fine_lag),
                            "total_shift_seconds": computed_median_shift + float(fine_lag),
                            "cc": float(cc),
                            "boundary": bool(boundary),
                            "good": bool(
                                cc >= threshold
                                and not boundary
                                and row["phase_geometry_usable"]
                            ),
                            "predicted_travel_time1_s": travel1,
                            "predicted_travel_time2_s": travel2,
                            "takeoff_angle_degrees": takeoff,
                            "plot_scale1_correlation_window_rms": plot_scale1,
                            "plot_scale2_correlation_window_rms": plot_scale2,
                        }
                    )
                    row["plot_time"] = plot_time
                    row["plot1"] = plot1
                    row["plot2"] = plot2
                    row["automatic_pick2_plot_time"] = (
                        float(row["automatic_pick2_offset_s"])
                        - computed_median_shift
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
        else:
            median_shift = computed_median_shift
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
            plot_phase_waveforms(output, pair, phase, pair_plot_rows, threshold)
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
            float(config["residual_lag_search_seconds"])
            if time_shift_source == "computed"
            else lag_search_seconds,
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
                "time_shift_workbook": str(time_shift_workbook) if time_shift_workbook else "",
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
                "phase_selection_rules": {
                    "PKiKP": "epicentral_distance_degrees > 100",
                    "PKIKP": "marked on plots only; not measured or fit",
                },
                "automatic_plot_qc_picks": {
                    "phases": list(PHASES),
                    "method": "AIC minimum after 0.7-4 Hz zero-phase filtering",
                    "search_seconds_relative_to_predicted_arrival": AUTOMATIC_PICK_SEARCH_SECONDS,
                    "minimum_snr": AUTOMATIC_PICK_MIN_SNR,
                    "maximum_absolute_offset_seconds": AUTOMATIC_PICK_MAX_OFFSET_SECONDS,
                    "use": "correlation-window centers and plot markers; the residual lag remains the waveform measurement",
                },
                "pairs": pair_labels,
                "phases": PHASES,
                "marked_phases": MARKED_PHASES,
                "excluded_stations": sorted(base.excluded_station_codes(config)),
                "summary_method": "pair median common shift; no L1 location fit",
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
                    f"{row['residual_shift_seconds']:+.2f}",
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
        choices=("computed", "workbook"),
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
