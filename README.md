# Repeater_sim

This repository measures differential teleseismic arrival times for 16
inner-core earthquake pairs and estimates their relative horizontal offsets.

Start with [`STATUS.md`](STATUS.md). It records the current scientific choices,
completed milestones, limitations, and immediate next steps. File locations are
explained in [`WORKING_LAYOUT.md`](WORKING_LAYOUT.md).

## Active files

- `analysis_config.json` controls the next run.
- `ICevents_working.xlsx` contains event and pair parameters.
- `station_acceptance_working.xlsx` contains station/phase A and X decisions
  plus manual window shifts.
- `latest_run/` contains the newest measurement tables and plots.

The active configuration uses a 0–5 s correlation window, CC >= 0.875, workbook
time shifts, fixed common depth, and P, PKP, and PKiKP measurements. P is the
primary location phase; P+PKP is the secondary sensitivity case. Pdiff, PcP,
and ScP are excluded.

## Run the active workflow

```bash
conda run -n vidale_main python run_repeater_workflow.py
```

The workflow measures arrivals, writes pair- and station-oriented plots, fits
relative offsets, estimates bootstrap uncertainties, runs tests, and refreshes
the station acceptance workbook. Generated runs are written under `outputs/`.

```bash
conda run -n vidale_main python -m unittest discover -s tests -p 'test_*.py'
```

## Other material

- `archive/` contains past runs, review pages, waveforms, and earlier working
  files. It is retained locally and ignored by Git.
- `catalog_locations/` is a reproducible, review-only absolute-location study.
  Its proposed catalog references have not been applied to the active workbook.
- `legacy/` contains superseded analyses and detailed historical notes. These
  files are retained for provenance and are not the current operating guide.
- The root `compare_repeater_pwaves.py` is a compatibility module because the
  active workflow still imports shared numerical helpers from the legacy
  P-wave implementation.

Update `STATUS.md` when the adopted settings, authoritative run, or next step
changes. Keep detailed numerical provenance in run manifests and output tables.
