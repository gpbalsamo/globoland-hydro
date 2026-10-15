# forcing/

WFDE5_CRU_GPCC acquisition and preparation for ecLand.

Status: **`download_wfde5.py` run for real (one real month downloaded and
assembled); `preprocess_wfde5.py` written and used in a real one-day ecLand
pilot** — see `PLAN.md` Milestones 1 and 3.

- `download_wfde5.py` — CDS retrieval of the `derived-near-surface-meteorological-variables`
  dataset, global 0.5°, generalised from `liaise-ecland/forcing/get_liaise_forcing_05_cds.py`
  (see `docs/migration_from_liaise.md`) by removing the regional crop step.
  Supports `--months` for a cheap single-month first request and `--dry-run`
  to print the exact CDS requests/output paths without calling CDS or
  writing anything. **Run for real 2026-09-17**:
  `forcing/WFDE5_CRU_GPCC_1988_01-01.nc` (1.2 GB, 744 hourly steps).
- `preprocess_wfde5.py` — **not** a port of
  `liaise-ecland/forcing/prepare_liaise_forcing_ecland.py` (that script only
  handles year-boundary endpoint stitching; a genuinely new problem showed
  up first). Converts a `download_wfde5.py` file into ecland's own
  `met_2DHT_<site>.nc` forcing format (variable renames, `Wind` split into
  fictitious-direction `Wind_E`/`Wind_N` components — ecLand's physics uses
  speed only — and, critically, numerically-safe fill values for WFDE5's
  masked ocean cells: filling them with `0.0` crashed `ecland-master-dp`'s
  surface-exchange physics on the very first timestep, since WFDE5 is
  land-only and `Tair=0 K`/`PSurf=0 Pa` are not physically representable.
  See `PLAN.md` Milestone 3 and `run/README.md`. Covered by
  `tests/test_preprocess_wfde5.py`.
- `validate_wfde5.py` — structural QC (dimensions, coordinate ordering, units,
  fill values, timestamps) with a `--strict` mode. See `docs/forcing_variables.md`
  for the variable/unit table this validates against. **Not started** — this
  is the script that must actually answer `docs/forcing_variables.md`'s open
  questions (longitude convention, latitude ordering, timestamp semantics)
  against real downloaded data; `download_wfde5.py` deliberately does not
  assert any of that itself.
- `inspect_grid.py` — quick grid-shape/coordinate report for any WFDE5 file.
  **Not started.**

No forcing data is committed here. See the repository `.gitignore`. The
recommended first real invocation, once you're ready to spend CDS quota, is
one month of one year:

```bash
python3 forcing/download_wfde5.py --start-year 1988 --end-year 1988 --months 01 \
    --output-dir forcing/WFDE5_CRU_GPCC
```

not a full year or multi-year range — see the script's own docstring for the
peak-memory reasoning (a global 0.5° field is much larger than the LIAISE
crop this logic was validated against).
