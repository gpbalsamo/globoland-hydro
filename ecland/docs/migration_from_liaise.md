# Migration matrix: liaise-ecland → wfde5-ecland

Phase 1 deliverable. Classification of every file the handoff prompt named, plus
a few more found by inspection, against `gpbalsamo/liaise-ecland` at commit
`ab8a0ab` (2026-09-17). Each file was actually opened and read — line counts and
"LIAISE-ish mention" counts below are grep counts against
`liaise|ebro|-5.75|46.75|39.25|5.25` (the LIAISE domain box), used only as a
quick signal of how domain-coupled a file is, not as the classification itself.

Categories, as specified: **A** reusable unchanged · **B** reusable after
generalisation · **C** LIAISE-specific, do not copy · **D** useful concept only,
reimplement cleanly.

## forcing/

| File | Lines | LIAISE hits | Class | Note |
|---|---:|---:|---|---|
| `get_liaise_forcing_05_cds.py` | 499 | 30 | **B** | The CDS request logic (dataset name, `cru`/`cru_and_gpcc` split, retry handling) is generic. The `CDS_VARIABLES_CRU`/`UNITS` tables (WFDE5 short names ↔ CDS long names ↔ units) are the single most valuable piece of *verified* knowledge to carry over — see `docs/forcing_variables.md`. What must be dropped: the per-year LIAISE bounding-box crop after download (this repo needs the *global* 0.5° field, not a regional clip). |
| `get_liaise_forcing_05.sh` / `get_liaise_forcing_05_cds.sh` | — | — | **D** | Thin shell wrappers around the Python script above with LIAISE paths baked in; reimplement as a config-driven CLI wrapper rather than porting. |
| `get_liaise_forcing_km.sh` | — | — | **C** | Downloads the ~3 km LIAISE-campaign-specific forcing products (ETHZ/IPSL). No global equivalent; out of scope here entirely. |
| `prepare_liaise_forcing_ecland.py` | 284 | 5 | **A→B** | Time-axis rebasing (`hours since <start-year>-01-01`) and the year-end endpoint-append/duplicate logic are grid-agnostic — they operate on whatever `(time, lat, lon)` file they're given. Reusable near-unchanged; only the default paths and the module docstring's "LIAISE" wording need to change. This is exactly the kind of file the handoff prompt asks to preserve provenance for. |
| `scratch_mirror.sh` | 129 | 5 | **B** | Push/pull-only-what-changed pattern between `$PERM` and `$SCRATCH` is generic; only the path list is LIAISE-specific. |

## init_clim/

