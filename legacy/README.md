# Legacy analyses

These files are retained for reproducibility but are not part of the active
multiphase relative-location workflow.

## `p_wave_noise/`

The original P-wave waveform-versus-noise experiment, its external station
selection manifest, implementation plan, and SNR plotting utility live here.
The active workflow still uses several low-level catalog and waveform helpers
from this implementation. The root-level `compare_repeater_pwaves.py` is a
compatibility module that preserves those imports and the historical command.

## `one_off/`

Scripts for isolated investigations, currently the event-726 hypocenter test.
They are preserved as historical methods and are not called by
`run_repeater_workflow.py`.

## `project_history/`

Long-form chat summaries and superseded root documentation live here. They may
contain obsolete paths and configuration values and should not be used to
determine the current setup; use the root `STATUS.md` instead.
