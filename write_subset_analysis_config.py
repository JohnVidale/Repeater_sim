#!/usr/bin/env python3
"""Write an isolated analysis configuration for selected event pairs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("pairs", nargs="+")
    parser.add_argument("--time-shift-source", choices=("computed", "workbook", "picked", "none"))
    parser.add_argument("--common-time-shift-source", choices=("high_snr_picks", "workbook", "none"))
    parser.add_argument("--selection-correlation-threshold", type=float)
    args = parser.parse_args()

    config = json.loads(args.source.read_text(encoding="utf-8"))
    requested = [str(pair) for pair in args.pairs]
    available = {str(pair) for pair in config["pairs"]}
    missing = sorted(set(requested) - available)
    if missing:
        raise SystemExit(f"Pairs are not active in the source configuration: {missing}")
    config["pairs"] = requested
    config["pairs_all"] = requested
    config["output_root"] = str(args.output.parent.resolve())
    if args.time_shift_source:
        config["time_shift_source"] = args.time_shift_source
    if args.common_time_shift_source:
        config["common_time_shift_source"] = args.common_time_shift_source
    if args.selection_correlation_threshold is not None:
        config["selection_correlation_threshold"] = args.selection_correlation_threshold
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
