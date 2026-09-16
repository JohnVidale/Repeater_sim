# Validation

On 2026-09-13, `vidale_main` passed all 10 subsystem unittest cases. Tests cover transitive membership and invalid endpoints, robust medoid/date-line/tie behavior, signed vector geometry, catalog priority and ambiguous matching, UTC conversion, depth quality and invalid coordinates, an independently inspected official HDF record, offline byte-for-byte numeric reproduction, checksum rejection, output-overwrite refusal, cross-event catalog-ID collision/incomplete-cluster blocking, and extraction agreement with the frozen workbook.

Two independent offline numeric runs produced identical JSON/CSV bytes, including their input manifests. No waveform processing or production test suite was run: production code was not modified. These tests establish implementation behavior, not scientific location accuracy or repeater overlap.

The delivered figures were rendered and visually inspected. Differential component panels supplement the vector overview so pair-specific values and marginal bootstrap errors remain legible. Exact runtime versions are in environment.json.

All 32 original source files in baseline_manifest.json matched their frozen SHA-256 values after the work. Initial tracked/untracked Git status was preserved; the sole new repository item is catalog_locations/. The copied inputs include both workbooks, production config/code, documentary provenance and two existing differential run variants. No production file, active configuration or workbook location was replaced.

The historical preferred-location artifacts named in project notes were not recovered in the searched locations. Original workbook columns therefore retain an explicit provenance limitation. All new proposals have downloaded official catalog records and checksums.
