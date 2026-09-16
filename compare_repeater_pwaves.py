#!/usr/bin/env python3
"""Compatibility access to the legacy P-wave analysis and shared utilities.

The implementation remains importable because the active multiphase workflow
uses its catalog, waveform, and signal-processing helpers.
"""

from __future__ import annotations

import sys

from legacy.p_wave_noise import compare_repeater_pwaves as _implementation


if __name__ == "__main__":
    raise SystemExit(_implementation.main())

# Make ``import compare_repeater_pwaves`` return the implementation module so
# existing imports and test-time patching keep their original behavior.
sys.modules[__name__] = _implementation
