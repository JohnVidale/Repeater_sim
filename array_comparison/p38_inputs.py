"""Workbook contract for the P38 YKA/ILAR comparison."""
from __future__ import annotations

import pandas as pd

import run_isolated_array_comparison_baseline as baseline

PAIR, EVENT1, EVENT2 = "P38", 732, 750


def read_inputs() -> dict[str, object]:
    """Read only the declared P38 fields from ``pairs`` and ``aligned_pairs``."""
    pairs = pd.read_excel(baseline.CURRENT_WORKBOOK, sheet_name="pairs")
    pair_rows = pairs[pairs["label"].astype(str).eq(PAIR)]
    if len(pair_rows) != 1:
        raise ValueError(f"Expected one {PAIR} row, found {len(pair_rows)}")
    pair = pair_rows.iloc[0]
    aligned = pd.read_excel(baseline.CURRENT_WORKBOOK, sheet_name="aligned_pairs")
    rows = aligned[aligned["label"].astype(str).eq(PAIR)]
    if len(rows) != 1:
        raise ValueError(f"Expected one {PAIR} aligned_pairs row, found {len(rows)}")
    row = rows.iloc[0]
    required = (
        "relative_location_north_m", "relative_location_east_m", "relative_location_phase_set",
        "relative_location_n", "relative_location_3d_m", "same_location_event1_reference_time",
        "same_location_event1_lat", "same_location_event1_lon", "same_location_event2_reference_time",
        "same_location_event2_lat", "same_location_event2_lon", "relative_location_event1_reference_time",
        "relative_location_event1_lat", "relative_location_event1_lon", "relative_location_event2_reference_time",
        "relative_location_event2_lat", "relative_location_event2_lon",
    )
    missing = [name for name in required if pd.isna(row[name])]
    if missing:
        raise ValueError(f"{PAIR} has incomplete aligned_pairs fields: {', '.join(missing)}")
    def events(prefix: str) -> dict[int, dict[str, object]]:
        return {event: {"time": str(row[f"{prefix}_event{number}_reference_time"]),
                        "lat": float(row[f"{prefix}_event{number}_lat"]),
                        "lon": float(row[f"{prefix}_event{number}_lon"])}
                for event, number in ((EVENT1, 1), (EVENT2, 2))}
    return {
        "pair": PAIR, "event1": EVENT1, "event2": EVENT2,
        "same_location_events": events("same_location"),
        "relative_location_events": events("relative_location"),
        "centroid_lat": float(pair["lat"]), "centroid_lon": float(pair["lon"]),
        "centroid_depth_km": float(pair["depth"]),
        "new_time_shift_s": float(row["same_location_event2_minus_event1_shift_s"]),
        "pick_align_shift_s": float(row["pick_align_shift_s"]),
        "north_m": float(row["relative_location_north_m"]), "east_m": float(row["relative_location_east_m"]),
        "separation_3d_m": float(row["relative_location_3d_m"]),
        "phase_set": str(row["relative_location_phase_set"]), "location_n": int(row["relative_location_n"]),
    }


def case_events(inputs: dict[str, object], differential: bool) -> dict[int, dict[str, object]]:
    selected = inputs["relative_location_events" if differential else "same_location_events"]
    return {event: {**values, "depth": inputs["centroid_depth_km"]} for event, values in selected.items()}
