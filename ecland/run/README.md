# run/

ecLand run driver and diagnostics.

Status: **one-day global pilot DONE and validated** (2026-09-19) — see
`PLAN.md` Milestone 3. Path taken generalises from ecland's own official
tooling (`/perm/pad/ecland/share/ecland/scripts/`), **not**
`liaise-ecland/run/run_liaise_ecland.{sh,slurm}` — that script targets an
older/different namelist convention; ecland's own `ecland_create_namelist.py`
+ `ecland_run_model.sh` are what its own currently-shipped test suite
(`tests/2D_EU-001_20220101-20220102`) actually uses, so this repo calls
those directly rather than reimplementing namelist patching.

- `run_ecland.sh` — stages surfclim/soilinit and a WFDE5-derived forcing
  slice (via `forcing/preprocess_wfde5.py`) into the exact directory layout
  ecland's official scripts expect, then calls them. Direct execution, no
  `sbatch`/`srun` — a one-day global run is tiny (matches `benchmark.yaml`'s
  `smoke` profile). Env-var driven (`STA`, `START_DATE`, `N_HOURS`,
  `ECLAND_ROOT`, `ECLAND_EXE`, `FORCING_SOURCE`, `SURFCLIM_SOURCE`,
  `SOILINIT_SOURCE`), no region name or grid dimensions hardcoded.
- `check_run.py` — minimal "did this actually run" check: `run.log` has no
  Fortran abort marker, `restartout.nc` exists, no NaN/Inf in any `o_*.nc`
  variable (excluding ecLand's own `1e20` fill value). **Not** a water/energy
  budget closure check — that's still planned, separate, and NOT STARTED.
- `check_water_budget.py` / `check_energy_budget.py` — **NOT STARTED**. The
  *equation and sign convention* from `liaise-ecland`'s copies (imported
  there, unmodified, from `plumber2-ecland`) are reused when written; the
  area-weighted **global** aggregation is new code, since the reference
  versions are per-site.
- `postprocess_ecland.sh` — **NOT STARTED**.
- `run_ecland_cmf.slurm` — batch wrapper for `run_ecland.sh`'s `RUN_CMF=true`
  path (see `cama_flood/README.md` for the coupled-run status). A 2-rank
  coupled run needs more memory than this project's interactive session's
  8 GiB cap allows regardless of run length -- submitted only after
  explicit user approval, per `AGENTS.md`'s sbatch/SLURM gate.

## Chunking rule: annual → daily, hourly → monthly

**Output file size scales with records per file = `N_HOURS / OUTPUT_FREQ_HOURS`.**
Measured on this system, global 0.5°, coupled:

| segment | output  | records | `o_gg.nc` | outcome |
|---------|---------|---------|-----------|---------|
| 1 year  | daily   |   366   |   18 GB   | completes (0.70 h) |
| 1 month | hourly  |   744   |   36 GB   | completes |
| 1 year  | hourly  |  8784   |  424 GB   | **SIGBUS on the final write** |

So: **annual chunks must use daily output; hourly output must use monthly
chunks.**

This is enforced, not just documented. `run_ecland.sh` refuses more than
`MAX_OUTPUT_RECORDS` (750) records per file — the ceiling is the largest
configuration actually proven to work here, not a guess at where it really
breaks. `run/submit_campaign.py --mode {annual,monthly}` sets it correctly and
refuses `--output-freq-hours 1 --mode annual` outright.

The 424 GB failure is a large-file **write** fault, not disk or quota: those
files are sparse, actual usage was 171 GB against 4.2 T free PERM. The limit
is bracketed but **not characterised** — `ALLOW_LARGE_OUTPUT=true` exists to
override the guard if someone wants to pin it down, and is not for production.

```bash
# annual + daily (the campaign default)
python3 run/submit_campaign.py --start-year 1989 --end-year 2024 \
    --restart-from run/output/Y1988_19880101-19890101/restartout.nc

# hourly output for one year -> 12 monthly segments
python3 run/submit_campaign.py --start-year 1995 --end-year 1995 \
    --mode monthly --output-freq-hours 1
```

## Requires (module load), confirmed 2026-09-19

`ecland-master-dp` is MPI-linked (HPC-X OpenMPI). Before running:

```bash
module load prgenv/intel intel/2021.4 hpcx-openmpi/2.9.0
```

Two gotchas found the hard way:
- Loading `nco` in the same `module load` command as this MPI stack (either
  order) silently breaks `LD_LIBRARY_PATH` again — load them in separate
  commands/scripts.
- **Never pipe a `module load` command's output** (e.g. `module load ... |
  tail -3`) — piping forks a subshell, and the environment changes it makes
  never reach the calling shell. Redirect (`module load ... >log 2>&1`)
  instead if you want to suppress the noisy "reloaded" message.

## A real bug this caught (2026-09-19)

WFDE5 is a land-only product (unlike ERA5, which has no ocean gaps).
`forcing/preprocess_wfde5.py`'s first version filled WFDE5's masked ocean
cells with `0.0`; `ecland-master-dp`'s `surfexcdriver_ctl` crashed with a
floating-point invalid-operation signal at `Tair=0 K`/`PSurf=0 Pa` on the
very first timestep. Fixed by filling masked cells with numerically-safe
reference-atmosphere constants instead — see that script's own
`MASKED_FILL_VALUES` and `docs/forcing_variables.md`.
