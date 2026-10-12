#!/usr/bin/env python3
"""Run the legacy YKA/ILAR pair comparison in collision-free directories.

The legacy source files are copied into each mode's ``staged_code`` directory
and only absolute input/output roots are rewritten.  The original legacy code,
workbooks, waveforms, and shared output directories are never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime


ARRAY_CODES_ROOT = Path("/Users/jvidale/Documents/GitHub/Array_codes")
RESEARCH_IC_ROOT = Path("/Users/jvidale/Documents/Research/IC")
LEGACY_WORKBOOK = ARRAY_CODES_ROOT / "Files" / "ICevents_full.xlsx"
CURRENT_WORKBOOK = ARRAY_CODES_ROOT / "Repeater_sim" / "ICevents_working.xlsx"
CURRENT_LOCATIONS = (
    ARRAY_CODES_ROOT
    / "Repeater_sim"
    / "latest_run"
    / "median_absolute_relative_locations_no_pkikp.csv"
)
CURRENT_UNCERTAINTIES = (
    ARRAY_CODES_ROOT
    / "Repeater_sim"
    / "latest_run"
    / "median_relative_location_offsets_no_pkikp_with_bootstrap_uncertainty.csv"
)

SOURCE_FILES = {
    "run_compare_pair.py": ARRAY_CODES_ROOT / "Run_YKA_WRA" / "run_compare_pair.py",
    "pro3_sort_plot_pair.py": ARRAY_CODES_ROOT / "Process" / "pro3_sort_plot_pair.py",
    "pro5_stack2d.py": ARRAY_CODES_ROOT / "Process" / "pro5_stack2d.py",
    "pro6_pair_cc.py": ARRAY_CODES_ROOT / "Process" / "pro6_pair_cc.py",
    "pro7_pair_scan.py": ARRAY_CODES_ROOT / "Process" / "pro7_pair_scan.py",
    "pro_proceed_john.py": ARRAY_CODES_ROOT / "Process" / "pro_proceed_john.py",
}

P38_DATA_INPUTS = [
    ARRAY_CODES_ROOT / "Files" / "Stations" / "sta_CN_YK.txt",
    ARRAY_CODES_ROOT / "Files" / "Stations" / "sta_ILAR.txt",
    RESEARCH_IC_ROOT / "Mseed" / "YKA" / "20060529_0520.mseed",
    RESEARCH_IC_ROOT / "Mseed" / "YKA" / "20150524_2106.mseed",
    RESEARCH_IC_ROOT / "Mseed" / "ILAR" / "20060529_0520.mseed",
    RESEARCH_IC_ROOT / "Mseed" / "ILAR" / "20150524_2106.mseed",
]

MODES = {
    "yka_40s": {
        "array": 5,
        "array_name": "YKA",
        "zstart": -20,
        "window_length": 40,
        "figure_index": 200,
        "window_normalize": False,
        "trace_normalize": True,
        "trace_amplitude": 1.0,
        "plot_peak": 1.0,
    },
    "ilar_40s": {
        "array": 6,
        "array_name": "ILAR",
        "zstart": -20,
        "window_length": 40,
        "figure_index": 300,
        "window_normalize": False,
        "trace_normalize": True,
        "trace_amplitude": 1.0,
        "plot_peak": 1.0,
    },
    "ilar_17s_normalized": {
        "array": 6,
        "array_name": "ILAR",
        "zstart": -15,
        "window_length": 17,
        "figure_index": 400,
        "window_normalize": True,
        "trace_normalize": False,
        "trace_amplitude": 0.5,
        "plot_peak": 0.05,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_snapshot(repo: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.rstrip()

    return {"head": run("rev-parse", "HEAD"), "status": run("status", "--short", "--branch")}


def require_inputs(require_relative_location_products: bool = True) -> None:
    """Check the inputs needed for an isolated legacy-array run.

    The baseline workflow retains the historical CSV requirement for provenance.
    The streamlined array workflow instead reads its relative offset directly
    from ``ICevents_working.xlsx`` and may disable that requirement.
    """
    required = [LEGACY_WORKBOOK, CURRENT_WORKBOOK]
    if require_relative_location_products:
        required.extend([CURRENT_LOCATIONS, CURRENT_UNCERTAINTIES])
    required.extend(SOURCE_FILES.values())
    required.extend(P38_DATA_INPUTS)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))


def stage_code(stage_dir: Path, intermediate: Path, figures: Path) -> dict[str, dict[str, str]]:
    stage_dir.mkdir(parents=True)
    replacements = [
        ("/Users/vidale/Documents/Research/IC/Pro_Files", str(intermediate)),
        ("/Users/vidale/Documents/Research/IC/Pro_files", str(intermediate)),
        ("/Users/vidale/Documents/Research/IC/Plots_hold", str(figures)),
        ("/Users/vidale/Documents/GitHub/Array_codes/Process", str(stage_dir)),
        ("/Users/vidale/Documents/GitHub/Array_codes", str(ARRAY_CODES_ROOT)),
        ("/Users/vidale/Documents/Research/IC", str(RESEARCH_IC_ROOT)),
    ]
    records: dict[str, dict[str, str]] = {}
    for name, source in SOURCE_FILES.items():
        original = source.read_text()
        staged = original
        for old, new in replacements:
            staged = staged.replace(old, new)
        # pandas 3 no longer permits float(single_element_series).  Each
        # legacy lookup is intended to use the first matched event row.
        staged = re.sub(
            r"float\((lines\d*\.[A-Za-z_][A-Za-z0-9_]*)\)",
            r"float(\1.iloc[0])",
            staged,
        )
        staged = re.sub(
            r"int\(max_xy\[([01])\]\)",
            r"int(np.asarray(max_xy[\1]).flat[0])",
            staged,
        )
        destination = stage_dir / name
        destination.write_text(staged)
        records[name] = {
            "source": str(source),
            "source_sha256": sha256(source),
            "staged_sha256": sha256(destination),
        }

    # The missing dependency only colors terminal text; this no-op shim leaves
    # all numerical and plotting operations unchanged.
    (stage_dir / "termcolor.py").write_text(
        "def colored(text, color=None, on_color=None, attrs=None):\n    return str(text)\n"
    )
    return records


def driver_text(pair: str, mode: dict[str, object]) -> str:
    return f'''from run_compare_pair import run_compare_pair

run_compare_pair(
    repeater={pair!r},
    dphase="PKIKP",
    beam_width=0.010,
    slow_delta=0.002,
    beam_offset=0.02,
    freq_min=1,
    freq_max=2,
    stat_corr=0,
    ARRAY={mode["array"]},
    Zstart_buff={mode["zstart"]},
    wind_len={mode["window_length"]},
    wind_buff=30,
    fig_index={mode["figure_index"]},
    do_interpolate=True,
    pair_name={pair!r},
    plot_peak={mode["plot_peak"]},
    win_norm={mode["window_normalize"]},
    trace_norm={mode["trace_normalize"]},
    trace_amp={mode["trace_amplitude"]},
)
'''


def selected_station_codes(intermediate: Path) -> dict[str, object]:
    script = (
        "import json,sys; from obspy import read; "
        "print(json.dumps({p: sorted({tr.stats.station for tr in read(p)}) for p in sys.argv[1:]}))"
    )
    files = sorted(intermediate.glob("*sel.mseed"))
    if not files:
        return {"by_file": {}, "intersection": []}
    result = subprocess.run(
        ["conda", "run", "-n", "vidale_main", "python", "-c", script, *map(str, files)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    raw = json.loads(result.stdout)
    by_file = {Path(path).name: stations for path, stations in raw.items()}
    station_sets = [set(stations) for stations in by_file.values()]
    intersection = sorted(set.intersection(*station_sets)) if station_sets else []
    return {"by_file": by_file, "intersection": intersection}


def write_location_snapshot(pair: str, destination: Path) -> None:
    with CURRENT_LOCATIONS.open(newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("pair") == pair]
    destination.write_text(json.dumps(rows, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="P38")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--modes", nargs="+", choices=sorted(MODES), default=list(MODES))
    args = parser.parse_args()

    if args.pair != "P38":
        parser.error("This audited pilot runner currently supports only P38")
    require_inputs()
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_root = args.output_root or Path(__file__).resolve().parent / "outputs" / f"array_comparison_{timestamp}"
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    repo = ARRAY_CODES_ROOT / "Repeater_sim"
    provenance = {
        "created": datetime.now().astimezone().isoformat(),
        "pair": args.pair,
        "correction_mode": "none_baseline",
        "git": git_snapshot(repo),
        "inputs": {
            str(path): {"sha256": sha256(path), "size": path.stat().st_size}
            for path in (
                LEGACY_WORKBOOK,
                CURRENT_WORKBOOK,
                CURRENT_LOCATIONS,
                CURRENT_UNCERTAINTIES,
                *P38_DATA_INPUTS,
            )
        },
        "note": (
            "Legacy ICevents_full.xlsx supplies event metadata and legacy timing shifts. "
            "The current ICevents_working.xlsx-derived location products are recorded but not applied."
        ),
        "modes": args.modes,
    }
    (output_root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    write_location_snapshot(args.pair, output_root / "differential_location_not_applied.json")

    failures = []
    for mode_name in args.modes:
        mode = MODES[mode_name]
        mode_root = output_root / "baseline" / mode_name
        intermediate = mode_root / "intermediate"
        figures = mode_root / "figures"
        logs = mode_root / "logs"
        stage_dir = mode_root / "staged_code"
        for directory in (intermediate, figures, logs):
            directory.mkdir(parents=True)
        sources = stage_code(stage_dir, intermediate, figures)
        driver = stage_dir / "run_mode.py"
        driver.write_text(driver_text(args.pair, mode))
        settings = {
            **mode,
            "pair": args.pair,
            "correction_mode": "none_baseline",
            "sources": sources,
            "compatibility_rewrites": [
                "absolute input/output roots",
                "float(single-row pandas Series) to float(Series.iloc[0])",
                "int(single-element NumPy index array) to int(array.flat[0])",
                "termcolor no-op terminal-color shim",
            ],
        }
        (mode_root / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

        command = ["conda", "run", "-n", "vidale_main", "python", str(driver)]
        environment = os.environ.copy()
        environment["MPLBACKEND"] = "Agg"
        environment["MPLCONFIGDIR"] = str(mode_root / "matplotlib_config")
        completed = subprocess.run(
            command,
            cwd=stage_dir,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (logs / "run.log").write_text(completed.stdout)
        (logs / "command.json").write_text(json.dumps(command, indent=2) + "\n")
        (logs / "exit_code.txt").write_text(f"{completed.returncode}\n")
        if completed.returncode:
            failures.append(mode_name)
            continue
        stations = selected_station_codes(intermediate)
        (mode_root / "common_elements.json").write_text(json.dumps(stations, indent=2) + "\n")

    summary = {
        "output_root": str(output_root),
        "successful_modes": [name for name in args.modes if name not in failures],
        "failed_modes": failures,
    }
    (output_root / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
