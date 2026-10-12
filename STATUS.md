# Current project status

Last updated: 2026-10-12
Repository HEAD when updated: `5a2875e` (authoritative analysis changes remain uncommitted)

This file is intentionally short. Run manifests and archived outputs hold the
detailed provenance.

## Current setup

- Active configuration: `analysis_config.json`
- Event and pair workbook: `ICevents_working.xlsx`
- Station acceptance and manual shifts: `station_acceptance_working.xlsx`
- Authoritative measurement, relative-location, uncertainty, and plot run:
  `latest_run/` (generated 2026-09-24 from the root working files)
- Active pairs: P30, P31, P33, P34, P35, P37, P38, P39, P51, P79,
  P112, P123, P140, P145, P321, and P355

## Adopted analysis choices

- Correlation window: 0–5 s after the accepted AIC arrival pick
- Preferred relative-location result: P+PKP, excluding PKiKP, CC >= 0.875
- P-only result: retained as a diagnostic sensitivity
- PKiKP: measured and plotted, but excluded from the preferred fit
- PcP through 65° and ScP: measured and plotted for diagnostic review, but excluded from
  the location fits
- Pdiff: excluded
- Relative depth: fixed common depth; report horizontal separation
- Common reference location: catalog `lat`/`lon`/`depth`; the former optional
  direct-P common-centroid relocation is retired from the active workflow
- Pair and common-origin shifts: read from the working workbook
- Station/phase `X`: persistent manual flag for redundant or unpickable data;
  measured for QC but excluded from the fit
- Station/phase `B`: persistent manual flag for a well-defined shift judged
  unlikely to result from differential location; measured and plotted but
  excluded from the fit
- Waveform timestamp correction: add 0.62 s to GT.BOSA, GT.DBIC, GT.LBTB,
  GT.LPAZ, and GT.VNDA for event origins from 2003-01-01 through 2010-12-31;
  the interval is half-open and ends at 2011-01-01
- Waveform timestamp correction: subtract 0.10 s from IU.OTAV and IU.TRQA
  over the same half-open 2003-01-01 to 2011-01-01 interval
- B-status residual searches use a +/-2 s lag window; other statuses use the
  standard +/-0.5 s residual lag window
- A-only versions of pair and station waveform plots are generated
- B-only versions of pair and station waveform plots are generated

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
- Completed the top-level workflow rerun on 2026-09-17 and promoted its
  measurements, fits, 200-iteration P+PKP bootstrap uncertainties, tests, and
  plots to `latest_run/`.
- Applied and validated the five-station +0.62 s timestamp correction, revised
  the affected B classifications, reran the full workflow on 2026-09-24, and
  promoted its measurements, preferred P+PKP fits, 200-iteration bootstrap
  uncertainties, acceptance-matrix snapshot, and plots to `latest_run/`.
- Applied and validated the IU.OTAV/IU.TRQA -0.10 s timestamp correction on top
  of the five-station +0.62 s correction, revised 18 affected B classifications
  (15 to A and 3 to R), reran the full workflow on 2026-09-24, and promoted its
  2,378 measurements, 16 preferred-location rows, 200-iteration bootstrap
  uncertainties, acceptance-matrix snapshot, and plots to `latest_run/`.
- Adopted the subsequent manual acceptance-matrix review (7 status changes and
  26 manual alignment-shift changes), reran the full workflow on 2026-09-24,
  and promoted the refreshed measurements, locations, uncertainties, workbook
  snapshot, and plots to `latest_run/`.
- Archived the immediately preceding authoritative package as
  `archive/latest_run_20260924_142308/`.
- Added differential-location predictions to every phase-shift summary, with
  observed-to-predicted connectors and thinner connectors for X selections.
- Flattened active inputs and the newest run at the repository root; moved old
  runs and superseded analyses into `archive/` and `legacy/`.
- Organized dated root backups and superseded workflow outputs under
  `archive/noncurrent_versions_20260927/`; no files were deleted.
- Completed a review-only catalog-location study for 59 connected events. Its
  proposed references have not been written to the active workbook.
- Retired the optional common-centroid relocation path on 2026-09-27 while
  retaining event-2-minus-event-1 differential-location fitting and bootstrap
  uncertainties; historical relocation scripts remain under
  `legacy/centroid_relocation/`.

- Added the `aligned_pairs` workbook contract: raw catalog values remain in
  `events` and `pairs`, while both analysis-reference hypotheses and
  metre-scale relative offsets are explicit together.
- Validated the P38 YKA relative-location array run from those references;
  predicted differential-location travel-time effects are about 2--3 ms.

## Limits to remember

- Horizontal-offset uncertainty is based on bootstrap component spreads; plot
  circles are approximate radial summaries, not covariance ellipses.
- PKP may be more sensitive to vertical separation and phase interference than
  direct P, so it remains secondary.
- `latest_run/` contains the corrected measurements, location fits, plots,
  canonical acceptance-matrix snapshot, and 200-iteration P+PKP (excluding
  PKiKP) bootstrap uncertainties. P-only sensitivity uncertainties remain in
  the archived 0–5 s comparison runs.
- Catalog cluster references are review proposals, not adopted locations or
  formal location uncertainties.

## Next steps

1. Inspect the currently accepted traces and improve inclusion decisions or
   correlation-window start times where the waveforms justify a change.
2. Review the newly measured ScP and PcP waveform quality and timing precision
   before considering either phase for the location fits.
3. Test whether PKiKP contains resolvable temporal changes that require more
   than differential inner-core rotation to explain.
4. Examine when timing discrepancies appear across events, stations, networks,
   and phases, looking for explanations other than sensor clock drift.

## Later maintenance

- Decide whether any catalog-derived cluster references should replace active
  absolute locations before modifying the working workbook.
- Keep this file current by editing these short lists rather than appending a
  chronological research diary.
