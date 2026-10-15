# AGENTS.md

Short contract for any coding agent. This is the GLOBAL, runoff-retaining instance of the
`<exp>-glofas` family and is deliberately NOT byte-identical to the six regional ones. Details in
`CLAUDE.md`, status in `PLAN.md`.

## Purpose
Run GloFAS v5 (LISFLOOD 5.0.0, operational configuration) globally on WFDE5 forcing, **retain the
runoff**, aggregate it to ecLand's 0.5 deg grid, and compare it with ecLand's `-(Qs+Qsb)`.

## Safe without asking
- reading anything; `git status/diff/log`; `pytest`; `bash -n`; any `--help`
- `glofas/prepare_meteo.py --days N` / `run_lisvap.py --days N` for a few days
- `glofas/make_settings.py` (writes a settings file only)
- `glofas/aggregate_runoff.py`, `glofas/compare_runoff.py` on existing output

## Needs explicit human approval
- any `sbatch`: `glofas/run_lisflood.slurm` (a global year is ~16 h on 8 cores), forcing arrays
- a whole year of `prepare_meteo.py` / `run_lisvap.py` (~8.5 h and ~70 GB of `$SCRATCH` together)
- `git push`; writing anywhere outside `work_dir`, `products/` and this repository
- editing the six `<exp>-glofas` repositories, `/perm/pad/liaise-glofas`, or `wfde5-ecland`

## Forbidden
- writing to `glofas_root` -- the GloFAS operational area is read-only input
- putting `work_dir` on `$PERM` (a 37-year run is ~2.6 TB of staging; `$PERM` is 10 TB in total)
- deleting anything under `wfde5-ecland/forcing/` -- that is the shared WFDE5 archive
- committing `work/`, `products/`, NetCDF, `.tss`, `config/paths.yaml`
- changing operational GloFAS options other than the paths, dates, `repDischargeMaps` and the two
  runoff map options -- and if a third is ever needed, re-run the output-only check in `PLAN.md`
- interpolating ecLand down to 0.05 deg and treating it as information (see `CLAUDE.md`)
- cold-starting each year to parallelise the campaign (it breaks the warm-start chain)

## Escalation
Two failed targeted fixes of the same check -> stop and report the log; do not loop.
