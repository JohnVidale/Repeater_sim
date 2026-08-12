# IC rotation / Repeater_sim project chat summary

## 2026-08-12 — Consolidated review of IC rotation project chats

Reviewed the project-relevant Codex chats visible in the app:

- Current Repeater_sim chat in `/Users/jvidale/Documents/GitHub/Array_codes/Repeater_sim`.
- Older IC rotation setup/design chats whose recorded cwd was `/Users/jvidale/Documents/ChatGPT/IC rotation`.
- Excluded unrelated general ChatGPT chats that were not tied to this repository or IC rotation analysis.

The target summary file did not already exist in this repository, so this is the first recorded project-chat entry.

### Workspace, project, and Git decisions

- The working code project is `/Users/jvidale/Documents/GitHub/Array_codes/Repeater_sim`; the older `/Users/jvidale/Documents/ChatGPT/IC rotation` folder was a project-folder mismatch and should be treated as historical chat context rather than the analysis repository.
- `AGENTS.md` in the repository defines the project root and scopes project-specific changes to Repeater_sim.
- Older IC rotation chats contain important decisions and should be retained as reference, but new code work should occur in the Repeater_sim project/root.
- The duplicate/new Repeater_sim project entry was discussed as removable if it contains no needed chats; the safer arrangement is to keep the IC rotation project pointed at the Repeater_sim folder if preserving older chats matters.
- A GitHub repository named `Repeater_sim` under `jvidale` was created by the user, but the chat record did not include a completed GitHub connector sync/initial commit in this project summary pass.

### Initial P-wave noise-comparison design and implementation

- The initial design goal was to test whether differences between near-repeater teleseismic P waves exceed the measured pre-P noise, not to prove a specific source-radiation cause.
- Core decisions captured in `PLAN.md` and implemented in `compare_repeater_pwaves.py`:
  - Use vertical `BHZ` components.
  - Use TauP `ak135` predicted direct `P` arrivals for alignment.
  - Treat SAC `t0` as QC-only header P travel time from catalog origin, not as the alignment reference.
  - Use causal bandpass filtering, detrending, tapering, common resampling, signed correlation, positive/no-polarity-flip alignment, symmetric normalization, pre-P noise chunks, empirical nulls, and non-overwriting run manifests.
  - Preserve source SAC files and Excel workbooks as read-only inputs.
- Created/maintained project files:
  - `compare_repeater_pwaves.py`
  - `analysis_config.json`
  - `station_selection.csv`
  - `README.md`
  - `tests/test_compare_repeater_pwaves.py`
  - `.gitignore`
  - `PLAN.md`
- The earliest full selected-station scientific run `20260807_182708` was superseded by `20260807_182908` after correcting the interpretation of SAC `t0`.
  - Substantive waveform results were unchanged.
  - QC header-P discrepancy flags changed substantially.
  - Use `/Users/jvidale/Documents/Research/IC/YKA-ILAR_Rotation/Output/20260807_182908` for that historical P-wave run.
- Historical selected-station result from the corrected run:
  - P34 classified `same_within_noise`.
  - P31, P33, P355, P37, P38, and P39 classified `different_beyond_noise`.
  - This was explicitly treated as a noise-compatibility result, not source attribution.

### Station-selection and pair-scope decisions

- `station_selection.csv` was not a direct export of `ICevents_full.xlsx`; it combined pair/event IDs from the workbook with station/correlation selections transcribed from waveform figures.
- P34 crowded labels were resolved as:
  - `GT.VNDA` = 0.98
  - `IU.SBA` = 0.96
  - `IU.LVC` = 0.98
- P38 retained one unresolved crowded-label/review item in the early selected-station manifest.
- P35 was later included in active calculations despite lacking a plotted selection panel:
  - Events 727 and 752.
  - 123 exact common BHZ station pairs, 122 coordinate-consistent.
  - `II.PFO` is the coordinate mismatch.
  - YKA/ILAR limitations were documented.
- P43 is intentionally ignored for this seismogram set because event 757 lacks required data there and P43 is outside the primary time window of interest.
- P30’s plotted combination was ignored because the latter event belongs to X15 in the master list and is not the catalog P30 matching pair.
- P63’s figure duplication/mismatch remained a figure-provenance issue rather than an active processing target.

### Configuration changes now reflected in `analysis_config.json`

Current inspected configuration includes:

- `pairs`: `P31`, `P33`, `P34`, `P35`, `P355`, `P37`, `P38`, `P39`
- `station_evaluation_mode`: `all`
- `selection_correlation_threshold`: `0.5`
- `time_shift_source`: `workbook`
- `time_shift_workbook`: `/Users/jvidale/Documents/GitHub/Array_codes/Files/ICevents_full.xlsx`
- `lag_search_seconds`: `4.0`
- `residual_lag_search_seconds`: `0.2`
- `plot_window_seconds`: `[-10.0, 80.0]`
- `correlation_window_seconds`: `[-10.0, 20.0]`
- `noise_pre_p_guard_seconds`: `10.0`, meaning the final noise window ends at least 10 s before estimated P.
- `clipping_repeat_count`: `10`, used as a waveform QC flag for repeated identical max/min samples.

