#!/usr/bin/env python3
"""Rebuild the SAC coordinate-normalized tree from a preserved original tree.

The two supplied CSV audits record the 98 consistency replacements and 29
published GE-coordinate fills made on 2026-09-10.  This script copies an
unchanged original tree, applies those recorded header values, and verifies
both waveform samples and the recorded before/after SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
from obspy.io.sac import SACTrace


REPO = Path(__file__).resolve().parent
AUDIT_FILES = (
    REPO
    / "archive/noncurrent_versions_20260927/workflow_outputs/Old/"
    "sac_coordinate_normalization_20260910_134612/coordinate_changes.csv",
    REPO
    / "archive/noncurrent_versions_20260927/workflow_outputs/Old/"
    "sac_coordinate_normalization_20260910_134944/coordinate_changes.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recorded_changes() -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for audit in AUDIT_FILES:
        with audit.open(newline="", encoding="utf-8") as handle:
            changes.extend(csv.DictReader(handle))
    relative_paths = [row["relative_path"] for row in changes]
    if len(relative_paths) != len(set(relative_paths)):
        raise RuntimeError("Coordinate audits contain duplicate relative paths")
    return changes


def update_header(path: Path, change: dict[str, str]) -> None:
    if sha256(path) != change["sha256_before"]:
        raise RuntimeError(f"Original checksum does not match audit: {path}")
    trace = SACTrace.read(str(path))
    samples = np.asarray(trace.data).copy()
    trace.stla = float(change["reference_latitude"])
    trace.stlo = float(change["reference_longitude"])
    temporary = path.with_name(path.name + ".coordinate-rebuild.tmp")
    try:
        trace.write(str(temporary), byteorder=trace.byteorder, flush_headers=False)
        rebuilt = SACTrace.read(str(temporary))
        if not np.array_equal(samples, np.asarray(rebuilt.data)):
            raise RuntimeError(f"Waveform samples changed: {path}")
        if rebuilt.stla != trace.stla or rebuilt.stlo != trace.stlo:
            raise RuntimeError(f"Coordinate write failed: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if sha256(path) != change["sha256_after"]:
        raise RuntimeError(f"Rebuilt checksum differs from recorded result: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    audit = args.audit.resolve()
    if not source.is_dir():
        raise RuntimeError(f"Source directory does not exist: {source}")
    if destination.exists():
        raise RuntimeError(f"Destination already exists: {destination}")
    changes = recorded_changes()
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    try:
        for change in changes:
            update_header(destination / change["relative_path"], change)
    except Exception:
        shutil.rmtree(destination)
        raise
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(
        json.dumps(
            {
                "source": str(source),
                "destination": str(destination),
                "files_copied": sum(1 for path in destination.rglob("*") if path.is_file()),
                "coordinates_rebuilt": len(changes),
                "audit_files": [str(path) for path in AUDIT_FILES],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(destination)
    print(audit)


if __name__ == "__main__":
    main()
