"""Launch the protected legacy stack workflow from readable settings.

The legacy files are copied into each run's ``staged_code`` directory.  This
adapter never edits their shared source files or output folders.
"""

from __future__ import annotations

from pathlib import Path
import subprocess


def run_p38_location_test(
    repository: Path,
    output_root: Path,
    include_relative_offset: bool,
    modes: list[str],
) -> None:
    """Run the isolated P38 workflow and raise if any requested mode fails."""
    driver = repository / "run_array_comparison_location_test.py"
    command = [
        "conda",
        "run",
        "-n",
        "vidale_main",
        "python",
        str(driver),
        "--output-root",
        str(output_root),
        "--modes",
        *modes,
        (
            "--include-relative-offset"
            if include_relative_offset
            else "--no-include-relative-offset"
        ),
    ]
    environment = {**__import__("os").environ, "MPLCONFIGDIR": "/private/tmp/repeater-mpl"}
    subprocess.run(command, cwd=repository, env=environment, check=True)
