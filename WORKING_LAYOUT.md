# Working layout

For the current scientific state and next steps, read `STATUS.md` first.

The files used to control the active analysis are kept at the repository root:

- `analysis_config.json` is the active run configuration.
- `ICevents_working.xlsx` contains the active event and event-pair parameters.
- `pairs` holds shared EHB latitude, longitude, and depth. `events` holds raw
  event times. `aligned_pairs` holds explicit same-location and
  relative-location analysis references, timing terms, and metre offsets.
- `station_acceptance_working.xlsx` contains the active station/phase acceptance
  states and manual window shifts.
- `latest_run/` is the most recent completed run. It currently contains the
  adopted 0–5 s, recalculated-A/R, CC >= 0.875 results after the configured
  five-station +0.62 s timestamp correction and IU.OTAV/IU.TRQA -0.10 s
  correction over the same 2003-01-01 to 2011-01-01 half-open interval, plus
  the A-only and B-only plot sets and preferred P+PKP/no-PKiKP bootstrap
  uncertainties.

The prior catalog-arrival review is preserved under
`archive/catalog_arrival_review_20260913/`. Dated root-workbook/configuration
backups and superseded workflow outputs are organized under
`archive/noncurrent_versions_20260927/`. The active configuration reads
waveform data from the catalog-review archive but reads both editable
workbooks from the repository root.

New workflow outputs are written beneath `outputs/`. After choosing a new run
as authoritative, move the previous `latest_run/` into `archive/` and move the
new run directory to `latest_run/`. Move superseded, unpromoted output
directories into the dated non-current archive rather than leaving them in
`outputs/`.

Historical analysis programs and fixed inputs are under `legacy/`. The small
root-level `compare_repeater_pwaves.py` compatibility module remains because
the active multiphase code imports shared catalog and waveform helpers from the
legacy P-wave implementation. The retired direct-P common-centroid relocation
and coupled calibration scripts are preserved under
`legacy/centroid_relocation/`; they are not part of the active workflow.

Routine workbook actions use `python maintain_workbook.py` with `format`,
`refresh-references`, `write-offsets --relative-locations FILE`, or
`write-time-shifts --median-summary FILE`. Each action saves a backup first.
