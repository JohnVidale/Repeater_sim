# Reproducible catalog locations — review subsystem

This directory is independent of the production waveform pipeline. It contains a frozen input release, official raw catalog downloads, code, tests, and content-versioned proposals. No production workbook writer exists here. Neither `analysis_config.json` nor `ICevents_full.xlsx` is changed by this workflow.

Use Python 3.10+ for offline processing; the project environment `conda run -n vidale_main python` provides matplotlib for QC and openpyxl for read-only workbook freezing. No production modules are imported. The current input release is self-contained: external absolute paths in manifests are provenance, not runtime dependencies.

From this directory:

```sh
conda run -n vidale_main python -m unittest discover -s . -p 'test_*.py'
conda run -n vidale_main python workflow.py
conda run -n vidale_main python qc.py runs/<printed-run-id>
```

Existing output directories are never overwritten by `workflow.py`. To reproduce a run for comparison, give `--output /private/tmp/catalog-reproduction-unique-name`. All numeric JSON/CSV outputs should be byte-identical for the same frozen inputs and code. Plot rendering can depend on matplotlib/font versions. `run_manifest.json` hashes every input and root Python/config file; `output_checksums.json` hashes all final artifacts. Failed runs must not be treated as complete: only a run containing both REVIEW.md and output_checksums.json is a delivered QC package.

## Location rule

The declared rule in `config.json` is proposed, not adopted. Read each delivered `REVIEW.md` for numerical results.

1. Normalize workbook headers without importing production loaders. Validate IDs, connect all valid pair-table edges, and retain entire components touching the configured active pairs. Count each member once; pair frequency does not add weight. Components are graph groups, not confirmation of physical rupture overlap. Retain excluded pair rows for audit.
2. Search using original event `LAT/LON/DEP`, falling back to the event NEIC columns only if unavailable. Never use `lat_best`, pair centroids, `new_*`, station acceptance, waveform offsets, or earlier relocation files as match seeds or absolute-location fallbacks. Original column provenance is not assumed to be ISC-EHB.
3. Prefer official ISC-EHB HDF geographic hypocentres. Match using absolute origin-time residual <=30 s and spherical distance <=100 km. Sort candidates deterministically; more than one candidate in the first nonempty catalog blocks selection instead of choosing the nearest. Duplicate catalog IDs assigned to different workbook events block all involved events. IDs, signed time/depth residuals, spatial residual, source file/year/line, source catalog, and depth-quality evidence are retained.
4. If no EHB match exists (including outside its 1964–2021 release coverage), try the USGS ComCat preferred hypocentre under the same gates. If absent, leave unresolved. This is an explicit two-catalog hierarchy with no hidden workbook fallback. Missing EHB files fail processing rather than trigger fallback. Network acquisition and matching are separate stages.
5. For complete clusters choose the unweighted epicentral medoid: the member latitude/longitude minimizing summed great-circle distance to all other members, using Earth radius 6371.0088 km. Resolve an exact tie by smallest workbook event ID. Choose median member catalog depth, averaging the two middle depths for even counts. All fallback members receive equal weight. Incomplete clusters have no proposed reference. Save an EHB-only sensitivity reference and fallback-induced horizontal/depth change. No formal centroid uncertainty is claimed.

This medoid convention is resistant to an isolated distant epicentre and handles the date line, but two-member ties select the first event and mixed-catalog biases remain. Depth-quality classes do not control weighting. HDF flags and errors are retained; only confidently mapped ISC classes are assigned and other cases remain `Not recovered`. USGS values are never assigned EHB quality classes. Review gates, fallback weighting, and cluster membership before adopting any location.

## Inputs and provenance

`inputs/baseline_manifest.json` identifies frozen workbook, production code/config, documentation, and differential-output copies by original path and SHA-256. `inputs/baseline/git_state.json` preserves initial Git status, commit, recent log, remote and tracked diff; untracked root Python files are copied separately. `inputs/workbook_tables.json` preserves all nonempty event and pair rows including old/new coordinates and comments. `inputs/study_*.json` are the explicitly selected graph inputs. `inputs/extraction_manifest.json` guards extraction integrity. `inputs/source_manifest.json` records every official download URL, time, byte count and SHA-256. Raw files are retained unmodified.

To make a new release, use a new directory and run `freeze.py --repo <repository> --destination <new-release>/inputs`; copy subsystem code/config there, then run `acquire.py` from that release. Acquisition fetches missing sources and verifies frozen existing sources; it does not silently refresh a catalog. Acquisition derives its time window from configuration and includes adjacent EHB years for year-boundary events. Processing rejects a match window wider than the frozen USGS requests. Do not replace this input release to refresh catalogs.

## Outputs and isolation

- `event_comparison.csv`, `working_pair_locations.csv`: original working locations and candidate catalog records, including available pair overrides.
- `matches.json`, `match_candidates.csv`: per-event decisions and accepted-gate candidates; ambiguities remain explicit, not manually guessed.
- `clusters.json`, `cluster_references.csv`, `member_deviations.csv`: common references, original member locations, east/north/horizontal/depth/3-D deviations and scatter; EHB-only sensitivity remains a separate field.
- `existing_differential_vectors.csv`: frozen source-run vectors and original bootstrap uncertainty fields. The two available recent run variants are identified individually, with their source manifests preserved. No run is asserted to be current merely from its directory name.
- `catalog_vs_differential_vectors.csv`: east/north, scalar magnitudes, vector difference and scalar difference reported separately; catalog errors do not become differential confidence intervals.
- `cluster_maps.png`, `match_depth_qc.png`, `existing_differential_vectors.png`, `REVIEW.md`: review package. Absolute cluster references never depend on QC or differential artifacts.

Production `compare_repeater_pwaves.resolve_catalog` checks pair/event best-coordinate consistency, which is unsuitable for retaining individual catalog locations. Direct-P `relocate_pair_fixed_depths.load_pairs` starts from pair coordinates and fits common location plus origin shifts. Multiphase/relative loaders can apply `new_lat/new_lon/new_depth` overrides. These components were inspected and frozen, not reused. Plotting here uses explicit local inputs instead of importing that hidden production state. The station-acceptance workbook is frozen for context only.

Sources: [ISC-EHB dataset and quality definitions](https://www.isc.ac.uk/isc-ehb/), [HDF format specification](https://download.isc.ac.uk/isc-ehb/format2.hdf), [USGS event query](https://earthquake.usgs.gov/fdsnws/event/1/), [GeoJSON fields](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php).
