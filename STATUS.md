# Current project status

Last updated: 2026-09-16  
Repository state when updated: `3ffa347`

This file is intentionally short. Run manifests and archived outputs hold the
detailed provenance.

## Current setup

- Active configuration: `analysis_config.json`
- Event and pair workbook: `ICevents_working.xlsx`
- Station acceptance and manual shifts: `station_acceptance_working.xlsx`
- Newest measurement and plot run: `latest_run/`
- Active pairs: P30, P31, P33, P34, P35, P37, P38, P39, P51, P79,
  P112, P123, P140, P145, P321, and P355

## Adopted analysis choices

- Correlation window: 0–5 s after the accepted AIC arrival pick
- Primary result: P only, CC >= 0.875
- Secondary sensitivity result: P+PKP
- PKiKP: measured and plotted, but excluded from the preferred fit
- Pdiff, PcP, and ScP: excluded
- Relative depth: fixed common depth; report horizontal separation
- Pair and common-origin shifts: read from the working workbook
- Station/phase `X`: measured for QC but excluded from the fit
- A-only versions of pair and station waveform plots are generated

## Completed

- Reassessed event locations and origin-time alignment.
- Built and manually reviewed the station/phase acceptance matrix.
- Removed Pdiff and resolved overlapping PKP/PKiKP choices.
- Compared CC thresholds 0.8 and 0.875 and phase sets P, P+PKP, and
  P+PKP+PKiKP.
- Compared 0–10 s and 0–5 s windows using the 14 pairs solved in every case.
- Selected the 0–5 s, recalculated-A/R, P-only, CC >= 0.875 case as primary.
- Obtained primary P-only solutions for 14 pairs. P140 and P145 require the
  P+PKP, CC >= 0.8 fallback when all 16 pairs are displayed together.
- Generated kilometer-scaled offset figures with uncertainty circles and
  A-only waveform plot sets.
- Flattened active inputs and the newest run at the repository root; moved old
  runs and superseded analyses into `archive/` and `legacy/`.
- Completed a review-only catalog-location study for 59 connected events. Its
  proposed references have not been written to the active workbook.

## Limits to remember

- Horizontal-offset uncertainty is based on bootstrap component spreads; plot
  circles are approximate radial summaries, not covariance ellipses.
- PKP may be more sensitive to vertical separation and phase interference than
  direct P, so it remains secondary.
- `latest_run/` is the newest waveform measurement and A-only plotting run. The
  preferred and sensitivity location-fit tables were produced in the archived
  0–5 s sensitivity runs; no single final rerun yet consolidates every selected
  product into `latest_run/`.
- Catalog cluster references are review proposals, not adopted locations or
  formal location uncertainties.

## Next steps

1. Run the complete workflow once from the new top-level working files so
   `latest_run/` becomes one self-contained authoritative measurement, fit,
   uncertainty, and plot package.
2. Review whether the catalog-derived cluster references should replace any
   active absolute locations. Do not change the working workbook until that
   scientific choice is explicit.
3. After the consolidated run, update only the date, commit, completed bullets,
   and next steps here; archive superseded detail instead of appending history.
