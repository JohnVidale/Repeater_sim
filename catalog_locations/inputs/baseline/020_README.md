# Repeater P-wave noise comparison

## Active multiphase phase selection (2026-09-05)

The multiphase workflow excludes PcP and ScP from measurements, common-time
estimation, and relative-location fits. The preferred fit uses P, Pdiff, and
PKP, and the P-only fit is retained as a diagnostic. Pdiff is measured only
from 100 degrees through distances below 110 degrees, filling the direct-P
shadow-zone gap while remaining separately labeled in plots and tables. PKiKP
is measured and plotted but is not used in a relative-location fit. PKIKP
remains a plot annotation only. Existing output folders retain their historical
phase selections and have not been regenerated.

Each active multiphase correlation window is centered on an accepted automatic
AIC pick for that phase and event. TauP ak135 supplies only the prediction
around which the picker searches. The reported total event-2-minus-event-1
shift is the difference between the two picked-arrival offsets plus the
correlation residual lag. The saved phase-measurement table retains the two
pick offsets, SNRs, acceptance states, and rejection reasons.

The active configuration searches from 21 s before to 21 s after each TauP
prediction and accepts automatic picks up to 20 s from the prediction for all
measured phases. The extra 1 s search margin preserves the separate
near-search-edge quality check at the requested 20 s tolerance.

The P-wave-only workflow documented below is a separate analysis.

`calibrate_pair_parameters.py` provides a guarded recalibration path for the
three coupled pair parameters. Its default preview mode computes a direct-P
common centroid, a pair-relative `new time shift`, and a common
`pick align shift` without modifying `ICevents_full.xlsx`. It writes current,
candidate, and change columns to `pair_calibration_candidates.csv`; a pair is
eligible for adoption only when all three calculations succeeded. The
canonical workbook hash is recorded so a later adoption is rejected if the
workbook changed after preview. Adoption is an explicit second command and
writes `new_lat`, `new_lon`, `new_depth`, `new time shift`, and
`pick align shift` together, with one timestamped backup:

```bash
conda run -n vidale_main python calibrate_pair_parameters.py
conda run -n vidale_main python calibrate_pair_parameters.py \
  --adopt-candidates outputs/pair_calibration_preview_TIMESTAMP/pair_calibration_candidates.csv
```

Station/phase manual pick corrections are applied in both workbook and
newly-computed common-shift modes, so a calibration preview honors the same
reviewed waveform adjustments as an ordinary workbook-driven run.

`plot_station_pair_summaries.py` transposes the pair-oriented measurement
table into one station-centric PNG per station. Each figure shows all 16 event
pairs on a common x axis, with separate phase colors and accepted, rejected,
or manually excluded marker shapes for differential shift, correlation, and
minimum event SNR.

The main multiphase run also writes `station_waveform_plots/`, containing one
station-and-phase waveform comparison per PNG. Each row is one available event
pair, using the same absolute-time trace alignment, phase markers, AIC picks,
trace colors, and acceptance labeling as the pair-oriented phase plots.

When `common_time_shift_source` is `workbook`, the pair-level `pick align shift`
is supplemented by optional station-and-phase values from the workbook named by
`manual_pick_alignment_workbook`. Values are read from rows whose Metric is
`Manual pick alignment shift (s)`. Each correction shifts the predicted phase
reference equally for both events before AIC picking, noise and SNR calculation,
correlation-window extraction, and differential-time measurement. It therefore
can change the selected picks, SNR, correlation, acceptance, differential time,
and relocation inputs. A positive value moves each waveform earlier relative to
the calculated phase marker on the plotted time axis.
The configured working matrix is stored beside `ICevents_full.xlsx` in the
shared `Array_codes/Files` directory; timestamped output folders may retain
copies for run provenance. After a successful workflow and test pass,
`run_repeater_workflow.py` refreshes the working matrix's Status, Differential
time shift, Correlation, and Minimum SNR rows from the new
`phase_measurements.csv`, leaves all manual-shift cells unchanged, and saves an
identical matrix snapshot in the run output directory.

