#!/usr/bin/env python3
"""Move timing and differential-location fields from ``pairs`` to ``aligned_pairs``."""
from __future__ import annotations

import argparse
import shutil
import math
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from aligned_pairs import header_map, refresh_reference_times

HEADERS = [
    "label", "event1", "event2", "pick_align_shift_s",
    "same_location_event2_minus_event1_shift_s", "same_location_available",
    "relative_location_event2_minus_event1_shift_s", "relative_location_north_m",
    "relative_location_east_m", "relative_location_phase_set", "relative_location_n",
    "relative_location_3d_m", "relative_location_median_abs_residual_s",
    "relative_location_rms_residual_s", "relative_location_available",
    "same_location_event1_reference_time", "same_location_event1_lat", "same_location_event1_lon",
    "same_location_event2_reference_time", "same_location_event2_lat", "same_location_event2_lon",
    "relative_location_event1_reference_time", "relative_location_event1_lat", "relative_location_event1_lon",
    "relative_location_event2_reference_time", "relative_location_event2_lat", "relative_location_event2_lon",
]
REMOVE = {
    "event2_minus_event1_delta_lat", "event2_minus_event1_delta_lon", "pick align shift", "new time shift",
    "relative_location_phase_set", "relative_location_n", "event2_minus_event1_delta_time_s",
    "event2_minus_event1_3d_km", "relative_location_median_abs_residual_s", "relative_location_rms_residual_s",
}

def value(sheet, header, row, name):
    col = header.get(name)
    return sheet.cell(row, col).value if col else None

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workbook", type=Path, default=Path("ICevents_working.xlsx"))
    args = p.parse_args()
    backup = args.workbook.parent / "archive" / f"{args.workbook.stem}_before_pairs_alignment_schema_{datetime.now():%Y%m%d_%H%M%S}{args.workbook.suffix}"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(args.workbook, backup)
    wb = load_workbook(args.workbook)
    try:
        pairs, aligned = wb["pairs"], wb["aligned_pairs"]
        ph, ah = header_map(pairs), header_map(aligned)
        pair_by_label = {str(pairs.cell(r, ph["label"]).value).strip(): r for r in range(2, pairs.max_row + 1) if pairs.cell(r, ph["label"]).value is not None}
        old_rows = []
        for r in range(2, aligned.max_row + 1):
            label = aligned.cell(r, ah["label"]).value
            if label is None: continue
            label = str(label).strip(); pr = pair_by_label[label]
            old_rows.append({name: value(aligned, ah, r, name) for name in ah} | {
                "relative_location_north_m": value(aligned, ah, r, "relative_location_north_m") if "relative_location_north_m" in ah else (None if value(pairs, ph, pr, "event2_minus_event1_delta_lat") is None else 111195.0 * float(value(pairs, ph, pr, "event2_minus_event1_delta_lat"))),
                "relative_location_east_m": value(aligned, ah, r, "relative_location_east_m") if "relative_location_east_m" in ah else (None if value(pairs, ph, pr, "event2_minus_event1_delta_lon") is None else 111195.0 * math.cos(math.radians(float(value(pairs, ph, pr, "lat")))) * float(value(pairs, ph, pr, "event2_minus_event1_delta_lon"))),
                "relative_location_3d_m": value(aligned, ah, r, "relative_location_3d_m") if "relative_location_3d_m" in ah else (None if value(aligned, ah, r, "relative_location_3d_km") is None else 1000.0 * float(value(aligned, ah, r, "relative_location_3d_km"))),
                "relative_location_median_abs_residual_s": value(aligned, ah, r, "relative_location_median_abs_residual_s"),
                "relative_location_rms_residual_s": value(aligned, ah, r, "relative_location_rms_residual_s"),
            })
        del wb["aligned_pairs"]
        aligned = wb.create_sheet("aligned_pairs")
        aligned.append(HEADERS)
        for values in old_rows:
            aligned.append([values.get(name) for name in HEADERS])
        for cell in aligned[1]:
            cell.fill = PatternFill("solid", fgColor="1F4E78"); cell.font = Font(color="FFFFFF", bold=True)
        aligned.freeze_panes = "A2"; aligned.auto_filter.ref = aligned.dimensions
        for r in range(2, aligned.max_row + 1): refresh_reference_times(wb, r)
        ph = header_map(pairs)
        for col in sorted((ph[name] for name in REMOVE if name in ph), reverse=True): pairs.delete_cols(col)
        wb.save(args.workbook)
    finally:
        wb.close()
    print(f"backup={backup}")
    print(f"aligned_pairs_rows={len(old_rows)}")

if __name__ == "__main__": main()
