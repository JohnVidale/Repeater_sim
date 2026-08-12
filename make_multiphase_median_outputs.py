from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from obspy.taup import TauPyModel

import compare_repeater_pwaves as base


PHASES = ("P", "PcP", "ScP", "PKiKP", "PKP")
MARKED_PHASES = ("P", "pP", "sP", "PP", "PcP", "ScP", "PKP", "PKiKP", "PKIKP")
PHASE_MARKERS = {"P": "o", "PcP": "s", "ScP": "^", "PKiKP": "D", "PKP": "P"}


def phase_is_usable_for_shift(phase: str, distance_degrees: float) -> bool:
    """Return whether this phase/station geometry should enter shift summaries."""
    if phase in {"PcP", "ScP"}:
        return distance_degrees < 40.0
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
) -> tuple[float | None, float, float | None, float | None]:
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
        return None, distance, None, None
    exact = [arrival for arrival in arrivals if arrival.name == phase]
    if exact:
        arrivals = exact
    arrival = arrivals[0]
    return (
        float(event.origin) + float(arrival.time),
        distance,
        float(arrival.time),
        float(arrival.takeoff_angle),
    )


def extract_normalized_plot(
    trace1: base.ProcessedTrace,
    trace2: base.ProcessedTrace,
    arrival1: float,
    arrival2: float,
    lag_seconds: float,
    window: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    relative = base.window_times(window, trace1.sampling_hz)
    first = base.extract_relative(trace1, arrival1, relative)
    second = base.extract_relative(trace2, arrival2, relative + lag_seconds)
    first = first - np.mean(first)
    second = second - np.mean(second)
    scale = max(float(np.sqrt(np.mean(first * first))), float(np.sqrt(np.mean(second * second))))
    if scale <= 0.0 or not math.isfinite(scale):
        scale = 1.0
    return relative, first / scale, second / scale


def display_shift(row: dict[str, Any]) -> float:
    preapplied = row.get("preapplied_time_shift")
    if isinstance(preapplied, str):
        preapplied = preapplied.strip().lower() == "true"
    if preapplied:
        return float(row["residual_lag_seconds"])
    return float(row["lag_seconds"])


def plot_phase_waveforms(
    output: Path,
    pair: base.Pair,
    phase: str,
    rows: list[dict[str, Any]],
    threshold: float,
) -> None:
    good = sorted(
        [row for row in rows if row["phase"] == phase and row["good"]],
        key=lambda row: row["epicentral_distance_degrees"],
        reverse=True,
    )
    if not good:
        return
    height = max(5.0, 1.0 + 0.45 * len(good))
    figure, axis = plt.subplots(figsize=(12, height), constrained_layout=True)
    for index, row in enumerate(good):
        baseline = (len(good) - 1 - index) * 5.0
        axis.plot(row["plot_time"], row["plot1"] + baseline, color="tab:blue", linewidth=0.7)
        axis.plot(row["plot_time"], row["plot2"] + baseline, color="tab:red", linewidth=0.7)
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
        axis.text(
            x_min + 0.01 * (x_max - x_min),
            baseline + 2.1,
            (
                f"{row['station_id']} {row['epicentral_distance_degrees']:.1f}° "
                f"az={row['azimuth_degrees']:.0f}\n"
                f"CC={row['cc']:.2f} shift={display_shift(row):+.2f}s"
            ),
            fontsize=7,
            va="top",
        )
    axis.axvspan(-10.0, 20.0, color="0.8", alpha=0.25)
    axis.axvline(0.0, color="0.3", linewidth=0.6)
    axis.set_yticks([])
    axis.set_xlabel(f"Time relative to predicted {phase} (s)")
    axis.set_title(
        f"{pair.label} {phase}: event {pair.event1.event_id} blue vs "
        f"{pair.event2.event_id} red; CC >= {threshold:g}"
    )
    figure.savefig(output / "phase_plots" / f"{pair.label}_{phase}.png", dpi=180, bbox_inches="tight")
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
    y_label = (
        "residual shift after pre-applied time shift (s)"
        if preapplied
        else "event2 shift relative to prediction (s)"
    )
    title_suffix = (
        "dashed line = 0 s residual"
        if preapplied
        else f"dashed line = median {median_shift:+.2f} s"
    )
    figure, (axis1, axis2) = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    colors = {"P": "tab:blue", "PcP": "tab:orange", "ScP": "tab:green", "PKiKP": "tab:red", "PKP": "tab:purple"}
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
) -> Path:
    config = base.load_json(Path("analysis_config.json"))
    time_shift_source = str(config.get("time_shift_source", "computed"))
    if time_shift_source not in {"computed", "workbook"}:
        raise base.AnalysisError(
            "time_shift_source must be either 'computed' or 'workbook'"
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
    pair_labels = [str(label) for label in config["pairs"]]
    pairs = base.resolve_catalog(
        Path(config["catalog_path"]),
        pair_labels,
        float(config["coordinate_tolerance_degrees"]),
        float(config["coordinate_tolerance_depth_km"]),
    )
    waveform_root = Path(config["waveform_root"])
    workbook_time_shifts: dict[str, float] = {}
    if time_shift_source == "workbook":
        workbook_time_shifts = read_workbook_time_shifts(
            time_shift_workbook or Path(config["catalog_path"])
        )
    preapply_time_shifts = time_shift_source == "workbook"
    lag_search_seconds = (
        float(config["residual_lag_search_seconds"])
        if preapply_time_shifts
        else float(config["lag_search_seconds"])
    )

    phase_windows = {phase: [-10.0, 20.0] for phase in PHASES}
    phase_windows["P"] = list(config["correlation_window_seconds"])
    plot_windows = {phase: [-20.0, 60.0] for phase in PHASES}
    plot_windows["P"] = list(config["plot_window_seconds"])

    measurement_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    phase_summary_rows: list[dict[str, Any]] = []
    median_summary_rows: list[dict[str, Any]] = []
    residual_geometry_rows: list[dict[str, Any]] = []

    for pair_label in pair_labels:
        pair = pairs[pair_label]
        print(f"PAIR {pair_label}", flush=True)
        index1 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event1))
        index2 = base.index_bhz_traces(base.event_directory(waveform_root, pair.event2))
        station_ids = sorted(set(index1).intersection(index2))
        pair_plot_rows: list[dict[str, Any]] = []

        for station_id in station_ids:
            try:
                path1, path2 = base.choose_trace_pair(
                    index1[station_id],
                    index2[station_id],
                    float(config["station_coordinate_tolerance_degrees"]),
                )
                trace1 = base.preprocess_trace(path1, config)
                trace2 = base.preprocess_trace(path2, config)
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
                    applied_time_shift = (
                        workbook_time_shifts[pair_label]
                        if preapply_time_shifts and pair_label in workbook_time_shifts
                        else 0.0
                    )
                    arrival1, distance1, travel1, takeoff = phase_arrival(
                        model, pair.event1, trace1.station_latitude, trace1.station_longitude, phase
                    )
                    arrival2, distance2, travel2, _ = phase_arrival(
                        model, pair.event2, trace2.station_latitude, trace2.station_longitude, phase
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
                    lag, cc, boundary, _, _ = base.signed_lag_correlation(
                        trace1,
                        trace2,
                        arrival1,
                        arrival2 + applied_time_shift,
                        phase_windows[phase],
                        lag_search_seconds,
                    )
                    plot_time, plot1, plot2 = extract_normalized_plot(
                        trace1,
                        trace2,
                        arrival1,
                        arrival2 + applied_time_shift,
                        lag,
                        plot_windows[phase],
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
                        )
                        if marked_arrival is None:
                            continue
                        relative_marked_time = float(marked_arrival - arrival1)
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
                        "preapplied_time_shift": preapply_time_shifts,
                        "residual_lag_seconds": float(lag),
                        "total_shift_seconds": total_shift,
                        "cc": float(cc),
                        "boundary": bool(boundary),
                        "phase_geometry_usable": phase_geometry_usable,
                        "good": good,
                        "trace1_path": str(path1),
                        "trace2_path": str(path2),
                    }
                    measurement_rows.append(row)
                    pair_plot_row = dict(row)
                    pair_plot_row.update(
                        {
                            "plot_time": plot_time,
                            "plot1": plot1,
                            "plot2": plot2,
                            "marked_phase_times": marked_phase_times,
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

        good_rows = [row for row in pair_plot_rows if row["good"]]
        computed_median_shift = (
            float(np.median([row["total_shift_seconds"] for row in good_rows]))
            if good_rows
            else math.nan
        )
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
        plot_shift_summary(output, pair_label, pair_plot_rows, median_shift, lag_search_seconds)
        plot_median_residual_geometry(
            output,
            pair_label,
            [row for row in residual_geometry_rows if row["pair_label"] == pair_label],
            median_shift,
            threshold,
        )

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
                "config_path": str(Path("analysis_config.json").resolve()),
                "correlation_threshold": threshold,
                "time_shift_source": time_shift_source,
                "time_shift_workbook": str(time_shift_workbook) if time_shift_workbook else "",
                "preapplied_time_shifts": preapply_time_shifts,
                "lag_search_seconds": lag_search_seconds,
                "phase_selection_rules": {
                    "PcP": "epicentral_distance_degrees < 40",
                    "ScP": "epicentral_distance_degrees < 40",
                    "PKiKP": "epicentral_distance_degrees > 100",
                    "PKIKP": "marked on plots only; not measured or fit",
                },
                "pairs": pair_labels,
                "phases": PHASES,
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
    args = parser.parse_args()
    output = run()
    print(f"OUTPUT {output.resolve()}")
    print(f"phase plots {len(list((output / 'phase_plots').glob('*.png')))}")
    print(f"residual plots {len(list((output / 'median_residual_geometry_plots').glob('*.png')))}")


if __name__ == "__main__":
    main()