| File | Lines | LIAISE hits | Class | Note |
|---|---:|---:|---|---|
| `init_clim.py` | 894 | **0** | **A, with a caveat found 2026-09-17** | Zero LIAISE-specific references. Already grid-shape-agnostic: `gen_file` (reduced-Gaussian/point representation) vs. `gen_file_LL` (regular lat/lon) are both implemented, `get_mask`/`cut_mask` take a `BBOX` parameter rather than a hardcoded one, `grib2nc`/`grib2nc_LL` take explicit `nlat`/`nlon`. **Correction**: "unmodified except for import paths" undersold it — its own `from osm_pyutils import grid_gaussian as gg` does not resolve against the *current* `/perm/pad/ecland` checkout at all (`grid_gaussian.py` no longer exists in that tree's `tools/create_forcing/scripts/osm_pyutils/`, confirmed by direct `ls`/`find`, not just an import error). Valid when `liaise-ecland` was built, stale against the actively-maintained ecland tree now. See `PLAN.md` Milestone 2's 2026-09-17 investigation note before assuming this ports as cleanly as this row once suggested. |
| `init_clim.sh` | 160 | 9 | **B** | Driver script; the LIAISE `TARGET_AREA`/grid constants need to move to `config/ecland.yaml`, the MARS/GRIB retrieval calls themselves are generic. |
| `clim.sh` | 50 | 1 | **B** | Thin wrapper, one LIAISE default to remove. |
| `get_init_clim.sh` | — | — | **C** | Installs the *LIAISE* pre-validated `surfclim`/`soilinit` from this repo's own Git-LFS `init_clim/data/` — meaningless outside this domain. A global equivalent would pull from wherever the global surfclim/soilinit ends up living (MARS `climate.v021` directly, most likely) — reimplement, don't port. |
| `add_bedrock_wtd_fields.py` | 283 | 7 | **D** | Prototype "depth trilogy" bedrock/water-table-depth field generator for the `ecland develop` branch. Useful *concept* (per-gridpoint `RDBEDROCK`/WTD) but tied to a non-mainline ecLand branch and a regional ancillary source; not a priority for the first global pilot. |

## namelist/

| File | Class | Note |
|---|---|---|
| `create_liaise_namelist.sh` | **B** | The env-var-driven namelist templating pattern (`NCSS`, `NDLEVEL`, `LE*` logical aliasing convention, etc.) generalises cleanly; the LIAISE grid dimensions and `CMODID` string do not. |
| `input`, `input_cmf*`, `input_depthtrilogy` | **C** (as files) / **D** (as templates) | The namelist *files themselves* encode the LIAISE grid's `NX`/`NY`/point count and cannot be reused verbatim — but their structure (which blocks are needed, what `LECMF1WAY`/`TCOUPFREQ` coupling requires, the `DTIN`-multiple-of-`DT` constraint, the `CMPIREGNC`-required-even-for-NPROC=1 gotcha) is exactly the kind of hard-won knowledge worth carrying into `namelist/templates/` as Jinja/placeholder templates plus documentation, not as literal copies. |

## run/

| File | Lines | LIAISE hits | Class | Note |
|---|---:|---:|---|---|
| `run_liaise_ecland.sh` | 488 | 10 | **B** | The annual-loop structure, the restart-chaining logic (including the January-1-cold-start bug this project found and fixed 2026-09-17 — see `CLAUDE.md` there), the `CMF_STATIC_FILES_EXTRA`/`START_YEAR`/`END_YEAR`/`INITIAL_RESTART` extension points, and the `OMP_NUM_THREADS` inherited-shell-profile gotcha are all real, hard-won, and domain-independent. Region name and forcing/static file layout need generalising. |
| `run_liaise_ecland.slurm` | — | — | **B** | Same content as above, SLURM-wrapped; same treatment. |
| `postprocess_liaise_ecland.sh` | 195 | 4 | **B** | Generalise output-path conventions. |
| `check_water_budget.py` | 153 | 1 | **A(eqn)/D(scope)** | Imported unmodified from the sibling `plumber2-ecland` repo already, so it's already domain-neutral code — but it is explicitly **per-site** (point-scale), not area-weighted-global. The *equation and sign convention* it encodes (`Rainf+Snowf+Evap+Qs+Qsb − DelIntercept−DelSoilMoist−DelSWE−DelAquifer`, `Qs`/`Qsb` **added**, not subtracted — subtracting manufactures a spurious 2× residual) is verified, real, and exactly what Phase 8 of the handoff asks to confirm before assuming. The area-weighted *global* aggregation needs new code (Category D), reusing this equation. |
| `check_energy_budget.py` | 231 | 1 | **A(eqn)/D(scope)** | Same treatment as the water budget script. |
| `extract_control_diagnostics.py` | — | — | **D** | LIAISE-specific point extraction; the *lesson* it embeds (`Rainf`/`Snowf`/`Qs`/`Qsb`/`Evap` in `o_wat.nc` are **rates**, not pre-accumulated depths, despite `LACCUMW`/`LRESET` in the namelist — multiply by the output interval before summing) is worth keeping in `docs/` regardless of whether the script itself is reused. |

## cama_flood/

| File | Lines | LIAISE hits | Class | Note |
|---|---:|---:|---|---|
| `build_global_cmf_fixdir.sh` | 179 | 5 | **A** | Already builds a **global** CaMa-Flood fix bundle at any resolution (`CMF_RES=glb_15min/glb_06min/glb_03min/glb_01min`) from the shared ECMWF `CMFDIR`; this is a global tool that happens to live in a regional repo. Validated this session at three resolutions (see `liaise-ecland/PLAN.md`, 2026-09-16/17). Port near-unchanged. |
| `derive_cmf_weights.sh` | 270 | 19 | **B** | `gen_inpmat.py`'s conservative-remapping machinery, the `-e`/`sel_region.py` basin-extension logic, and the `mpireg.nc`-flattened-to-one-region fix are all reusable — but the whole *purpose* of this script is clipping the global network down to the small LIAISE box (`CLATN`/`CLATS`/`CLONW`/`CLONE`, `EXTEND_CROSSING_BASINS`). For a **global** run the clip step is simply skipped; the remap-weight generation (`gen_inpmat.py`) that runs against the ecLand grid stays and is the genuinely reusable core. Two upstream `ecland`-side source patches this script depends on (`cnt41s.F90` NLALO→NPOI bound fix; `cython_ext.pyx` out-of-bounds-pixel `continue` instead of `raise`) are prerequisites regardless of domain size — see `liaise-ecland/CLAUDE.md`, "Two ecland-side source patches required". |
| `aggregate_runoff_to_daily.py` | 118 | 5 | **B** | Volume-conserving hourly→daily aggregation (checked to 1e-9 relative error in the source project). Grid-agnostic by construction; only defaults need generalising. Directly answers Phase 9's temporal-integration requirement. |
| `fixdir_to_merit_map_bin.py`, `inpmat_to_cmfgpu_npz.py`, `subset_parameters_for_liaise.py`, `prepare_liaise_runoff_for_cmfgpu.py` | — | — | **C/D** | CaMa-Flood-GPU bridge tooling, tied to the LIAISE domain subset and to a GPU-specific runoff format the handoff prompt doesn't ask for. The runoff **sign convention** these files got wrong once and then fixed — total runoff is `-(Qs+Qsb)`, not `Qs-Qsb`, because `Qsb` is signed as a soil-column-loss term in ecLand's own convention — is a real, easy-to-repeat mistake worth documenting in `docs/forcing_variables.md` regardless of which script carries it forward. |
| `estimate_dam_q100.py`, `build_dam_param_csv.py` | — | — | **C** | Ebro-reservoir-specific (GRanD dam list filtered to the Ebro basin). Not relevant to a global historical run. |
| `extract_liaise_grdc_observations.py` | — | — | **D** | LIAISE-domain gauge filter; the *pattern* (basin-topology-aware filtering beats a lat/lon box; GRDC via Caravan is public-domain and redistributable, CAMELS-\* sub-datasets are not) generalises directly to Phase 6's validation framework, worth reimplementing globally rather than porting. |
| `skill_benchmark_*.py`, `build_*_dashboard.py`, `liaise_river_geometry.py` | — | — | **C/D** | LIAISE-gauge-specific scoring and dashboards. The **KGE/NSE/PBIAS formulas themselves** (verified against the official CaMa-Flood package's own `p02_get_100yrDischarge.py` this session) are correct, standard, and worth reusing verbatim in `validation/discharge/`; the dashboard/gauge-matching machinery is not. |

## Cross-cutting lessons worth carrying over regardless of file reuse

These aren't files — they're findings from `liaise-ecland/CLAUDE.md` that would be
expensive to rediscover and are directly relevant to this repo's own invariants:

1. **The annual restart chain silently cold-starting every year** (found
   2026-09-17): a driver script that stages a restart file and sets
   `LNF=.FALSE.` does nothing if the underlying `NSTART` stays 0 — the offline
   driver only calls `RDRES` when `NSTART != 0`. Any run script this repo writes
   must be checked the same way (compare day-2 restart state to what was staged,
   don't just check the run exits 0).
2. **`OMP_NUM_THREADS` inherited from ECMWF's shell profile is `1`**, and
   `sbatch --export=ALL` propagates it, silently defeating any
   `${OMP_NUM_THREADS:-N}` default. Threading is also **not a universal win**:
   measured 1.6× *slower* at 1,405 active river cells, ~1.4-2× faster at 34,000+.
   Any run script needs an explicit, logged thread-count decision, not a
   fire-and-forget default.
3. **Runoff sign convention**: ecLand's `Qsb` in `o_wat.nc` is a signed
   soil-column-loss term, not a plain positive flux — total runoff to a router
   is `-(Qs+Qsb)`, verified against real Fortran discharge to within 0.2-3%.
   `Qs-Qsb` silently double-counts surface runoff and was the single largest
   source of discharge bias found in the sibling GPU-coupling work.
4. **`mpireg.nc` is for MPI domain decomposition, not OpenMP thread
   scheduling** — the two are unrelated parallelism mechanisms and conflating
   them wastes time (confirmed by direct question this session).

## Summary

- Category A (port unchanged, adjust only paths/imports): `init_clim/init_clim.py`,
  `forcing/prepare_liaise_forcing_ecland.py` (near-A), `cama_flood/build_global_cmf_fixdir.sh`.
- Category B (port + generalise config/domain): `forcing/get_liaise_forcing_05_cds.py`
  (variable tables), `forcing/scratch_mirror.sh`, `init_clim/init_clim.sh`, `init_clim/clim.sh`,
  `namelist/create_liaise_namelist.sh`, `run/run_liaise_ecland.{sh,slurm}`,
  `run/postprocess_liaise_ecland.sh`, `cama_flood/derive_cmf_weights.sh` (remap core only),
  `cama_flood/aggregate_runoff_to_daily.py`.
- Category C (do not copy): LIAISE km-scale forcing, dam/reservoir tooling, GRDC/CAMELS
  gauge dashboards, `get_init_clim.sh`, literal namelist files.
- Category D (concept only, reimplement): global area-weighted water/energy budget,
  global gauge-benchmark framework, CaMa-Flood-GPU bridge, bedrock/WTD ancillary fields.

This matrix drives Phase 2 onward; see `PLAN.md` Milestone 0 for the resulting task list.
