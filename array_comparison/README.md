# YKA/ILAR array comparison

Run P38 through the isolated legacy array stack workflow using one settings
file:

```bash
conda run -n vidale_main python array_comparison/run.py
```

The only scientific switch currently exposed is
`include_relative_offset` in `settings/p38_yka_ilar.json`.

- `false`: both events use the common working-workbook reference location.
- `true`: event 2 minus event 1 uses the relative north/east offset in metres
  stored in `ICevents_working.xlsx:aligned_pairs`.

Both cases read their event reference times and coordinates from the workbook
`aligned_pairs` sheet.  That sheet applies the pair `pick align shift` once to
both events, then applies either the no-location `new time shift` or the
location-fit differential origin-time shift to event 2.  The staged legacy
code receives zero additional pair/common shifts, uses TauP ak135 PKiKP
alignment, applies no station-static table, and cross-correlates only after
stacking. Each run stages legacy code into a
new timestamped output directory and does not modify shared legacy code,
workbooks, waveforms, `latest_run`, or historical outputs. The detailed
`latest_run` CSV remains a fit and uncertainty record, but is not required by
this downstream array workflow.

The legacy adapter currently supports P38 and the three verified modes: YKA
40 s, ILAR 40 s, and normalized ILAR 17 s. Extend it to additional pairs only
after checking their input coverage and settings explicitly.

`run.py` validates settings, `p38_inputs.py` reads the workbook contract,
`legacy_adapter.py` stages protected legacy code, and the root driver handles
the isolated run, figures, and provenance.
