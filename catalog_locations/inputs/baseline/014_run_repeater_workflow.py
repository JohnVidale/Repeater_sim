#!/usr/bin/env python3
"""Run the full repeater-pair processing workflow.

Typical use from VSCode:

    conda run -n vidale_main python run_repeater_workflow.py

The ``do_centroid_relocation`` setting in ``analysis_config.json`` controls
whether the default run first refreshes pair centroids.  The default assumes
the centroids are already current and remakes phase plots, relative offsets,
uncertainties, and workbook offset columns:

    conda run -n vidale_main python run_repeater_workflow.py

To redo the configured direct-P centroid relocation and rewrite its new
coordinates (for ``fixed_depth`` or ``free_hypocenter`` mode):

    conda run -n vidale_main python run_repeater_workflow.py --do-centroid-relocation
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl

try:
    import resource
except ImportError:  # pragma: no cover - Windows fallback
    resource = None


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "analysis_config.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def run_command(command: list[str], dry_run: bool) -> subprocess.CompletedProcess[str]:
    printable = " ".join(str(part) for part in command)
    print()
    print(f"RUN {printable}", flush=True)
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    captured: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        captured.append(line)
        print(line, end="", flush=True)
    returncode = process.wait()
    stdout = "".join(captured)
    if returncode != 0:
        raise SystemExit(f"Command failed with exit code {returncode}: {printable}")
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def child_cpu_seconds() -> float:
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def format_duration(seconds: float) -> str:
    minutes, remainder = divmod(float(seconds), 60.0)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remainder:05.2f}"
    return f"{minutes:d}:{remainder:05.2f}"


def play_completion_sound(sound_file: Path | None, enabled: bool) -> None:
    if not enabled:
        return
    # Always emit a terminal bell first; it works in many terminals and is safe.
    print("\a", end="", flush=True)
    if platform.system() != "Darwin":
        return
    default_sound = Path("/System/Library/Sounds/Glass.aiff")
    sound_path = sound_file or default_sound
    if not sound_path.is_file():
        return
    try:
        subprocess.run(
            ["afplay", str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return


def parse_last_existing_path(output: str) -> Path:
    for line in reversed(output.splitlines()):
        candidate = Path(line.strip())
        if candidate.exists():
            return candidate
    raise RuntimeError("Could not find an output path in command output")


def parse_multiphase_output_path(output: str) -> Path:
    pattern = re.compile(r"^OUTPUT\s+(.+)$")
    for line in output.splitlines():
        match = pattern.match(line.strip())
        if match:
            path = Path(match.group(1))
            if path.exists():
                return path
    return parse_last_existing_path(output)


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def missing_workbook_time_shifts(workbook_path: Path, pair_labels: list[str]) -> list[str]:
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook["pairs"]
        rows = sheet.iter_rows(values_only=True)
        header = {
            str(value).strip().lower(): index
            for index, value in enumerate(next(rows))
            if value is not None and str(value).strip()
        }
        if "label" not in header or "new time shift" not in header:
            return list(pair_labels)
        label_index = header["label"]
        shift_index = header["new time shift"]
        shifts: dict[str, float] = {}
        for row in rows:
            label = row[label_index] if label_index < len(row) else None
            if label is None:
                continue
            shift = row[shift_index] if shift_index < len(row) else None
            parsed = finite_float(shift)
            if parsed is not None:
                shifts[str(label).strip()] = parsed
        return [label for label in pair_labels if label not in shifts]
    finally:
        workbook.close()


def write_missing_pairs_config(
    config: dict[str, Any],
    missing_pair_labels: list[str],
    config_path: Path,
    *,
    dry_run: bool,
) -> Path:
    preflight_dir = ROOT / "outputs" / "workflow_preflight_configs"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    preflight_config_path = (
        preflight_dir
        / f"{config_path.stem}_missing_time_shifts_{timestamp}.json"
    )
    if dry_run:
        return preflight_config_path

    preflight_dir.mkdir(parents=True, exist_ok=True)
    preflight_config = dict(config)
    preflight_config["pairs"] = list(missing_pair_labels)
    preflight_config["preflight_source_config"] = str(config_path)
    preflight_config["preflight_reason"] = (
        "temporary config for computing missing workbook new time shift values only"
    )
    preflight_config_path.write_text(
        json.dumps(preflight_config, indent=2) + "\n",
        encoding="utf-8",
    )
    return preflight_config_path


def write_workflow_summary(
    output: Path,
    *,
    config_path: Path,
    workbook_path: Path,
    relocation_output: Path | None,
    computed_shift_output: Path | None,
    missing_time_shifts_filled: list[str],
    bootstrap_iterations: int,
    elapsed_time_seconds: float,
    cpu_time_seconds: float,
    station_acceptance_matrix: Path | None,
) -> None:
    summary = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "config_path": str(config_path.resolve()),
        "workbook_path": str(workbook_path),
        "relocation_output": str(relocation_output) if relocation_output else "",
        "computed_shift_output": str(computed_shift_output)
        if computed_shift_output
        else "",
        "missing_time_shifts_filled": missing_time_shifts_filled,
        "multiphase_output": str(output.resolve()),
        "preferred_relative_locations": str(
            output / "median_absolute_relative_locations_no_pkikp.csv"
        ),
        "preferred_bootstrap_uncertainties": str(
            output / "median_relative_location_offsets_no_pkikp_with_bootstrap_uncertainty.csv"
        ),
        "bootstrap_iterations": bootstrap_iterations,
        "elapsed_time_seconds": elapsed_time_seconds,
        "cpu_time_seconds": cpu_time_seconds,
        "station_acceptance_matrix": (
            str(station_acceptance_matrix.resolve())
            if station_acceptance_matrix
            else ""
        ),
        "station_acceptance_matrix_snapshot": (
            str((output / "station_acceptance_matrix.xlsx").resolve())
            if station_acceptance_matrix
            else ""
        ),
        "workflow": [
            "optional fixed-depth direct-P centroid relocation",
            "optional write pair new_lat/new_lon to workbook",
            "optional missing-pairs-only computed preflight for blank workbook new time shift values",
            "make pair-oriented phase plots, station-oriented all-pair waveform plots, and measurement tables",
            "fit relative offsets with preferred P+Pdiff+PKP (no_pkikp) and diagnostic p_only phase sets",
            "bootstrap preferred no_pkikp uncertainties",
            "write compact centroid/delta columns to ICevents_full.xlsx",
            "run unit tests",
            "refresh the canonical station acceptance matrix while preserving manual shifts and save a run snapshot",
        ],
    }
    (output / "workflow_run_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--do-centroid-relocation",
        action="store_true",
        help="Override the JSON setting and redo the configured centroid relocation.",
    )
    parser.add_argument(
        "--skip-missing-time-shift-preflight",
        action="store_true",
        help="Do not auto-compute and fill missing workbook 'new time shift' values.",
    )
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=None,
        help="Override bootstrap_iterations in the JSON configuration.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )
    parser.add_argument(
        "--no-sound",
        action="store_true",
        help="Do not play a completion sound.",
    )
    parser.add_argument(
        "--sound-file",
        type=Path,
        default=None,
        help="Optional sound file to play on macOS when the workflow completes.",
    )
    args = parser.parse_args()
    start_wall = time.perf_counter()
    start_cpu = time.process_time() + child_cpu_seconds()

    config_path = args.config.resolve()
    config = load_json(config_path)
    centroid_mode = str(config.get("centroid_location_mode", "fixed_depth")).strip().lower()
    if centroid_mode not in {"free_hypocenter", "fixed_depth", "catalog_fixed"}:
        raise SystemExit(
            "centroid_location_mode must be 'free_hypocenter', 'fixed_depth', "
            "or 'catalog_fixed'"
        )
    bootstrap_iterations = (
        int(args.bootstrap_iterations)
        if args.bootstrap_iterations is not None
        else int(config.get("bootstrap_iterations", 1000))
    )
    if bootstrap_iterations < 1:
        raise SystemExit("bootstrap_iterations must be at least 1")
    workbook_path = Path(config.get("time_shift_workbook") or config["catalog_path"])
    configured_station_acceptance_matrix = config.get(
        "manual_pick_alignment_workbook"
    )
    station_acceptance_matrix = (
        Path(str(configured_station_acceptance_matrix))
        if configured_station_acceptance_matrix
        else None
    )
    pair_labels = [str(label) for label in config["pairs"]]
    print(f"Config: {config_path}")
    print(f"Workbook: {workbook_path}")
    print(f"Pairs ({len(pair_labels)}): {', '.join(pair_labels)}")
    print(f"Centroid location mode: {centroid_mode}")
    do_centroid_relocation = bool(config.get("do_centroid_relocation", False))
    if args.do_centroid_relocation:
        do_centroid_relocation = True
    print(f"Do centroid relocation: {do_centroid_relocation}")
    print(f"Bootstrap iterations: {bootstrap_iterations}")

    python = sys.executable
    relocation_output: Path | None = None
    computed_shift_output: Path | None = None
    missing_shifts: list[str] = []
    if do_centroid_relocation and centroid_mode != "catalog_fixed":
        completed = run_command(
            [
                python,
                "relocate_pair_fixed_depths.py",
                "--config",
                str(config_path),
            ],
            args.dry_run,
        )
        if not args.dry_run:
            relocation_output = parse_last_existing_path(completed.stdout)
            run_command(
                [
                    python,
                    "write_pair_new_locations_to_workbook.py",
                    str(workbook_path),
                    str(relocation_output / "pair_fixed_depth_location_summary.csv"),
                ],
                args.dry_run,
            )
    elif do_centroid_relocation:
        print(
            "Centroid location mode is catalog_fixed: retaining the EHB pair "
            "coordinates; no spatial relocation is run.",
            flush=True,
        )

    if (
        str(config.get("time_shift_source", "computed")) == "workbook"
        and not args.skip_missing_time_shift_preflight
    ):
        missing_shifts = missing_workbook_time_shifts(workbook_path, pair_labels)
        if missing_shifts:
            print()
            print(
                "Missing workbook 'new time shift' for: "
                + ", ".join(missing_shifts),
                flush=True,
            )
            preflight_config_path = write_missing_pairs_config(
                config,
                missing_shifts,
                config_path,
                dry_run=args.dry_run,
            )
            print(
                "Computing missing shifts only, using temporary config: "
                f"{preflight_config_path}",
                flush=True,
            )
            completed = run_command(
                [
                    python,
                    "make_multiphase_median_outputs.py",
                    "--config",
                    str(preflight_config_path),
                    "--time-shift-source",
                    "computed",
                ],
                args.dry_run,
            )
            if not args.dry_run:
                computed_shift_output = parse_multiphase_output_path(completed.stdout)
            else:
                computed_shift_output = ROOT / "outputs" / "DRY_RUN_COMPUTED_SHIFT_OUTPUT"
            run_command(
                [
                    python,
                    "write_pair_time_shifts_to_workbook.py",
                    "--config",
                    str(config_path),
                    str(workbook_path),
                    str(computed_shift_output / "median_summary.csv"),
                ],
                args.dry_run,
            )
        else:
            print()
            print("All requested pairs already have workbook 'new time shift' values.")

    completed = run_command(
        [python, "make_multiphase_median_outputs.py", "--config", str(config_path)],
        args.dry_run,
    )
    output = ROOT / "outputs" / "DRY_RUN_OUTPUT"
    if not args.dry_run:
        output = parse_multiphase_output_path(completed.stdout)

    if (
        str(config.get("time_shift_source", "computed")) == "computed"
        and bool(config.get("update_workbook_time_shifts_from_computed", False))
    ):
        run_command(
            [
                python,
                "write_pair_time_shifts_to_workbook.py",
                "--overwrite",
                "--config",
                str(config_path),
                str(workbook_path),
                str(output / "median_summary.csv"),
            ],
            args.dry_run,
        )

    if str(config.get("time_shift_source", "computed")) == "none":
        print(
            "No-time-shift mode: skipping relative location, bootstrap, and "
            "workbook location updates.",
            flush=True,
        )
    else:
        run_command(
            [python, "fit_relative_offsets.py", str(output), "--config", str(config_path)],
            args.dry_run,
        )
        run_command(
            [
                python,
                "bootstrap_relative_offset_uncertainties.py",
                str(output),
                "--config",
                str(config_path),
                "--phase-set",
                "no_pkikp",
                "--iterations",
                str(bootstrap_iterations),
            ],
            args.dry_run,
        )
        run_command(
            [
                python,
                "write_pair_centroid_offsets_to_workbook.py",
                "--workbook",
                str(workbook_path),
                "--relative-locations",
                str(output / "median_absolute_relative_locations_no_pkikp.csv"),
            ],
            args.dry_run,
        )
    run_command(
        [python, "-m", "unittest", "discover", "-s", "tests"],
        args.dry_run,
    )
    if station_acceptance_matrix is not None:
        run_command(
            [
                python,
                "update_station_acceptance_matrix.py",
                "--matrix",
                str(station_acceptance_matrix),
                "--measurements",
                str(output / "phase_measurements.csv"),
                "--output-copy",
                str(output / "station_acceptance_matrix.xlsx"),
            ],
            args.dry_run,
        )
    if not args.dry_run:
        elapsed_time_seconds = time.perf_counter() - start_wall
        cpu_time_seconds = time.process_time() + child_cpu_seconds() - start_cpu
        write_workflow_summary(
            output,
            config_path=config_path,
            workbook_path=workbook_path,
            relocation_output=relocation_output,
            computed_shift_output=computed_shift_output,
            missing_time_shifts_filled=missing_shifts,
            bootstrap_iterations=bootstrap_iterations,
            elapsed_time_seconds=elapsed_time_seconds,
            cpu_time_seconds=cpu_time_seconds,
            station_acceptance_matrix=station_acceptance_matrix,
        )
        print()
        print(f"Workflow complete: {output}")
        print(
            f"Elapsed clock time: {format_duration(elapsed_time_seconds)} "
            f"({elapsed_time_seconds:.3f} s)"
        )
        print(f"CPU time: {format_duration(cpu_time_seconds)} ({cpu_time_seconds:.3f} s)")
        play_completion_sound(args.sound_file, not args.no_sound)
    else:
        elapsed_time_seconds = time.perf_counter() - start_wall
        cpu_time_seconds = time.process_time() + child_cpu_seconds() - start_cpu
        print()
        print(
            f"Dry run complete. Elapsed clock time: {format_duration(elapsed_time_seconds)} "
            f"({elapsed_time_seconds:.3f} s)"
        )
        print(f"CPU time: {format_duration(cpu_time_seconds)} ({cpu_time_seconds:.3f} s)")


if __name__ == "__main__":
    main()
