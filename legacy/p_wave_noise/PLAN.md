# Repeating-earthquake P-wave noise comparison plan

## Objective

Quantify, seismogram by seismogram, whether differences between aligned vertical teleseismic P-wave signals can be explained by the pre-P noise observed on the two traces. Summarize the station results for each earthquake pair and assign explicit `same_within_noise`, `different_beyond_noise`, or `indeterminate` assessments.

This first analysis tests waveform similarity relative to noise. It does not by itself attribute any detected difference to source radiation; propagation, timing, location, and instrumentation remain possible contributors.

## Read-only inputs

- Event and pair catalog: `/Users/jvidale/Documents/GitHub/Array_codes/Files/ICevents_full.xlsx`
- SAC waveforms: `/Users/jvidale/Documents/Research/IC/Mseed/IC non-IC SAC files/`
- Station-selection figures: `/Users/jvidale/Documents/Research/IC/YKA-ILAR_Rotation figs/rotation non-IC figures/`
- Supplementary pair deck: `/Users/jvidale/Documents/Research/IC/YKA-ILAR_Rotation figs/all_pair_waveforms.pptx`

Never rewrite the workbook, SAC files, figures, or presentation. The surrounding `Array_codes` repository already has unrelated worktree changes; preserve them and do not stage or modify them.

## Code and output locations

Create the implementation under:

`/Users/jvidale/Documents/GitHub/Array_codes/Repeater_sim/`

Planned files:

- `compare_repeater_pwaves.py`: main analysis entry point
- `analysis_config.json`: explicit paths and agreed processing parameters
- `station_selection.csv`: auditable transcription of the externally selected stations and posted correlations
- `README.md`: commands, formulas, assumptions, and limitations
- `tests/`: focused automated tests

Write generated results only beneath:

`/Users/jvidale/Documents/Research/IC/YKA-ILAR_Rotation/Output/<YYYYMMDD_HHMMSS>/`

Every run must use a new timestamped directory and include a frozen copy of the configuration and selection manifest. Never overwrite an earlier run.

## Pair scope and external station selection

Process the seven pairs for which the available right-hand PNG panel matches
the workbook event pair, plus P35 through the all-stations workflow:

- P31: events 723 and 757
- P33: events 725 and 749
- P34: events 726 and 753
- P35: events 727 and 752; include because it lies within the time interval of
  interest even though no matching station-selection plot is available. The
  YKA data do not match the expected pattern and ILAR is too noisy.
- P355: events 729 and 829
- P37: events 731 and 747
- P38: events 732 and 750
- P39: events 733 and 745

Defer these pairs:

- P30 figure: ignore the displayed event combination. The master list assigns
  the latter event shown in that plot to pair X15, rather than listing the
  plotted combination as a matching pair.
- P43: ignore for this seismogram set because event 757 has no data in this set
  and the pair is outside the time window of greatest interest
- P63: the available PNG duplicates the P39 event combination rather than workbook P63

Also defer event 744 until its intended partner and station-selection rule are resolved.

For each processed pair, include only stations whose correlation printed in the matching right-hand panel is greater than or equal to 0.90. Treat those posted values as an external, fixed selection criterion. Record the pair label, both event IDs, network, station, posted correlation, and source-figure path in `station_selection.csv`.

Allow configuration to select either this external station population or every
exact `network.station` BHZ intersection for the event pair. When all stations
are evaluated, retain the full analysis table and separately report every
station whose newly calculated correlation is greater than or equal to the
configured `selection_correlation_threshold`.

If a printed label or value is not confidently legible, flag it for review rather than guessing. A selected seismogram must have a matching BHZ trace for both events. Match exact `network.station`, verify station coordinates, and permit differing location codes only when coordinates agree. Report all missing, ambiguous, or one-sided members in the exceptions table.

Do not remove a selected station merely because the newly calculated correlation or signal-to-noise ratio is lower. Record and flag the discrepancy instead.

## Event metadata and P arrivals

