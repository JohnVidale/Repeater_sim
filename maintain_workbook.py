#!/usr/bin/env python3
"""One entry point for routine ``ICevents_working.xlsx`` maintenance.

Use one action at a time.  Each delegated writer retains its own backup and
provenance behavior.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("refresh-references", "format", "write-offsets", "write-time-shifts"))
    p.add_argument("--workbook", type=Path, default=ROOT / "ICevents_working.xlsx")
    p.add_argument("--relative-locations", type=Path)
    p.add_argument("--median-summary", type=Path)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    commands = {
        "refresh-references": ["write_aligned_pairs_to_workbook.py", "--workbook", str(args.workbook), "--replace"],
        "format": ["format_working_workbook.py", "--workbook", str(args.workbook)],
    }
    if args.action == "write-offsets":
        if args.relative_locations is None: p.error("write-offsets requires --relative-locations")
        commands[args.action] = ["write_pair_relative_offsets_to_workbook.py", "--workbook", str(args.workbook), "--relative-locations", str(args.relative_locations)]
    if args.action == "write-time-shifts":
        if args.median_summary is None: p.error("write-time-shifts requires --median-summary")
        commands[args.action] = ["write_pair_time_shifts_to_workbook.py", str(args.workbook), str(args.median_summary)] + (["--overwrite"] if args.overwrite else [])
    subprocess.run([sys.executable, *commands[args.action]], cwd=ROOT, check=True)
    return 0

if __name__ == "__main__": raise SystemExit(main())
