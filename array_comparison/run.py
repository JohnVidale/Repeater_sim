#!/usr/bin/env python3
"""Run an isolated P38 YKA/ILAR comparison from one readable settings file."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

from legacy_adapter import run_p38_location_test


REPOSITORY = Path(__file__).resolve().parents[1]
ALLOWED_MODES = {"yka_40s", "ilar_40s", "ilar_17s_normalized"}


def load_settings(path: Path) -> dict[str, object]:
    """Load and validate the small public configuration surface."""
    settings = json.loads(path.read_text())
    if settings.get("pair") != "P38":
        raise ValueError("This first streamlined runner supports P38 only")
    if not isinstance(settings.get("include_relative_offset"), bool):
        raise ValueError("include_relative_offset must be true or false")
    modes = settings.get("modes")
    if not isinstance(modes, list) or not modes or not all(isinstance(m, str) for m in modes):
        raise ValueError("modes must be a non-empty list of mode names")
    invalid = set(modes) - ALLOWED_MODES
    if invalid:
        raise ValueError(f"Unsupported modes: {', '.join(sorted(invalid))}")
    if len(set(modes)) != len(modes):
        raise ValueError("modes may not contain duplicates")
    return settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path(__file__).resolve().parent / "settings" / "p38_yka_ilar.json",
        help="JSON file containing the pair, relative-offset switch, and requested modes.",
    )
    parser.add_argument("--output-root", type=Path, help="Optional empty output directory.")
    args = parser.parse_args()
    settings_path = args.settings.resolve()
    settings = load_settings(settings_path)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_root = (
        args.output_root.resolve()
        if args.output_root
        else REPOSITORY / "outputs" / f"array_comparison_{timestamp}"
    )
    if output_root.exists():
        raise FileExistsError(f"Refusing to reuse existing output directory: {output_root}")

    run_p38_location_test(
        REPOSITORY,
        output_root,
        bool(settings["include_relative_offset"]),
        list(settings["modes"]),
    )
    shutil.copy2(settings_path, output_root / "settings_used.json")
    request = {
        "settings_path": str(settings_path),
        "include_relative_offset": settings["include_relative_offset"],
        "pair": settings["pair"],
        "modes": settings["modes"],
    }
    (output_root / "streamlined_run_request.json").write_text(json.dumps(request, indent=2) + "\n")
    print(json.dumps(request, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