Resolve event IDs and origin times through the workbook `events` sheet. Use the `lat`, `lon`, and `depth` values from the `pairs` sheet after verifying that they match `LAT`, `LON`, and `DEP` for both corresponding event rows. The seven selected pairs have already passed this coordinate-consistency check.

Calculate direct `P` arrivals with ObsPy TauP model `ak135`, using workbook event coordinates, origin time, and station coordinates from the SAC headers. Do not silently substitute `Pdiff`, `PKP`, or another phase when direct `P` is unavailable; record the station as an exception.

Where a SAC `t0` value labeled P exists, compare it with the calculated arrival for quality control. Continue to use the calculated arrival as the analysis reference, but record `calculated P - header P`. Flag discrepancies larger than 2 seconds.

## Preprocessing

Process vertical BHZ traces only. The response has reportedly already been removed, but the SAC headers do not define physical amplitude units, scale, or response metadata. Therefore:

- label absolute amplitudes and noise RMS values as `stored trace amplitude units`;
- report correlation, normalized noise, signal-to-noise ratio, and normalized residual statistics as dimensionless;
- do not claim displacement, velocity, or acceleration units without separate provenance.

For every trace:

1. Validate timing, sampling metadata, finite samples, gaps, and clipping indicators.
2. Remove the full-trace mean and linear trend.
3. Apply a short start taper.
4. Apply a one-pass causal fourth-order Butterworth 1-3 Hz bandpass in second-order sections at the native sampling rate.
5. Exclude the documented causal-filter startup transient from the usable noise interval.
6. Polyphase-resample the filtered trace to 100 samples per second.

Upsampling provides a common processing grid but does not increase the original waveform bandwidth or information content.

## Alignment and symmetric normalization

Use a 10-second correlation window from 1 second before through 9 seconds after the calculated P arrival: `[P-1 s, P+9 s)`.

For each event trace, remove the correlation-window mean before calculating correlation. Search lags from -2 to +2 seconds and maximize the signed Pearson correlation coefficient, not its absolute value. Refine the discrete maximum parabolically to obtain a sub-sample lag. Do not permit polarity reversal. Flag an optimum at either lag boundary.

Normalized correlation is already invariant to positive amplitude scaling. For the residual analysis, normalize the aligned traces symmetrically so neither earthquake is an amplitude reference:

`u(t) = x(t) / s_x`

`v(t) = y(t + tau) / s_y`

where `s_x` and `s_y` are the respective RMS amplitudes in the aligned 10-second correlation window. Retain and report `s_x`, `s_y`, and their ratio.

## Signal-residual and noise measurements

Measure the aligned normalized residual over exactly 30 seconds from 1 second before through 29 seconds after P: `[P-1 s, P+29 s)`.

For each event trace, define usable noise as the filtered record from the end of the filter-startup exclusion through 1 second before calculated P. Divide it into non-overlapping 30-second chunks. Reject only objectively invalid chunks containing gaps, nonfinite values, or clipping. Retain real transient energy so the estimated noise environment is not artificially quiet.

For each trace, report:

- median 30-second noise-chunk RMS in stored trace amplitude units;
- 16th and 84th percentiles of chunk RMS;
- usable noise duration and valid chunk count;
- correlation-window RMS `s`;
- normalized noise level `sigma_n / s`;
- signal-to-noise measures and QC flags.

Use the median chunk RMS as the robust primary noise estimate. Report unusually large chunks separately rather than silently deleting them.

The symmetric descriptive residual-to-noise ratio is:

`R_sym = RMS(u - v) / sqrt[(sigma_nx / s_x)^2 + (sigma_ny / s_y)^2]`

This statistic is unchanged when the two events are swapped.

## Empirical noise null and assessments

Construct a trace-level empirical null from every eligible combination of one 30-second noise chunk from event 1 and one from event 2. Apply the signal-derived symmetric normalization factors, but do not shift, align, or refit the noise chunks. The two noise records are treated as uncorrelated.

Require at least five valid 30-second noise chunks for each trace before assigning a trace-level assessment. With fewer chunks, still report descriptive metrics but classify the result as `indeterminate`.

