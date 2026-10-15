![WFDE5-ecLand](docs/wfde5-ecland-banner.png)

# wfde5-ecland

Scripts and configuration to run [ecLand](https://www.ecmwf.int/en/research/modelling-systems/land-surface) — ECMWF's land-surface model — globally at 0.5° (88,373 land points) for 1988–2024, coupled to the CaMa-Flood river-routing model, and to prepare the routed discharge for scoring against real river gauges.

The meteorological forcing is WFDE5-CRU-GPCC (Cucchi et al., 2020, https://doi.org/10.5194/essd-12-2097-2020), 0.5°, hourly, retrieved from the [Copernicus Climate Data Store](https://cds.climate.copernicus.eu/). This repository generalises [`liaise-ecland`](https://github.com/gpbalsamo/liaise-ecland) — a validated regional instance of the same chain over the LIAISE/Ebro domain — from one basin to the globe.

## Requirements

- An ecLand executable, built separately — see
  [ECMWF ecLand](https://github.com/ecmwf-ifs/ecland) or the build walkthrough
  in [`ecLand4U`](https://github.com/gpbalsamo/ecLand4U). CaMa-Flood is
  compiled *into* `ecland-master-dp` for one-way coupling, so no second
  executable is needed once Milestones 4-5 land.
- ECMWF HPC modules for an actual run (not needed for anything below yet):
  `prgenv/intel`, `intel/2021.4`, `hpcx-openmpi/2.9`, `netcdf4/4.9.1`, `python3`.
- Python packages: `numpy`, `xarray`, `netCDF4`, `cdsapi`, `pyyaml` (see
  `pyproject.toml`); `pytest` for the test suite.
- A CDS API key (`~/.cdsapirc`) once forcing acquisition exists (Milestone 1)
  — for the *global* `derived-near-surface-meteorological-variables` request,
  much larger than any LIAISE-clipped pull.
- Shared ECMWF CaMa-Flood static data (`CMFDIR`) for
  `cama_flood/build_global_cmf_fixdir.sh`, once routing is exercised
  (Milestone 5).
- **No Git LFS needed yet.** Unlike `liaise-ecland`, this repo commits no
  validated ancillary/forcing/gauge data — see "Data policy" in `CLAUDE.md`.
  Real global surfclim/soilinit/forcing/CaMa-Flood inputs live outside the
  repo, referenced through `config/paths.yaml` (gitignored).

## Quick start

Seven steps take you from a clone to a validated global year. Each step says
what to expect when it worked. All paths are relative to the repository root.

Every step below has been executed for real; the one-year coupled pilot is
validated (see [Current status](#current-status)). What is *not* yet done is
budget closure and gauge scoring — those are called out where they apply
rather than implied by silence.

### 1. Clone and verify

```bash
git clone git@github.com:gpbalsamo/wfde5-ecland.git
cd wfde5-ecland
python3 scripts/benchmark.py --profile fast
```

*Expect:* `RESULT: PASS`, 3/3 checks (Python syntax, Bash syntax, synthetic
tests). This is the one command in this whole Quick start that is fully
working today — see `docs/agent_quickstart.md`. No `git lfs pull` step: there
is nothing checked into LFS here (see "Requirements" above).

### 2. Configure paths and CDS access

```bash
cp config/paths.example.yaml config/paths.yaml   # edit for your machine
```

`config/wfde5.yaml` already covers `1979-2024`; a `1988-2024` experiment
(matching the period `liaise-ecland` validated regionally) is a sub-range of
that, so no config edit is needed for the date range itself — only the
machine-specific paths, and your own `~/.cdsapirc` (never committed; see
`.gitignore`). **Status: real file, but nothing downstream consumes it yet.**

### 3. Get the forcing

```bash
python3 forcing/download_wfde5.py --start-year 1988 --end-year 1988 --months 01 \
    --output-dir forcing/WFDE5_CRU_GPCC
```

*Real, run 2026-09-17*: `forcing/WFDE5_CRU_GPCC_1988_01-01.nc` (1.2 GB, 744
hourly steps, global 360x720). Unlike `liaise-ecland` (IPSL mirror for
1988-2014 + CDS for 2015-2024), this repo's global request has only one
source — the CDS `cru`/`cru_and_gpcc` split (see `docs/forcing_variables.md`)
— since the IPSL mirror is a LIAISE-domain-specific product.
`forcing/validate_wfde5.py` (a dedicated structural-QC script) still does
**not exist** — the grid facts recorded in `docs/forcing_variables.md` so
far came from ad hoc inspection of this file, not an automated gate.

### 4. Install the ancillary fields

```bash
module load nco
init_clim/build_global_surfclim_soilinit.sh
```

*Real, run 2026-09-19*: `surfclim_GLOBAL_1988-2024.nc` (8.8 MB) and
`surfinit_GLOBAL_1988-2024.nc` (4.9 MB), 360x720. **Not** `init_clim.py` —
that script's own `osm_pyutils.grid_gaussian` import no longer resolves
against the current ecland checkout (see `docs/migration_from_liaise.md`'s
corrected entry). Uses ecland's own actively-maintained
`tools/create_forcing/ecland_create_forcing.py` instead, with a global
bounding box at cell-center corners matching WFDE5's real grid exactly —
`init_clim/validate_init_grid.py` confirms this (**PASS**).

### 5. Choose a namelist

`namelist/templates/namelist_ecland_50R1_ctl` — ecland's own official
`{}`-placeholder template (ecland VERSION 2.0.0), ported unchanged, the same
one its own `tests/2D_EU-001_20220101-20220102` test uses. Not
`liaise-ecland/namelist/create_liaise_namelist.sh`'s pattern — see
`namelist/README.md`.

### 6. Run ecLand

```bash
module load prgenv/intel intel/2021.4 hpcx-openmpi/2.9.0
run/run_ecland.sh
```

*Real, run 2026-09-19*: 1988-01-01 -> 1988-01-02, global 0.5°, 48 half-hour
steps, 106 seconds, using the real WFDE5 forcing and surfclim/soilinit
above. `run/run_ecland.sh` calls ecland's own official
`ecland_create_namelist.py` + `ecland_run_model.sh`, not a hand-rolled
driver. **A real bug was caught and fixed here**: WFDE5 is land-only
(unlike ERA5); naively filling its masked ocean cells with `0.0` crashed
`ecland-master-dp`'s surface-exchange physics on the first timestep — see
`run/README.md`.

For a full year, coupled, chained and archived, use the campaign driver
rather than the bare script:

```bash
# one validated year (1988): 0.70 h of model time on 128 cores
sbatch --time=06:00:00 --mem=64G --ntasks=16 --cpus-per-task=8 \
    run/run_ecland_cmf.slurm run/configs/year_1988_daily.env

# 1989-2024, each year chained from the previous year's restart
python3 run/submit_campaign.py --start-year 1989 --end-year 2024 \
    --restart-from run/output/Y1988_19880101-19890101/restartout.nc
```

**Chunking rule, enforced in `run/run_ecland.sh`**: output file size scales
with records per file (`N_HOURS / OUTPUT_FREQ_HOURS`). Measured here — one
year of *daily* output (366 records, 18 GB) and one month of *hourly* output
(744 records, 36 GB) both complete; one year of *hourly* output (8784
records, 424 GB) dies with SIGBUS on the final write. So **annual chunks use
daily output, and hourly output uses monthly chunks**. Anything above 750
records per file is refused with that reason.

### 7. Check the output

```bash
python3 run/check_run.py --output-dir run/output/GLOBAL_19880101-19880102
```

*Real, PASS*: `run.log` clean, `restartout.nc` present, zero NaN/Inf in any
`o_*.nc` variable (excluding ecLand's own `1e20` fill value over masked
cells). This is **not** a water/energy budget closure check —
`run/check_water_budget.py`/`check_energy_budget.py` (the *equation*,
`Rainf+Snowf+Evap+Qs+Qsb - DelIntercept-DelSoilMoist-DelSWE-DelAquifer ≈ 0`,
verified from `liaise-ecland`'s per-site version) are still **not started**;
the global, area-weighted aggregation code does not exist yet.

## Running coupled to CaMa-Flood

Milestone 4/5, **not yet available**:

```bash
python3 cama_flood/remap_runoff.py ...          # planned
python3 cama_flood/validate_remapping.py ...    # planned -- conservation gate, see docs/cama_interface.md
cama_flood/run_cama.sh ...                      # planned
```

`cama_flood/build_global_cmf_fixdir.sh` (+ its three vendored companion
tools) is already ported and already builds a genuinely global fix bundle at
any of `glb_15min`/`glb_06min`/`glb_03min`/`glb_01min` — but has not yet been
run in this repository. The runoff sign convention
(`total_runoff = -(Qs+Qsb)`, not `Qs-Qsb`) must be implemented from the
start, not discovered the way `liaise-ecland` did — see
`docs/cama_interface.md`.

## Scientific purpose

Build a reproducible global historical land-surface + river-routing modelling
chain:

```
WFDE5_CRU_GPCC hourly forcing
        |
        v
forcing acquisition / QC / unit conversion
        |
        v
ecLand 0.5-degree global
        |
        v
surface runoff + subsurface runoff
        |
        v
conservative runoff transfer
        |
        v
CaMa-Flood
        |
        v
Q / river storage / flood storage / flood diagnostics
```

See `docs/workflow.md` for the annotated version and `docs/cama_interface.md`
for the runoff-transfer step's design.

## Relation to `liaise-ecland`

[`liaise-ecland`](https://github.com/gpbalsamo/liaise-ecland) built and
validated the same ecLand-CaMa-Flood chain over a small regional domain (the
LIAISE campaign area, Ebro basin, Spain) across 37 years, three CaMa-Flood
routing resolutions, and against real river gauges. This repository is a
**global generalisation**, not a fork — regional assumptions (grid dimensions,
basin-specific dam/reservoir modelling, LIAISE campaign forcing products) are
intentionally left behind. What is carried forward is: code that was already
grid-agnostic, and hard-won correctness findings that would be expensive to
rediscover (a runoff sign-convention bug, a silently-broken restart chain, an
inherited environment variable that silently defeated multi-threading, and
several others). The full file-by-file reuse decision is in
[`docs/migration_from_liaise.md`](docs/migration_from_liaise.md).

## Role in the ecLand benchmark cascade

`wfde5-ecland` is the **global** stage of a wider, deliberately staged ecLand
validation cascade spanning several sibling repositories. Each level is
cheaper to run and to debug than the one below it, so a failure is meant to
be caught before an expensive global/decadal run is ever attempted:

```
LEVEL 0  SOFTWARE     official ecLand build + unit/ctest checks
              |
LEVEL 1  SITE          plumber2-ecland — point-scale process evaluation
              |         (energy, water, carbon, snow, soil moisture, fluxes)
LEVEL 2  REGION        liaise-ecland — regional forcing/grid consistency,
              |         surfclim/soilinit, spatial fluxes, regional CaMa-Flood
LEVEL 3  GLOBAL        wfde5-ecland (this repo) — global forcing, land water
              |         balance, snow/soil-moisture/runoff climatology
LEVEL 4  ROUTING       CaMa-Flood — global discharge, storage, flood diagnostics
              |
LEVEL 5  BENCHMARKING  GRDC / ifs-riverbench / real flood observations
```

- [`ecLand4U`](https://github.com/gpbalsamo/ecLand4U) — the gateway/build/
  learning layer (install, build, test, first-run instructions for the
  official [`ecmwf-ifs/ecland`](https://github.com/ecmwf-ifs/ecland)).
- [`plumber2-ecland`](https://github.com/gpbalsamo/plumber2-ecland) — Level 1,
  site benchmark.
- [`liaise-ecland`](https://github.com/gpbalsamo/liaise-ecland) — Level 2,
  regional benchmark (see "Relation to `liaise-ecland`" above).
- `wfde5-ecland` (this repo) — Level 3, global benchmark, plus Level 4
  (CaMa-Flood routing) wiring.

This repository does not duplicate the sibling repos' scientific code. It
exposes a small, deterministic **agent/orchestration interface** —
[`AGENTS.md`](AGENTS.md), [`docs/agent_quickstart.md`](docs/agent_quickstart.md),
[`docs/benchmark_contract.md`](docs/benchmark_contract.md), and
`scripts/benchmark.py` — so that a future cross-repo orchestrator (not built
here), or a low-footprint local coding agent (e.g. a 7B model run locally via
Ollama), can run and interpret each stage's checks without needing to read or
understand the full scientific codebase. See those documents for the current,
honestly-labelled state of that interface — most of it is scaffolding, not a
working pipeline yet (`PLAN.md`'s "Agent/cascade interface" milestone).

## WFDE5 forcing choice

The first (and, for now, only planned) forcing is **WFDE5 with CRU+GPCC
precipitation correction** (the `derived-near-surface-meteorological-variables`
CDS dataset, `cru_and_gpcc` reference for precipitation, plain `cru` for
everything else — see `config/wfde5.yaml` and `docs/forcing_variables.md` for
why these two request types cannot be merged into one). ERA5 and MSWEP
precipitation-sensitivity comparisons are a later milestone (`PLAN.md`
Milestone 7), not a near-term goal.

## Spatial-resolution philosophy

Two grids, deliberately kept distinct — see
[`docs/grid_strategy.md`](docs/grid_strategy.md):

- ecLand runs on WFDE5's **native 0.5° global grid**. Runoff generation is not
  interpolated to a finer grid, because doing so would not create additional
  meteorological information, only the appearance of it.
- CaMa-Flood may route that same runoff at a much finer resolution (down to
  3 arcmin or finer), since river-network/channel-geometry resolution is a
  separate concept from runoff-generation resolution. The reference project
  measured a real, positive effect of finer *routing* resolution on discharge
  skill using *identical* runoff input — see `liaise-ecland/PLAN.md`'s
  resolution-comparison result — which is exactly the effect this separation
  is designed to isolate cleanly.

## Pilot strategy

No multi-decade global run is launched before a staged validation passes:

1. **Test A** — one day, global.
2. **Test B** — one month, global.
3. **Test C** — one full year, global, checked against a global water and
   energy budget before anything longer is attempted.

A well-observed large basin (Rhine, Mississippi, Amazon, or similar) may be
useful for fast end-to-end debugging, but does not replace the global
structural validation above. See `PLAN.md` Milestone 3 and Phase 10 of the
original migration specification for the reasoning.

## Reproducibility

Every experiment run through `run/run_ecland.sh` is expected to log its own
metadata: this repository's git commit, ecLand's own commit/version, the
forcing version used, an experiment ID, the date range, grid, executable
path, namelist, hostname, and start/end time (`PLAN.md` Milestone 3;
`experiments/<id>/` is where that metadata lands, without any output data
committed alongside it).

## Dashboards and forcing mirror: sites.ecmwf.int

[`sites.ecmwf.int/pad/wfde5/`](https://sites.ecmwf.int/pad/wfde5/) is this
project's ECMWF-internal site (`module load sites`, `sitesctl`), mirroring
the role `sites.ecmwf.int/pad/liaise/...` plays for `liaise-ecland`. Two
uses, both **not yet exercised**:

- **Dashboards/reports** — once `validation/` produces any (Milestone 6), or
  simply to publish a `benchmark.py` JSON report, `scripts/publish_site.sh`
  wraps `sitesctl site content upload` (auth token via `$ECMWF_WFDE5` by
  default, never printed; `--dry-run` prints the exact command without
  uploading). See `AGENTS.md` — an actual (non-dry-run) publish is visible
  to others and needs the same explicit go-ahead as a real data download.
- **Forcing mirror** — the plan is to also host pre-assembled global WFDE5
  files there to ease download, the way the IPSL mirror did for
  `liaise-ecland`'s 1988-2014 range. Nothing is hosted there yet, and
  `forcing/download_wfde5.py` does not know about this second source —
  that wiring is future work once files actually land on the site.

## Repository layout

```
config/        wfde5.yaml, ecland.yaml, paths.example.yaml
forcing/       WFDE5 acquisition, preprocessing, validation
init_clim/     surfclim / soilinit construction on the exact ecLand grid
namelist/      ecLand + CaMa-Flood namelist templates
run/           ecLand run driver, restart chaining, water/energy budgets
cama_flood/    conservative runoff remap, CaMa-Flood routing
validation/    per-stage validation: forcing, runoff, discharge, water_balance
experiments/   one directory per experiment, metadata only
docs/          workflow, forcing-variable mapping, grid strategy, interface design
tests/         synthetic-fixture unit tests (no real WFDE5 archive needed)
```

Each directory has its own `README.md` stating its real status and what it
generalises from `liaise-ecland`, if anything.

## Current status

The staged pilot required before any multi-decade run — one day → one month →
one complete year, each validated — has **passed**:

| stage | status |
|-------|--------|
| One day, global | **DONE** 2026-09-19, `check_run.py` PASS |
| One month, global, coupled | **DONE** 2026-09-20, `check_run.py` PASS |
| One complete year (1988), coupled | **DONE** 2026-09-23, `check_run.py` PASS |

The 1988 annual chunk runs in **0.70 h of model time** (0.93 h including
forcing preprocessing and ECFS archiving) on 128 cores, 7.4 GB of output on
disk, archived to ECFS and verified. Forcing for 1988–2024 is being retrieved.

Not done, and not to be read as done: **energy-balance closure,
water-balance closure and global runoff totals are NOT STARTED**.
`run/check_run.py` is a NaN/crash gate, not a budget-closure check.
`forcing/validate_wfde5.py` does not exist — forcing checks so far are manual
and not reproducible. Milestones 4–7 (CaMa interface validation, routing,
gauge scoring, forcing sensitivity) have not started.

See [`PLAN.md`](PLAN.md) for the itemised, honestly-labelled milestone list
(DONE / IN PROGRESS / BLOCKED / NOT STARTED / NOT VERIFIED).

## Roadmap

Milestones 0-7 in `PLAN.md`: repository migration → WFDE5 forcing → ecLand
climatology/init → pilot ecLand run → runoff-to-CaMa interface → CaMa-Flood
routing → validation against real river gauges and global water balance →
forcing sensitivity (ERA5, MSWEP).

## License

Not yet decided; matches whatever `liaise-ecland` settles on, given the
shared codebase.
