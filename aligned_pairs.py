"""Shared accessors for the ``aligned_pairs`` workbook contract.

``pairs`` owns common EHB coordinates and depth.  ``events`` owns raw catalog
times.  This module keeps all alignment and differential-location quantities
on ``aligned_pairs`` and refreshes its explicit reference times after a timing
or location update.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def header_map(sheet) -> dict[str, int]:
    return {str(cell.value).strip(): cell.column for cell in sheet[1] if cell.value is not None}


def event_times(workbook) -> dict[int, datetime]:
    sheet = workbook["events"]
    h = header_map(sheet)
    result = {}
    for r in range(2, sheet.max_row + 1):
        index = sheet.cell(r, h["INDEX"]).value
        if index is None: continue
        value = sheet.cell(r, h["TIME"]).value
        result[int(index)] = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    return result


def aligned_rows(sheet) -> dict[str, int]:
    h = header_map(sheet)
    return {str(sheet.cell(r, h["label"]).value).strip(): r
            for r in range(2, sheet.max_row + 1) if sheet.cell(r, h["label"]).value is not None}


def refresh_reference_times(workbook, row: int) -> None:
    """Regenerate the four analysis reference times for one aligned-pairs row."""
    sheet = workbook["aligned_pairs"]
    h = header_map(sheet)
    times = event_times(workbook)
    event1 = int(sheet.cell(row, h["event1"]).value)
    event2 = int(sheet.cell(row, h["event2"]).value)
    pick = sheet.cell(row, h["pick_align_shift_s"]).value
    same = sheet.cell(row, h["same_location_event2_minus_event1_shift_s"]).value
    relative = sheet.cell(row, h["relative_location_event2_minus_event1_shift_s"]).value
    for name in ("same_location_event1_reference_time", "same_location_event2_reference_time",
                 "relative_location_event1_reference_time", "relative_location_event2_reference_time"):
        sheet.cell(row, h[name]).value = None
    if pick is not None and same is not None:
        sheet.cell(row, h["same_location_event1_reference_time"]).value = times[event1] + timedelta(seconds=float(pick))
        sheet.cell(row, h["same_location_event2_reference_time"]).value = times[event2] + timedelta(seconds=float(pick) + float(same))
    if pick is not None and relative is not None:
        sheet.cell(row, h["relative_location_event1_reference_time"]).value = times[event1] + timedelta(seconds=float(pick))
        sheet.cell(row, h["relative_location_event2_reference_time"]).value = times[event2] + timedelta(seconds=float(pick) + float(relative))
