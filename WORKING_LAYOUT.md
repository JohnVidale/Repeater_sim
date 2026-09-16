# Working layout

The files used to control the active analysis are kept at the repository root:

- `analysis_config.json` is the active run configuration.
- `ICevents_working.xlsx` contains the active event and event-pair parameters.
- `station_acceptance_working.xlsx` contains the active station/phase acceptance
  states and manual window shifts.
- `latest_run/` is the most recent completed run. It currently contains the
  adopted 0–5 s, recalculated-A/R, CC >= 0.875 results and the A-only plot sets.

The prior catalog-arrival review, sensitivity runs, earlier workbooks, and old
run directories are preserved under `archive/catalog_arrival_review_20260913/`.
The active configuration reads waveform data from that archive but reads both
editable workbooks from the repository root.

New workflow outputs are written beneath `outputs/`. After choosing a new run
as authoritative, move the previous `latest_run/` into `archive/` and move the
new run directory to `latest_run/`.

Historical analysis programs and fixed inputs are under `legacy/`. The small
root-level `compare_repeater_pwaves.py` compatibility module remains because
the active multiphase code imports shared catalog and waveform helpers from the
legacy P-wave implementation.