A station-phase status of `X` in the working matrix is read before analysis.
That trace pair is still picked, measured, and plotted, but it is marked
ineligible for the differential-location fit. The four calculated cells for
that station-pair entry are highlighted yellow. Accepted `A` status cells are
blue. Non-zero manual pick-alignment shifts are orange, while zero and blank
manual shifts have no background fill. Every `X` present when a run starts is
retained during the workbook refresh, including when processing produces no
measurement row.

The station-phase label appears only on each Status row. Numeric differential
times with absolute value at most 0.05 s, correlations at least 0.85, and
minimum SNR values at least 1.0 are shown in green; values outside those display
thresholds remain red.

This program implements the workflow in `PLAN.md` for the eight currently
supported repeating-earthquake pairs. It tests whether the residual between
two aligned, vertical teleseismic P-wave traces is compatible with the pre-P
noise measured on those traces. It does **not** attribute a difference to the
earthquake source: propagation, timing, location, and instrumentation remain
possible contributors.

## Files

- `compare_repeater_pwaves.py` is the command-line analysis and plotting tool.
- `analysis_config.json` freezes input paths and processing parameters.
- `plot_station_pair_summaries.py` makes all-pair diagnostic plots for each
  station from a multiphase `phase_measurements.csv` file.
- `station_selection.csv` is the auditable transcription of external station
  selections from the right-hand panels of the source PNGs.
- `tests/test_compare_repeater_pwaves.py` contains synthetic/unit tests for the
  numerical and data-contract behavior.

One crowded group of labels in P38 is marked `review` in the selection manifest
because the text is not confidently legible. It is written to `exceptions.csv`
and is not silently treated as selected stations. Resolve this row against a
clearer source before a definitive scientific run. The formerly crowded P34
group is resolved as GT.VNDA, IU.SBA, and IU.LVC.

The figure path in the original plan contained a duplicated directory name.
The configuration uses the verified on-disk path:

`/Users/jvidale/Documents/Research/IC/YKA-ILAR_Rotation/rotation non-IC figures`

## Environment and commands

The implementation requires Python plus NumPy, SciPy, ObsPy, openpyxl, and
Matplotlib. The existing `vidale_main` conda environment supplies them.

Validate the workbook pair mapping and selection manifest without reading SAC
samples or writing an output directory:

```bash
conda run -n vidale_main python compare_repeater_pwaves.py --validate-only
```

Event hypocentres are read from the `events` sheet columns `lat_best`,
`lon_best`, and `depth_best`. The older `LAT`, `LON`, and `DEP` columns are
retained in the workbook for comparison but are not used by the analysis.

Run the focused implementation tests:

```bash
conda run -n vidale_main python -m unittest discover -s tests -v
```

Run the analysis:

```bash
conda run -n vidale_main python compare_repeater_pwaves.py
```

At successful completion, the program reports wall-clock elapsed time and
Python-process CPU time in seconds. Full runs also save both measurements as
`elapsed_time_seconds` and `cpu_time_seconds` in `run_manifest.json`.

`--config PATH` and `--selection PATH` select alternate frozen inputs. A full
run creates exactly one new directory named `YYYYMMDD_HHMMSS` below the
configured output root. Creation is exclusive: if that directory already
exists, the program fails instead of overwriting it.

During a full run, the terminal reports `Station evaluations completed: X/Y`
after every twentieth attempted station and at final completion, with the pair,
station ID, and whether that evaluation completed or failed. Failed attempts
advance the counter because their details are retained in `exceptions.csv`.
Pair waveform overlays and per-station diagnostic plots are created only for
successfully analyzed stations whose newly calculated correlation is greater
than or equal to `selection_correlation_threshold`. Tabular results and pair
statistics continue to retain all successfully analyzed stations. Each plotted
trace is annotated at upper left on two lines: station ID, epicentral distance,
and event-to-station azimuth above the newly calculated correlation and compact
signed event-2 shift after predicted-P alignment. The shift sign follows
`y(t + shift)`. Noise levels and noise-mismatch assessments remain in the
tabular outputs but are not printed on the plots.

`station_evaluation_mode` in the JSON configuration controls the station
population. `"selected"` analyzes only confirmed rows in
`station_selection.csv`; `"all"` analyzes every exact `network.station` BHZ
intersection between the two events. Coordinate-incompatible or ambiguous
trace pairs are recorded as exceptions. The active configuration uses `"all"`.
P35 is included only through this all-stations path because no matching external
station-selection panel is available. Its YKA data do not match the expected
pattern and its ILAR data are too noisy, but the pair lies within the time
interval of interest.

