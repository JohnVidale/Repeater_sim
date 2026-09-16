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
- Added differential-location predictions to every phase-shift summary, with
  observed-to-predicted connectors and thinner connectors for X selections.
- Flattened active inputs and the newest run at the repository root; moved old
  runs and superseded analyses into `archive/` and `legacy/`.
- Completed a review-only catalog-location study for 59 connected events. Its
  proposed references have not been written to the active workbook.

## Limits to remember

- Horizontal-offset uncertainty is based on bootstrap component spreads; plot
  circles are approximate radial summaries, not covariance ellipses.
- PKP may be more sensitive to vertical separation and phase interference than
  direct P, so it remains secondary.
- `latest_run/` now contains the newest measurements, location fits, and plots.
  Its bootstrap uncertainty products have not yet been regenerated there; the
  current sensitivity uncertainties remain in the archived 0–5 s runs.
- Catalog cluster references are review proposals, not adopted locations or
  formal location uncertainties.

## Next steps

1. Inspect the currently accepted traces and improve inclusion decisions or
   correlation-window start times where the waveforms justify a change.
2. Split the present exclusion meaning into:
   - `X`: redundant or unpickable data;
   - `B`: a measurable trace whose timing deviates from expectations.
   Define how `B` participates in plots, diagnostics, and location fits before
   changing the workbook or code.
3. Review ScP and PcP waveform quality and timing precision to decide whether
   either phase should be folded into the measurement and location workflow.
4. Test whether PKiKP contains resolvable temporal changes that require more
   than differential inner-core rotation to explain.
5. Examine when timing discrepancies appear across events, stations, networks,
   and phases, looking for explanations other than sensor clock drift.

## Later maintenance

- Run the complete workflow once from the top-level working files so
  `latest_run/` becomes one self-contained authoritative measurement, fit,
  uncertainty, and plot package.
- Decide whether any catalog-derived cluster references should replace active
  absolute locations before modifying the working workbook.
- Keep this file current by editing these short lists rather than appending a
  chronological research diary.
