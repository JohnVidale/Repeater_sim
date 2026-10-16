#!/usr/bin/env python3
"""Compare P38 pair-stack superpositions for two location hypotheses."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt


def make_figure(same_root: Path, relative_root: Path, mode: str, output: Path) -> None:
    """Place the two event-stack superpositions side by side without resampling."""
    def traces(root: Path, case: str) -> Path:
        matches = sorted((root / "cases" / case / mode / "figures").glob("P38_Array_*_traces.png"))
        if len(matches) != 1:
            raise FileNotFoundError(f"Expected one stack figure for {case}/{mode}, found {matches}")
        return matches[0]
    figures = {"same location": traces(same_root, "without_relative_offset"),
               "relative location": traces(relative_root, "with_relative_offset")}
    fig, axes = plt.subplots(1, 2, figsize=(18, 8), constrained_layout=True)
    for axis, (title, path) in zip(axes, figures.items()):
        if not path.is_file():
            raise FileNotFoundError(path)
        axis.imshow(plt.imread(path))
        axis.set_title(title, fontsize=15)
        axis.axis("off")
    fig.suptitle(
        f"P38 {mode}: event-pair stack superposition\n"
        "green = 2006 event; red = 2015 event; no additional cross-correlation alignment",
        fontsize=16,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("same_location_root", type=Path)
    parser.add_argument("relative_location_root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--modes", nargs="+", default=("yka_40s", "ilar_40s"))
    args = parser.parse_args()
    for mode in args.modes:
        make_figure(args.same_location_root, args.relative_location_root, mode, args.output_dir / f"P38_{mode}_same_vs_relative_stack_superposition.png")


if __name__ == "__main__": main()