Trace-level assessment:

- `same_within_noise`: observed normalized signal-residual RMS does not exceed the empirical noise-residual distribution's 95th percentile
- `different_beyond_noise`: observed normalized signal-residual RMS exceeds that 95th percentile
- `indeterminate`: insufficient noise support or a material QC failure prevents classification

The phrase `same_within_noise` means that the observed mismatch is compatible with the measured noise; it is not proof that the underlying source waveforms are identical.

For each earthquake pair, bootstrap the median residual statistic across stations and compare it with the corresponding bootstrapped median-noise null. Require at least two stations with valid trace-level classifications.

Pair-level assessment:

- `same_within_noise`: observed station-median residual does not exceed the pair null's 95th percentile
- `different_beyond_noise`: observed station-median residual exceeds that percentile
- `indeterminate`: fewer than two stations are classifiable or material QC failures prevent aggregation

Use a fixed random seed recorded in the configuration for reproducible bootstrap results.

## Figures

### Main pair overlay

Create one main plot for every processed event pair. For every externally selected station:

- superimpose the two aligned, symmetrically normalized traces;
- plot from 10 seconds before through 40 seconds after calculated P;
- use blue for workbook event `index1` and red for `index2` consistently;
- sort station rows by epicentral distance, with the largest distance at the top;
- place station baselines at uniform six-normalized-amplitude-unit intervals;
- use the same trace gain, baseline spacing, colors, time limits, and general layout for every pair;
- do not rescale individual station rows to improve appearance.

Annotate every station row with:

`NET.STA | CC=<new correlation> | N1=<sigma_n1/s_1> | N2=<sigma_n2/s_2> | noise explains mismatch: YES/NO/INDET`

Map `YES` to `same_within_noise`, `NO` to `different_beyond_noise`, and `INDET` to `indeterminate`. Keep posted selection correlation, absolute noise values, uncertainties, chunk counts, and detailed QC in the tables and diagnostic figures rather than overcrowding the main overlay.

### Station diagnostics

Create one diagnostic PNG per processed station pair showing:

- alignment and analysis windows;
- aligned normalized traces;
- normalized residual;
- each trace's noise estimates and chunk distribution;
- empirical null distribution and observed residual;
- posted and newly calculated correlations;
- lag, RMS normalizations, `R_sym`, assessment, and QC flags.

### Pair summary

Create a compact summary PNG for each pair containing station count, median `R_sym`, range, median new correlation, pair-level null comparison, final assessment, and QC/exception counts.

## Tabular outputs and run manifest

Each timestamped run directory should contain at least:

- frozen `analysis_config.json`
- frozen `station_selection.csv`
- `station_results.csv`
- `stations_meeting_correlation_threshold.csv`
- `pair_results.csv`
- `noise_chunks.csv`
- `exceptions.csv`
- `run_manifest.json`
- `pair_plots/`
- `station_diagnostics/`
- `pair_summaries/`

Record input paths, file timestamps or hashes, software versions, random seed, processing parameters, run start/end time, and all exclusions in the run manifest.

## Tests and verification

Add focused synthetic/unit tests for:

- workbook event and pair resolution;
- coordinate-consistency checks;
- exact `network.station` intersection and missing-member reporting;
- direct-P availability and time-window bounds;
- causal filtering and unequal native sample rates;
- resampling to 100 samples per second;
- signed mean-removed lag correlation and sub-sample refinement;
- symmetric normalization and event-order invariance of `R_sym`;
- exact `[P-1, P+9)` and `[P-1, P+29)` windows;
- 30-second noise chunking and robust statistics;
- empirical null construction without noise alignment;
- minimum noise/station requirements and all three assessment states;
- non-overwriting timestamped output creation.

Before interpreting results, verify that every selected row maps to two intended SAC files, every plotted label agrees with the results table, all expected outputs exist, no source input changed, and the pre-existing unrelated Git changes remain untouched.

Implementation tests validate the processing code; they do not constitute scientific validation of the same/different conclusions.