## Processing contract

In selected mode, each exact `network.station` selected externally at posted
correlation greater than or equal to 0.90 requires a BHZ trace for each event.
In all mode, the candidate population is the exact `network.station`
intersection of the two BHZ inventories, independent of the external
selection. Different SAC location codes are allowed only when station
coordinates agree. Pair-sheet coordinates are checked against both event rows
before any waveform processing.

Direct P arrivals are selected from exact `P` predictions calculated with TauP
`ak135`. There is no substitution of Pdiff, PKP, or another phase. In these
files, a SAC `t0` labeled P is a travel time from the catalog origin even though
the record starts about 100 seconds before origin; it is retained only as a
quality-control comparison. Calculated P is always the analysis reference.

For plotting only, TauP also requests `pP`, `sP`, and `PP`. When present
in the display window, the earliest arrival of each exact phase name is marked
and labeled for event 1 only. These additional phase predictions do not change
alignment, correlation, or assessment.

Each full trace is demeaned and linearly detrended, tapered only at its start,
causally filtered once with a fourth-order 1-3 Hz Butterworth filter in
second-order sections, and polyphase-resampled to 100 samples/s. The configured
20-second startup exclusion is omitted from noise. Upsampling standardizes the
grid but adds no waveform information or bandwidth.

The signed, mean-removed Pearson correlation is maximized over lags from -2 to
+2 seconds in the exact half-open window `[P-1, P+9)`. The discrete maximum is
refined parabolically. With the reported convention, the aligned second trace
is `y(t + lag)`; polarity is never reversed.

For residual analysis, the respective correlation-window RMS values are
`s_x` and `s_y`, and

```text
u(t) = x(t) / s_x
v(t) = y(t + lag) / s_y
```

The observed residual RMS uses exactly `[P-1, P+29)`. Pre-P noise is divided
into non-overlapping 30-second chunks after the startup exclusion. Chunks are
anchored backward from `P-10`, so the final complete noise window ends exactly
10 seconds before the predicted P arrival. The primary noise estimate is the
median chunk RMS. Large chunks are reported using the configured
median-absolute-deviation rule; they are not deleted.

The symmetric descriptive statistic is

```text
R_sym = RMS(u - v) / sqrt[(sigma_nx / s_x)^2 + (sigma_ny / s_y)^2]
```

The empirical null contains every combination of one event-1 noise chunk and
one event-2 noise chunk after applying `s_x` and `s_y`. Noise chunks are not
shifted, aligned, or refit. A trace needs at least five chunks from each event
and no material QC failure. Its observed residual is
`same_within_noise` at or below the null 95th percentile and
`different_beyond_noise` above it; otherwise it is `indeterminate`.

For a pair, the reproducibly seeded bootstrap resamples stations and one null
value from each sampled station. The observed station-median residual is
compared with the bootstrapped median-noise null's 95th percentile. At least two
classifiable stations are required.

## Outputs and units

Every run freezes its configuration and selection CSV and writes:

- `station_results.csv`, `pair_results.csv`, `noise_chunks.csv`, and
  `exceptions.csv`; the exception report includes epicentral distance in
  degrees whenever a coordinate-consistent trace pair was identified;
- `stations_meeting_correlation_threshold.csv`, containing every successfully
  analyzed station whose newly calculated correlation is greater than or equal
  to `selection_correlation_threshold`;
- `run_manifest.json`, including input SHA-256 hashes, file metadata, software
  versions, parameters, exclusions, times, and the seed;
- pair overlays, per-station diagnostics, and pair summaries in their named
  subdirectories.

Absolute amplitudes, RMS noise, and `s_x`/`s_y` are labeled **stored trace
amplitude units** because the SAC headers do not establish physical units.
Correlations, normalized noise, SNR, normalized residuals, and `R_sym` are
dimensionless.

Implementation tests establish code behavior only. They are not scientific
validation, and `same_within_noise` means compatibility with measured noise,
not proof of identical source waveforms.
