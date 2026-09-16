# Baseline inventory — 2026-09-13

The task checkout is `/Users/jvidale/.codex/worktrees/75e6/Repeater_sim`; the applicable AGENTS.md directs work to `/Users/jvidale/Documents/GitHub/Array_codes/Repeater_sim`, verified as the Git repository root. No ancestor AGENTS.md was found in /, /Users, the user home, Documents, GitHub, or Array_codes. The repository AGENTS.md repeats the supplied project-root instruction. No existing production file was edited.

Initial HEAD: `f036496` (Update multiphase relocation analysis). Remote: `git@github.com:JohnVidale/Repeater_sim.git`. Exact initial status, five commits, remote, and tracked patch are frozen in `inputs/baseline/git_state.json`. Seven tracked files were modified and six root/test files were untracked at task start; they remain user work. Root Python sources were copied without importing or executing production pipelines.

## Workbooks and current configuration

- Catalog and time-shift workbook: `/Users/jvidale/Documents/GitHub/Array_codes/Files/ICevents_full.xlsx`. Four sheets: pairs (994 physical rows, 61 columns), events (1001 physical rows, 23 columns), Multiplets, time_shift_history. The entire XLSX is frozen byte-for-byte, preserving unused sheets, formulas and formatting.
- Station-acceptance/manual alignment workbook: `/Users/jvidale/Documents/GitHub/Array_codes/Files/station_acceptance_matrix.xlsx`. Frozen byte-for-byte for provenance only; excluded from absolute-location processing.
- There are 147 nonempty event rows and 207 nonempty pair rows. 0 pair rows have missing event endpoints and are retained in excluded_pairs.json. Every configured active pair has valid endpoints.
- Active pairs: P30, P31, P33, P34, P35, P37, P38, P39, P51, P79, P112, P123, P140, P145, P321, P355. Connecting the complete valid pair table first yields 128 retained edges, 59 member events, and 13 study components. The extended membership includes events outside the 17 active pairs.
- Current config: threshold 0.875; shifts from workbook; centroid relocation False; centroid mode `fixed_depth`; relative depth `fixed_common`; model `ak135`; bootstrap 200. Full configuration is frozen, including all paths and station rules.

## Location meanings and provenance limits

`events.lat_best/lon_best/depth_best` are current common working coordinates. `events.LAT/LON/DEP` and `NEIC lat/lon/dep` are older individual-coordinate columns. Their original catalog identifiers are not present in the inspected event headers; do not label them ISC-EHB without a recovered source. `pairs.lat/lon/depth`, `new_lat/new_lon/new_depth`, `centroid_*`, and differential delta columns are separate retained location sets.

`Notes/ICrot_project_chat_summary.md` describes earlier catalog matching, common-depth/common-location workbooks, insertion of best coordinates, and later waveform-derived centroid updates. Its referenced output directory and named preferred-location artifacts were not found in the searched Array_codes, IC rotation, and YKA-ILAR_Rotation trees. This is documentary history, not a recovered per-event catalog-ID audit trail. The new ISC/USGS raw files provide a separate traceable basis.

`compare_repeater_pwaves.resolve_catalog` loads event best coordinates and enforces agreement with pair coordinates. `relocate_pair_fixed_depths` loads pair lat/lon/depth, obtains direct-P waveform picks and jointly fits common location/origin offsets. Multiphase and differential fit code can apply pair new_* overrides. The active config disables a fresh centroid relocation, but it does not erase existing overrides. The new subsystem neither imports these loaders nor uses their coordinates for absolute references.

Two existing September 12 output variants (cc0.8 and cc0.875) have frozen non-PKiKP differential CSVs, bootstrap fields, and source manifests. Their vectors are event 2 minus event 1. Their manifests identify relocated-centroid-when-available coordinates and Pdiff participation. They are comparison evidence, not fresh reruns or proof that either output exactly represents today's workbook/config. Station acceptance affects waveform measurements, never the proposed catalog reference.

## Proposed rule before adoption

Use unique ISC-EHB matches within ±30 s and 100 km of original event coordinates; use unique USGS ComCat preferred hypocentres only when EHB has no match; otherwise leave unresolved. More than one candidate or a cross-event catalog-ID collision blocks automatic assignment. Use each graph member once: epicentral medoid with lowest event ID for exact ties, and median member catalog depth. Retain fallback flags and an EHB-only sensitivity reference. No reference is adopted by computing this proposal. See README.md and the versioned REVIEW.md for all details and QC.
