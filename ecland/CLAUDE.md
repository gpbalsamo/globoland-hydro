# CLAUDE.md

Guidance for Claude Code, and any other coding agent (OpenCode, Codex-style
tools, etc.) working in this repository. If you are such an agent: read this
file, `PLAN.md`, and `docs/migration_from_liaise.md` before making changes.

## Scientific objective

Build a reproducible **global** historical ecLand → CaMa-Flood modelling
chain, driven by WFDE5_CRU_GPCC forcing. See `README.md` and
`docs/workflow.md` for the pipeline diagram. This repository generalises
[`liaise-ecland`](https://github.com/gpbalsamo/liaise-ecland) (a validated
regional instance of the same chain over the LIAISE/Ebro domain) — read
`docs/migration_from_liaise.md` before assuming any regional assumption
transfers globally, and before re-deriving something that project already
found and documented.

## The single most important rule in this repository

**Never claim a workflow step is working merely because the script exists. A
step is only working when it has been executed successfully and its
validation checks pass.** `PLAN.md`'s status labels (DONE / IN PROGRESS /
BLOCKED / NOT STARTED / NOT VERIFIED) exist to make this distinction
impossible to paper over — when you finish work, update the label to what is
actually true, not what was intended.

## Repository architecture

```
config/        wfde5.yaml, ecland.yaml, paths.example.yaml (paths.yaml itself
               is gitignored -- machine-specific, never committed)
forcing/       WFDE5 acquisition, preprocessing, validation
init_clim/     surfclim / soilinit construction on the exact ecLand grid
namelist/      ecLand + CaMa-Flood namelist templates
run/           ecLand run driver, restart chaining, water/energy budgets
cama_flood/    conservative runoff remap, CaMa-Flood routing
validation/    per-stage validation: forcing, runoff, discharge, water_balance
experiments/   one directory per experiment, metadata only, no output data
docs/          workflow, forcing-variable mapping, grid strategy, interface design
tests/         synthetic-fixture unit tests (must not require the real WFDE5 archive)
```

## Build / run / check commands

There is no working pilot yet (see `PLAN.md`). Once scripts exist:

```bash
# Python syntax check, repo-wide
python -m compileall .

# Shell syntax check
bash -n path/to/script.sh

# Any CLI script should support --help and (where meaningful) --dry-run
python3 forcing/validate_wfde5.py --help

# Unit tests against synthetic fixtures only -- must not need real WFDE5 data
pytest tests/
```

## Conventions

- Python: `argparse` CLIs, `pathlib` for paths, explicit logging, `--dry-run`
  where practical. `xarray`/`netCDF4` for NetCDF I/O.
- Shell: `set -euo pipefail` in every new script.
- No hard-coded machine paths (`/home/pad/`, `/perm/pad/`, `/scratch/`, or
  their equivalents on whatever machine you're on). Every path is an
  environment variable or a `config/*.yaml` entry with a documented default;
  `config/paths.example.yaml` shows the shape, `config/paths.yaml` (gitignored)
  holds the real values.
- Small, logical commits — one concern per commit, not one large opaque
  commit for a whole phase. `git status` and `git diff` before every commit.

## Forbidden / destructive actions

- Never push destructive changes to `liaise-ecland` — it is the reference
  repository this project generalises from, not a branch of this one.
- Never commit: large forcing datasets, ecLand output, CaMa-Flood map
  datasets, credentials, CDS API keys, or machine-specific paths. See
  `.gitignore` — if something doesn't fit an existing rule, add a rule rather
  than committing it once "to be safe."
- Do not launch a multi-decade global simulation without first passing the
  staged pilot (one day → one month → one year, each validated) — see
  `README.md` "Pilot strategy" and `PLAN.md` Milestone 3.
- Do not interpolate WFDE5 to the CaMa-Flood routing grid and treat that as
  additional hydrological information — see `docs/grid_strategy.md`. This is
  a scientific-validity invariant, not a style preference.

## Data policy

- No `*.nc`, `*.grib`, `*.zarr`, `*.bin` in git except tiny, hand-reviewed
  synthetic fixtures under `tests/fixtures/`.
- Real experiment output lives outside the repo (`experiments/<id>/` holds
  only the run's *metadata*: this repo's commit, ecLand's commit/version,
  forcing version, experiment ID, dates, grid, executable, namelist,
  hostname, start/end time).

## Grid invariants (see `docs/grid_strategy.md` for the full reasoning)

- The WFDE5/ecLand runoff-generation grid and the CaMa-Flood routing grid are
  different concepts and must never be conflated.
- `surfclim`, `soilinit`, and the ecLand forcing files must describe exactly
  the same grid: same axis order, same latitude direction, same longitude
  convention, same land mask. Never assumed — always checked by
  `init_clim/validate_init_grid.py` before a run is trusted.
- If flattening a grid to a 1-D point representation is necessary internally,
  the index convention must be documented and reversibility proven, not
  assumed.

## Water-conservation requirement

Any global remapping of runoff (ecLand → CaMa-Flood) must conserve water.
`cama_flood/validate_remapping.py` computes and reports the relative
conservation error for every tested period and fails (nonzero exit) above a
configurable tolerance. See `docs/cama_interface.md` for the exact pipeline
and the specific sign-convention bug (`total_runoff = -(Qs+Qsb)`, not
`Qs-Qsb`) that made this go wrong once already in the reference project.

## Explicit validation checklist for any forcing/grid/runoff change

Before trusting a change, verify (see `docs/forcing_variables.md` and
`docs/grid_strategy.md` for the specifics):

- dimensions, coordinates, ordering, longitude convention
- units, missing-value convention, timestamps
- accumulated vs. instantaneous variable semantics
- land mask agreement across forcing/surfclim/soilinit
- water-balance closure (area-weighted, not a plain grid-cell average)

## How to run a pilot test

Not yet possible — `PLAN.md`'s "Immediate next step" is the actual current
entry point. Once Milestone 1 exists, the one-day/one-month/one-year staged
pilot in `README.md` is the required sequence; do not skip stages.

## How to validate a change

1. `python -m compileall .` / `bash -n` on anything touched.
2. `--help` on any CLI script touched.
3. `pytest tests/` (synthetic fixtures only).
4. If the change touches forcing, grid, or runoff handling: run the relevant
   `validation/` check against real data if any exists yet, and update
   `PLAN.md`'s status label to match what was actually observed — not what
   was hoped for.