Threshold, residual lag search, and workbook-shift source were moved into JSON as the single source of truth for `make_multiphase_median_outputs.py`; earlier CLI overrides were removed.

### `compare_repeater_pwaves.py` changes beyond the initial implementation

- Added all-station mode and `stations_meeting_correlation_threshold.csv`.
- Added terminal progress reporting and throttled it to every 20 completions plus final completion.
- Added elapsed wall time and CPU time reporting at program end.
- Prevented JSON output failure from `NaN` values by ensuring nonfinite values are handled before strict JSON writing.
- Added/updated plotting annotations:
  - Station name, distance, azimuth, CC, and shift in compact two-line labels.
  - Arrival markers for `P`, `pP`, `sP`, `PP`, `PcP`, and related phases where requested.
  - Later requested not to print noise levels or whether noise explains mismatch on trace plots.
- Restricted plotted correlations to those above threshold where requested.
- Added distance in degrees to the exceptions Excel output.
- Clarified that the VS Code run triangle works if the selected interpreter is `/opt/anaconda3/envs/vidale_main/bin/python`.

### Catalog locations, preferred locations, and ICevents workbook decisions

- The project investigated South Sandwich event locations and concluded that absolute locations accurate to roughly 10–20 km may matter for interpreting precise differential times, especially because depth differences can strongly affect depth phases.
- ISC-EHB was treated as the best catalog source when available, but depth constraints remain weak from travel times alone.
- The adopted strategy was to constrain repeater-pair depths to be common rather than rely on weak independent depth estimates.
- Generated location-comparison and preferred-location workbooks under:
  - `outputs/019fe3df-32a0-70c0-a5c4-a6cbf8a5b62f/`
- Important products in that folder include:
  - `south_sandwich_repeater_locations_common_depth.xlsx`
  - `south_sandwich_repeater_location_comparison.xlsx`
  - `all_icevents_preferred_locations_common_depth.xlsx`
  - `ICevents_full_best_locations.xlsx`
  - `ICevents_full_common_locations.xlsx`
  - `all_preferred_locations.json`
  - catalog-match CSVs and diagnostic PNG previews.
- The user requested a new version of `ICevents_full.xlsx` with best locations inserted:
  - Replace `lat/lon/depth` values in the `pairs` sheet.
  - Add `lat_best`, `lon_best`, and `depth_best` to the `events` sheet.
  - Ensure corresponding pair and event values agree for all pair members.
  - Move `lat_best/lon_best/depth_best` immediately right of the time column and move older lat/lon/depth provenance columns to the far right.
- `compare_repeater_pwaves.py` was changed to use `lat_best`, `lon_best`, and `depth_best` rather than `LAT`, `LON`, and `DEP`.

### Multi-phase repeater relative-location workflow

- A separate script, `make_multiphase_median_outputs.py`, was created for multi-phase analysis so the original P-only production script was not disturbed.
- Phases measured/used in current workflow:
  - `P`
  - `PcP`
  - `ScP`
  - `PKiKP`
  - `PKP`
- Arrival markers on phase plots include:
  - `P`, `pP`, `sP`, `PP`, `PcP`, `ScP`, `PKP`, `PKiKP`, `PKIKP`
- Current phase-use gates:
  - Use `PcP` and `ScP` only for distances `< 40°`.
  - Use `PKiKP` only for distances `> 100°`.
  - Label `PKIKP` when present but do not use it in the fit.
- Current timing model:
  - With `time_shift_source = "workbook"`, read the `new time shift` value from `ICevents_full.xlsx`, pre-apply it to event 2, and then search only the residual lag.
  - With `time_shift_source = "computed"`, compute the common shift from current phase measurements and search the full `±lag_search_seconds`.
  - Workbook-preapplied phase shift summary plots should show residual lag about zero, dashed reference at zero, and y-limits set by `±residual_lag_search_seconds`.
  - Computed-mode summary plots should show full shifts, dashed reference at the computed median, and y-limits set by `±lag_search_seconds`.
- Plotting decisions:
  - Only polar azimuth/takeoff-angle residual plots are made in the latest workflow.
  - Azimuth is the angle; TauP takeoff angle is the radius.
  - Point color shows residual shift; label color encodes correlation.
  - The title clutter was removed.

### Multi-phase time shifts written to `ICevents_full.xlsx`

The `pairs` sheet column `new time shift` was updated for the eight active pairs, with backup:

- Workbook updated: `/Users/jvidale/Documents/GitHub/Array_codes/Files/ICevents_full.xlsx`
- Backup: `/Users/jvidale/Documents/GitHub/Array_codes/Files/ICevents_full.before_median_shift_update.xlsx`

Recorded median shifts:

| Pair | new time shift |
|---|---:|
| P31 | +1.79 s |
| P33 | +0.62 s |
| P34 | +0.75 s |
| P35 | +3.01 s |
| P355 | -1.30 s |
| P37 | -1.41 s |
| P38 | +0.62 s |
| P39 | -2.13 s |

### Latest corrected multi-phase output

Latest corrected run:

`outputs/multiphase_median_cc0.5_workbook_20260811_182018/`

Key files:

- `manifest.json`
- `phase_measurements.csv`
- `phase_summary.csv`
- `median_summary.csv`
- `median_residual_geometry.csv`
- `median_absolute_relative_locations.csv`
- `best_relative_locations.csv`
- `relative_location_fits_from_median_residuals.csv`
- `relative_location_fit_predictions.csv`
- `exceptions.csv`
- `multiphase_relative_location_report.html`
- `phase_plots/`
- `median_residual_geometry_plots/`

Verified properties of this run:

- `time_shift_source = workbook`
- workbook time shifts pre-applied before phase correlation
- residual lag search `±0.2 s`
- correlation threshold `0.5`
- phase shift summary plots centered on zero residual with y-axis `±0.2 s`
- 46 phase waveform plots and 9 polar residual plots in the latest verified folder inventory.

Preferred median-absolute relative-location results from `median_absolute_relative_locations.csv`:

| Pair | N | East km | North km | Depth km | 3-D sep km | median abs residual s | residual RMS s |
|---|---:|---:|---:|---:|---:|---:|---:|
| P31 | 37 | -0.10 | +0.06 | -0.03 | 0.12 | 0.007 | 0.057 |
| P33 | 38 | -0.30 | +0.32 | -0.11 | 0.45 | 0.012 | 0.068 |
| P34 | 49 | +0.11 | -0.04 | +0.02 | 0.12 | 0.005 | 0.057 |
| P35 | 29 | -0.15 | -0.04 | -0.04 | 0.16 | 0.006 | 0.060 |
| P355 | 29 | +0.12 | +0.11 | -0.04 | 0.17 | 0.009 | 0.049 |
| P37 | 57 | +0.35 | -0.46 | +0.05 | 0.58 | 0.012 | 0.038 |
| P38 | 76 | -0.04 | -0.26 | +0.08 | 0.28 | 0.009 | 0.042 |
| P39 | 51 | -0.02 | -0.87 | +0.03 | 0.87 | 0.008 | 0.048 |

The older L1 fit to median-centered residuals remains useful as a sensitivity test, but the chat explicitly shifted the preferred interpretation toward median/median-absolute behavior because the residuals are often tightly clustered with a few rough outliers.

### Scientific interpretation from the chats

- A nearly azimuth-independent shift after same-phase correlation is strong evidence for a common event-to-event time shift and effective co-location, not for a large hypocentral separation.
- The preferred current interpretation is:
  - Use median common time shift as the robust event-to-event timing correction.
  - Use residual patterns after subtracting/pre-applying that shift as the relative-location diagnostic.
  - Treat small fitted spatial offsets as diagnostic/upper-bound style quantities unless residuals show coherent azimuth/takeoff-angle structure.
- Multi-phase observations generally showed that PcP, PKP, and P shifts agree closely; ScP is sparse/noisier.
- For P38, same-phase PcP/ScP/PKiKP shifts mostly reinforced the P result rather than requiring a different hypocenter.
- Seismograms in the configured SAC directory are generally about 1400 s long, not 1800 s or 3600 s; normal records span roughly 23.3 minutes.
- TauP/ak135 estimates from the current station set:
  - `ScP` often arrives about 716–903 s after origin where present.
  - `PKiKP` often arrives about 990–1090 s after origin.
- The Song/Wen-style interpretation was discussed cautiously:
  - Current robust estimates suggest repeaters are unlikely to be separated by 10–20 km.
  - Several pairs look sub-km, with P39 near 0.9 km in the preferred latest median-absolute table.
  - Catalog mislocation alone is unlikely to explain the precise differential timing, but sub-km to ~1 km offsets may still matter for waveform details.

### Unresolved items and cautions

- The latest multi-phase outputs are scientific analysis products, but the current Git worktree still has uncommitted code/config changes:
  - modified `analysis_config.json`
  - untracked `make_multiphase_median_outputs.py`
  - this new `Notes/ICrot_project_chat_summary.md`
- Generated outputs under `outputs/` are numerous and should not be blindly staged; many are derived scientific products.
- The GitHub sync/commit state for Repeater_sim still needs an explicit, careful pass before publication.
- The current project summary is based on visible Codex chat summaries plus inspected repository files; if older chats are hidden outside the current app list, they were not available to this review.
- Scientific caution remains that waveform decorrelation can arise from focal mechanism, source-time function/directivity, medium changes anywhere along the path, source-side or receiver-side scattering, and path-dependent station noise, not just hypocentral separation.
- The multi-phase workflow should remain reproducibility-audited: future summary claims should cite the exact output folder, config, threshold, and whether shifts were `computed` or `workbook` pre-applied.
