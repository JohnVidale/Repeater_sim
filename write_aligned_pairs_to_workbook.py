#!/usr/bin/env python3
"""Write explicit global-alignment event references to ``aligned_pairs``.

The raw event ``TIME`` values remain unchanged on the ``events`` sheet.  This
writer creates two analysis-reference hypotheses per pair:

* ``same_location``: both events use the pair centroid and the workbook's
  ``new time shift``;
* ``relative_location``: events use the fitted horizontal offset and its
  corresponding fitted differential origin-time shift.

In both hypotheses, ``pick align shift`` is applied once to both events.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from aligned_pairs import refresh_reference_times


DEFAULT_WORKBOOK = Path("ICevents_working.xlsx")
SHEET_NAME = "aligned_pairs"
TIME_FORMAT = "yyyy-mm-dd hh:mm:ss.000"

HEADERS = [
    "label", "event1", "event2", "ehb_depth_km", "raw_event1_time",
    "raw_event2_time", "pick_align_shift_s", "same_location_event2_minus_event1_shift_s",
    "same_location_available",
    "relative_location_event2_minus_event1_shift_s", "relative_location_phase_set",
    "relative_location_n", "relative_location_3d_km", "relative_location_available",
    "same_location_event1_reference_time", "same_location_event1_lat",
    "same_location_event1_lon", "same_location_event2_reference_time",
    "same_location_event2_lat", "same_location_event2_lon",
    "relative_location_event1_reference_time", "relative_location_event1_lat",
    "relative_location_event1_lon", "relative_location_event2_reference_time",
    "relative_location_event2_lat", "relative_location_event2_lon",
]


def headers(sheet) -> dict[str, int]:
    return {str(cell.value).strip(): index for index, cell in enumerate(sheet[1]) if cell.value is not None}


def as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is not None:
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
    return result


def required(row: tuple[Any, ...], index: dict[str, int], name: str) -> Any:
    value = row[index[name]]
    if value is None:
        raise ValueError(f"Missing {name}")
    return value


def build_rows(workbook_path: Path) -> list[list[Any]]:
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        pairs = workbook["pairs"]
        events = workbook["events"]
        pair_index = headers(pairs)
        event_index = headers(events)
        pair_required = {
            "label", "index1", "index2", "lat", "lon", "depth", "pick align shift", "new time shift",
        }
        event_required = {"INDEX", "TIME"}
        if missing := pair_required - pair_index.keys():
            raise ValueError(f"pairs sheet missing columns: {sorted(missing)}")
        if missing := event_required - event_index.keys():
            raise ValueError(f"events sheet missing columns: {sorted(missing)}")
        event_times = {
            int(row[event_index["INDEX"]]): as_datetime(row[event_index["TIME"]])
            for row in events.iter_rows(min_row=2, values_only=True)
            if row[event_index["INDEX"]] is not None
        }
        rows: list[list[Any]] = []
        for pair in pairs.iter_rows(min_row=2, values_only=True):
            label = pair[pair_index["label"]]
            if label is None:
                continue
            event1 = int(required(pair, pair_index, "index1"))
            event2 = int(required(pair, pair_index, "index2"))
            raw1, raw2 = event_times[event1], event_times[event2]
            common_value = pair[pair_index["pick align shift"]]
            same_delta_value = pair[pair_index["new time shift"]]
            same_available = common_value is not None and same_delta_value is not None
            common = float(common_value) if common_value is not None else None
            same_delta = float(same_delta_value) if same_delta_value is not None else None
            lat = float(required(pair, pair_index, "lat"))
            lon = float(required(pair, pair_index, "lon"))
            depth = float(required(pair, pair_index, "depth"))
            offset_keys = {"event2_minus_event1_delta_lat", "event2_minus_event1_delta_lon", "event2_minus_event1_delta_time_s"}
            available = offset_keys <= pair_index.keys() and all(pair[pair_index[key]] is not None for key in offset_keys)
            delta_lat = float(pair[pair_index["event2_minus_event1_delta_lat"]]) if available else None
            delta_lon = float(pair[pair_index["event2_minus_event1_delta_lon"]]) if available else None
            relative_delta = float(pair[pair_index["event2_minus_event1_delta_time_s"]]) if available else None
            phase_set = pair[pair_index["relative_location_phase_set"]] if "relative_location_phase_set" in pair_index else None
            count = pair[pair_index["relative_location_n"]] if "relative_location_n" in pair_index else None
            separation = pair[pair_index["event2_minus_event1_3d_km"]] if "event2_minus_event1_3d_km" in pair_index else None
            same1 = raw1 + timedelta(seconds=common) if same_available else None
            same2 = raw2 + timedelta(seconds=common + same_delta) if same_available else None
            relative_available = bool(available and common is not None)
            relative1 = raw1 + timedelta(seconds=common) if relative_available else None
            relative2 = raw2 + timedelta(seconds=common + relative_delta) if relative_available else None
            rows.append([
                str(label), event1, event2, depth, raw1, raw2, common, same_delta, bool(same_available), relative_delta,
                phase_set, count, separation, bool(relative_available), same1, lat if same_available else None,
                lon if same_available else None, same2, lat if same_available else None, lon if same_available else None,
                relative1, lat - 0.5 * delta_lat if relative_available else None,
                lon - 0.5 * delta_lon if relative_available else None, relative2,
                lat + 0.5 * delta_lat if relative_available else None, lon + 0.5 * delta_lon if relative_available else None,
            ])
        return rows
    finally:
        workbook.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_aligned_pairs(workbook_path: Path, replace: bool = False) -> Path:
    backup = workbook_path.parent / "archive" / f"{workbook_path.stem}_before_aligned_pairs_{datetime.now().strftime('%Y%m%d_%H%M%S')}{workbook_path.suffix}"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(workbook_path, backup)
    workbook = load_workbook(workbook_path)
    try:
        if SHEET_NAME in workbook.sheetnames:
            # The normalized schema keeps source alignment values here.  A
            # refresh only regenerates references from events plus those values.
            sheet = workbook[SHEET_NAME]
            for row in range(2, sheet.max_row + 1):
                refresh_reference_times(workbook, row)
            header = headers(sheet)
            for name in (
                "same_location_event1_reference_time", "same_location_event2_reference_time",
                "relative_location_event1_reference_time", "relative_location_event2_reference_time",
            ):
                for row in range(2, sheet.max_row + 1):
                    sheet.cell(row, header[name] + 1).number_format = TIME_FORMAT
            workbook.save(workbook_path)
            return backup
        rows = build_rows(workbook_path)
        sheet = workbook.create_sheet(SHEET_NAME)
        sheet.append(HEADERS)
        for row in rows:
            sheet.append(row)
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, datetime):
                    cell.number_format = TIME_FORMAT
        for column in range(1, len(HEADERS) + 1):
            width = max(len(str(sheet.cell(row=1, column=column).value)), 12)
            sheet.column_dimensions[chr(64 + column) if column <= 26 else "Z"].width = min(width + 2, 32)
        workbook.save(workbook_path)
    finally:
        workbook.close()
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    before = sha256(args.workbook)
    backup = write_aligned_pairs(args.workbook, replace=args.replace)
    print(f"backup={backup}")
    print(f"input_sha256={before}")


if __name__ == "__main__":
    main()
