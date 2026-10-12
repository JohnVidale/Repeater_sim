# Retired common-centroid relocation

These scripts preserve the former direct-P common-centroid relocation and
coupled pair-calibration workflow for reproducibility. They are not part of
the active repeater workflow.

The active workflow uses the catalog coordinates in `ICevents_working.xlsx`
as the common reference location and estimates only event-2-minus-event-1
relative location and origin-time offsets. Historical commands in these files
may require path or import adjustments when run from this directory.

Retired from the active workflow on 2026-09-27:

- `relocate_pair_fixed_depths.py`
- `write_pair_new_locations_to_workbook.py`
- `calibrate_pair_parameters.py`
- `test_calibrate_pair_parameters.py`
