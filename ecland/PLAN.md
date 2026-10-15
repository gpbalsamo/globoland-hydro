# PLAN.md

Living state tracker. Status labels are load-bearing, not decorative: **DONE**
means executed successfully and its own validation passed; **NOT VERIFIED**
means code/config exists but has not been run against real data; **NOT
STARTED** means neither exists. Nothing is marked DONE because a script was
written — see `CLAUDE.md`.

## Role in benchmark cascade

This repo is Level 3 (global) of a site→region→global→routing→benchmark
cascade — see README.md's "Role in the ecLand benchmark cascade" for the full
diagram and sibling-repo list (`ecLand4U`, `plumber2-ecland`, `liaise-ecland`).
Milestone 8 below tracks the agent/orchestration interface that makes this
repo's stages callable by a future cross-repo orchestrator or a low-footprint
local coding agent, separate from the scientific milestones (0-7).

## Milestone 0 — repository migration

- [x] Identify reusable `liaise-ecland` code — `docs/migration_from_liaise.md`,
      every named file actually read and classified A/B/C/D.
- [x] Create global directory structure.
- [x] Port Category A files unchanged (`init_clim/init_clim.py`,
      `cama_flood/build_global_cmf_fixdir.sh` + its 3 vendored companion
      tools, `cama_flood/vendor/`) — **files copied, syntax-checked
      (`py_compile`/`bash -n`), NOT YET EXECUTED against real data in this
      repo**. `cama_flood/aggregate_runoff_to_daily.py` (Category B) also
      carried over as a reference implementation, explicitly flagged
      NOT YET GENERALIZED in its own header.
- [ ] Generalise Category B files (remove LIAISE grid/domain constants, move
      to `config/`) — **NOT STARTED** except the reference copy above.
- [x] Remove regional assumptions from the *design* (grid strategy, interface
      docs) — `docs/grid_strategy.md`, `docs/cama_interface.md`.

## Milestone 1 — WFDE5 forcing

- [ ] Define required ecLand variables — **DONE for the CDS-side table**
      (`docs/forcing_variables.md`, carried from a verified source), **NOT
      VERIFIED for the ecLand-side conventions** (accumulated-vs-instantaneous,
      timestamp interpretation, longitude/latitude convention) — these are
      stated as open questions in that document, not assumed answered.
- [x] `forcing/download_wfde5.py` — **PORTED/GENERALISED** from
      `liaise-ecland/forcing/get_liaise_forcing_05_cds.py` (LIAISE bbox crop
      removed, `--months`/`--dry-run` added), syntax-checked and covered by
      `tests/test_download_wfde5.py` (synthetic fixtures, 4 tests, all
      pass). **NOT YET RUN against a real CDS request** — no WFDE5 data has
      been downloaded in this repository. Deliberately does not assert any
      global grid convention itself; see the next line.
- [x] Obtain one month of global WFDE5 as a first real test — **DONE**
      2026-09-17: `forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_1988_01-01.nc`
      (1.2 GB, 744 hourly steps, 360x720 global 0.5 deg), downloaded with
      `python3 forcing/download_wfde5.py --start-year 1988 --end-year 1988
      --months 01`. Values are physically sane (Tair 210-322 K, Rainf/Snowf
      non-negative). One full year, then 1988-2024, is still **NOT
      STARTED** — do this incrementally, not in one multi-year batch (see
      the script's own memory-estimate warning).
- [ ] Validate coordinates/timestamps/units against real downloaded data —
      **PARTIALLY ANSWERED, ad hoc, not yet a real check**: longitude
      convention (`-180..180`) and latitude ordering (ascending) are now
      confirmed against the real file above and recorded in
      `docs/forcing_variables.md`. `forcing/validate_wfde5.py` itself still
      **does not exist** — units/timestamp-semantics/fill-value checks are
      not yet automated, and nothing here should be trusted as a real gate
      until that script exists and is run.
- [x] Create ecLand-ready files — **DONE** 2026-09-20: `forcing/preprocess_wfde5.py`
      converts WFDE5 to ecLand `met_2DHT` format and has produced the real
      files driving every run below. Rewritten to stream in 168-hour blocks
      after the whole-period load was measured at ~82 GB peak for one year
      (unrunnable); peak RSS is now 546 MB and the output was verified
      **bit-identical** to the pre-rewrite file on the one-day case.
- [x] Verify global coverage — **DONE** 2026-09-22 for the assembled year
      files, by inspection not by script: 8784 records for 1988 (leap) /
      8760 otherwise, grid 360x720, lat -89.75..89.75 **ascending**, lon
      -179.75..179.75, strictly hourly with no gaps, units K / kg kg-1 / Pa /
      W m-2 / kg m-2 s-1 / m s-1, and an identical 64.2% ocean mask across
      all eight variables. `forcing/validate_wfde5.py` **still does not
      exist**, so this is a manual check that is not reproducible or
      version-controlled — writing that script remains open.

## Milestone 2 — ecLand climatology + initialization

- [x] Construct `surfclim` on the exact model grid — **DONE** 2026-09-19:
      `init_clim/build_global_surfclim_soilinit.sh` runs ecland's own
      `tools/create_forcing/ecland_create_forcing.py` (2D pipeline, global
      bounding box) and produces `surfclim_GLOBAL_1988-2024.nc` (8.8 MB,
      360x720). Real MARS retrieval: 26 ERA5 fields, 27.2 MB, 4 seconds
      (`class=ea, type=an, date=19880101`); the static climatology
      (`climate.v015/639l_2`) is a direct file copy, no retrieval.
- [x] Construct `soilinit` on the exact model grid — **DONE** 2026-09-19,
      same run: `surfinit_GLOBAL_1988-2024.nc` (4.9 MB, 360x720).
- [x] Validate shape/coordinates/mask — **DONE, real check, real bug
      found and fixed**: `init_clim/validate_init_grid.py` compares
      forcing/surfclim/soilinit pairwise. First real run caught a genuine
      grid mismatch — the tool writes latitude in native MARS/GRIB order
      (descending, north-to-south); WFDE5 is ascending. Fixed by
      `init_clim/flip_latitude_to_ascending.py` (now wired into the build
      script automatically, not a manual step). After the fix:
      `validate_init_grid.py` reports **PASS** — 360x720 lat/lon identical
      across all three files (lat -89.75..89.75, lon -179.75..179.75).
      Land-mask agreement (WFDE5 coverage vs. surfclim's ERA5-derived
      `landsea`) is 98.0% — reported as informational, not a hard
      pass/fail, since the two masks are independently derived (see the
      script's own docstring).
- [x] No accidental flattening/reordering — **VERIFIED**: output is a
      proper `(lat, lon)` gridded NetCDF (not the flattened `x`-point
      representation `init_clim.py`'s `gen_file` would have produced),
      confirmed by `validate_init_grid.py` reading `lat`/`lon` directly.
      Covered by 5 synthetic-fixture tests, `tests/test_init_clim_grid.py`.

**Path taken**: ecland's own `ecland_create_forcing.py` (Option B from the
2026-09-17 investigation below), not a patched `init_clim.py`. Config
template: `init_clim/config_global.yaml.tmpl` (rendered by the build script
via `envsubst`) — global box `clatn=89.75/clats=-89.75/clonw=-179.75/
clone=179.75, dx=0.5` (cell-center corners, exactly matching WFDE5's real
grid, not the naive `90/-180/-90/180` grid-line corners).

**Investigation findings, 2026-09-17 (superseded by the above — kept for
the reasoning trail)**:

- `init_clim/init_clim.py`'s own import, `from osm_pyutils import
  grid_gaussian as gg`, **does not resolve against the current
  `/perm/pad/ecland` checkout** — `grid_gaussian.py` does not exist
  anywhere in that tree's `tools/create_forcing/scripts/osm_pyutils/`
  (checked directly: `ls` + `find`, not just an import error). This was
  valid against whatever ecland snapshot `liaise-ecland` was built against
  at the time; the currently-maintained ecland tree has moved past it.
  `docs/migration_from_liaise.md`'s Category A classification of
  `init_clim.py` ("port unchanged, adjust only import paths") is **no
  longer accurate as stated** — the import itself needs more than a path
  fix, or a different tool entirely.
- A plausible successor exists — `iniclim_forcing_LL.py`/`interp_ll.py` in
  the same `osm_pyutils` package — but **not verified as a drop-in
  replacement** for whatever `get_grib_grid()` provided.
- Separately, and better news: this machine already has a **full working
  ecLand build**, `/perm/pad/ecland/build/bin/ecland-master-dp` (+
  `ecland-master-cmflood-dp` for coupled runs) — a real unblock for
  Milestone 3 once surfclim/soilinit/namelist exist.
- ecland's own tree also has an **actively-maintained**, config-driven
  alternative: `tools/create_forcing/ecland_create_forcing.py`
  (MARS-or-CDS, ERA5-based climatology/init, `1D` site or `2D`
  bounding-box region). It has no explicit "global" mode, but its internal
  grid-sizing formula (`nlat=int((180-dx)/dx+1)`, `nlon=int((360-dx)/dx+1)`)
  is resolution-only, so a full-globe bounding box is plausible —
  **untested at that extent**.
- Confirmed `climate.v021` (the static climatology archive both tools
  ultimately read from, e.g. `/home/rdx/data/climate/climate.v021/399_4/`)
  is genuinely **global already** (`grib_ls`: -89.83..89.83 coverage) — the
  LIAISE crop in both `liaise-ecland`'s `init_clim.sh` and ecland's own 2D
  tool happens only at the interpolation step, not the source data. Even
  the LIAISE-flagged irrigation input turns out to be a global product at
  the same native resolution.
- Confirmed the exact MARS grid/area parameterization needed to land on
  WFDE5's grid convention if generalising `init_clim.sh` directly:
  `area=89.75/-179.75/-89.75/179.75` (cell-center corners, matching WFDE5's
  `±89.75`/`±179.75`), **not** `90/-180/-90/180` (grid-line corners) — the
  wrong choice here silently produces a half-cell-offset grid, exactly the
  kind of mismatch `docs/grid_strategy.md` warns about.
- **Decision paused, not made**: patch `init_clim.py`'s broken import
  (faithful to the original migration plan, but reverse-engineering a
  compatibility shim) vs. switch to `ecland_create_forcing.py`'s 2D
  pipeline with a global box (built on currently-maintained code, but
  untested at that scale) — pick this up in a future session before
  writing any new driver code.
- Independent of that choice: `namelist/templates/` is still empty and
  `run/run_ecland.sh` does not exist — "run ecLand" needs both regardless
  of how surfclim/soilinit get built.

## Milestone 3 — pilot ecLand run

- [x] One day, global — **DONE** 2026-09-19: `run/run_ecland.sh` ran
      `ecland-master-dp` (real executable at `/perm/pad/ecland/build/bin/`)
      for 1988-01-01 00:00 -> 1988-01-02 00:00 (48 half-hour steps), global
      0.5°, using the real downloaded WFDE5 forcing and the real
      `ecland_create_forcing.py`-built surfclim/soilinit. Completed in 106s.
      `run/check_run.py` reports **PASS**: `run.log` clean (no Fortran abort
      marker), `restartout.nc` present, zero NaN/Inf in any `o_*.nc`
      variable (excluding ecLand's own `1e20` fill value over masked/ocean
      cells). 87,798 land points; `AvgSurfT` 197.5-325.4 K, `SoilTemp`
      215.9-316.1 K on land -- physically plausible for a global January
      day, not independently validated against observations.
- [x] One month, global — **DONE** 2026-09-20: full month of January 1988,
      coupled ecLand<->CaMa-Flood over real MPI, hourly coupling
      (`TCOUPFREQ=1`). `run/check_run.py` **PASS** over ~60 GB of output.
- [x] One complete year, global — **DONE** 2026-09-23 (`Y1988_19880101-19890101`,
      job 30129241). Full leap year, 8784 hourly forcing records, 17,566
      steps, coupled, 16 ranks x 8 threads. Model integration 2505 s
      (**0.70 h/simulated year**; 0.93 h including preprocessing and ECFS
      archiving), 12 `NFORCWINDOW` refills, 7.4 GB on disk, archived to
      `ec:/pad/wfde5-ecland` and verified with `els`.
      `run/check_run.py` **PASS** — `run.log` clean, `restartout.nc`
      present, no NaN/Inf in any `o_*.nc`.
      A first attempt (job 30010675) completed all 17,566 steps then died
      with **SIGBUS on the final write** of a 424 GB hourly `o_gg.nc`. That
      is a large-file write fault, **not** disk or quota (files are sparse;
      171 GB actual against 4.2 T free). Hence the chunking rule now
      enforced in `run/run_ecland.sh`: annual chunks -> daily output,
      hourly output -> monthly chunks. The limit is bracketed between 36 GB
      (works) and 424 GB (fails) but **not characterised**.
- [ ] Verify energy budget — **NOT VERIFIED (2026-10-10). The test cannot be
      performed as written, and the earlier DONE label is retracted.**
      `DelSoilHeat` is **identically zero at every land point** in ecLand's
      `o_efl.nc` -- measured on v4's 1989: `min = max = 0` across all 88,373
      land points x 365 records, 0 nonzero of 32,256,145. The variable exists
      in the file; the model never writes it. So `check_budgets.py`'s energy
      sum omits the budget's main storage term and is an OPEN SUM, not a
      closure, and its residual cannot be read as a closure error either way.
      Measured on v4 with the committed script:

        1988  3244 EJ  0.938%     2012  3502 EJ  1.009%
        1989  3540 EJ  1.024%     2024  3202 EJ  0.928%
        2000  3583 EJ  1.038%

      Near-constant in ABSOLUTE terms (3,202-3,583 EJ) while net radiation
      varies -- the signature of one systematic missing term, and it straddles
      the arbitrary 1% default tolerance, so 3 of these 5 years "FAIL" for a
      reason unrelated to the run. `check_budgets.py` now detects the zero term
      and reports the energy result as INCONCLUSIVE instead of FAIL, and does
      not let it gate exit status; the water closure still does.
      **The earlier "33-year sweep, narrow 0.53-0.96% band" claim is
      withdrawn**: the committed script's real range on v4 includes 1.038%, the
      sweep covered 33 years of a different (pre-v2) archive, and the entry
      itself was already flagged NOT RE-CONFIRMED. **ROOT CAUSE, in ecLand's source.** The diagnostic is not
      implemented. The whole tree contains exactly ONE assignment to it,
      `src/surf/offline/driver/upddiag.F90:410`:

        D1SDSH(KIDIA:KFDIA,IBL) = 0._JPRB ! DelSoilHeat of skin layer (0)

      and `D1SDSH` points at level index 1 only
      (`sugdi1s.F90:479`, `GDIAUX1S(:,M1SDSH,1,:)`). The all-level array
      `D1SDSH2` -- which is what `wrtdcdf.F90:613` actually writes to netCDF --
      **is never assigned anywhere**, so the file carries the zero-initialised
      buffer. Meanwhile the variable is fully registered for output with a long
      name and units `J m-2` (`netcdf_utils.F90:369`), which is what makes it a
      silent zero rather than an absent field.

      The water-side twin IS computed, one routine away, which shows the
      intended form (`upddiag.F90:229`):

        D1SWDS(JL,IBL)=PTSPHY*RHOH2O*DOT_PRODUCT(PSURF%PWSAE1(JL,:),RDAW(:))

      i.e. the layer-depth-weighted integral of the soil tendency. `DelColdCont`
      (snow heat content) at least *reaches* the output, from
      `PDDHS%PDHTSS(:,1,15)` -- but it is wrong too, for different reasons; see
      the third ecLand bug below. Closing the soil gap means the
      heat analogue of line 229 -- soil temperature tendency dotted with each
      layer's volumetric heat capacity and depth -- which is an **ecLand source
      change**, done below.

- [x] **Wire up DelSoilHeat in ecLand -- DONE and VERIFIED 2026-10-11.**
      One line in `src/surf/offline/driver/upddiag.F90` on ecland `develop`:

        -D1SDSH(KIDIA:KFDIA,IBL) = 0._JPRB ! DelSoilHeat of skin layer (0)
        +D1SDSH(KIDIA:KFDIA,IBL) = SUM(PDDHS%PDHTTS(KIDIA:KFDIA,1:KLEVS,15),DIM=2)

      The quantity was already computed per layer (`srft_mod.F90:411`) and slot
      15 was reserved for it (`sucdh1s.F90:89` names its last flux "soil heat
      content change"). Verified four ways, built into
      `/perm/pad/ecland/build-dsh` so `build/` stayed untouched under the
      pending REPREX/AMAZEX segments:

      1. **Diagnostic only.** `restartout.nc` and `o_gg.nc` md5-identical
         between old and new binaries on the same 1-day run; of every variable
         in `o_efl.nc`, `DelSoilHeat` alone changed (0 -> populated).
      2. **Correct to machine precision.** Regressed on the soil temperature
         change from `o_gg.nc`: correlation **1.000000**, slope*3600 =
         **2.19349E6**, matching `RRCSOIL` (`sussoil_mod.F90:487`) exactly.
      3. **The soil energy budget now closes.** `Qg + (DelSoilHeat - Qf) = 0`
         to **2.9E-10** relative (35.428263 vs -35.428263 EJ), where
         `DelSoilHeat - Qf` is the full `PCTSA*RDAT*dT` storage change. With the
         term at zero the same identity is out by **37.9%** -- that is how the
         missing term was found.
      4. **No ctest reference affected.** The only reference values are
         `AvgSurfT`/`SoilMois`/`SoilTemp` -- all state, all unchanged.

      Caveat recorded in the source: slot 15 differences `ZTSA` (the tridiagonal
      solution) against `PTSAM1M`, which is the real temperature change only
      because `RSIMP = 1` (`sussoil_mod.F90:493`). A different `RSIMP` would
      silently break it, and `PTSDFL` (`srft_mod.F90:338`) with it.

- [x] **Second ecLand bug, found and fixed: the unit labels were wrong.**
      `DelSoilHeat` and `DelColdCont` declared `J m-2`, but both are written
      through the same path as `Qf`/`Qg` -- accumulator bucket `IA` times
      `ZWA = 1/(NFRPOS*TSTEP)` (`wrtdcdf.F90:613,628`) -- so they are MEAN RATES
      in `W m-2`. Corrected in `netcdf_utils.F90`. Consequence: every budget
      this repo computed before today **under-scaled both storage terms by the
      output interval**, because `check_budgets.py` keys off units. It now
      overrides the stale label on archived files and says so.

- [x] **Third ecLand bug, found and fixed: the snow energy diagnostics --
      DONE and VERIFIED 2026-10-11.** `DelColdCont` was wrong by a factor
      `PTMST` *and* was the top snow layer of five, and `Qfsn` had the opposite
      sign under `LESNML` from the single-layer schemes. The earlier note here
      blamed `srfsn_mod.F90:380`, where the melt term is commented out of index
      15 -- that is real but **not the live path**: this configuration sets
      `LESNML=.TRUE.`, `NCSNEC=5`, so `surftstp_ctl_mod.F90:647` dispatches to
      `SRFSN_DRIVER` -> `SRFSN_WEBAL`. The live defects were

      ```fortran
      ! srfsn_webal_mod.F90:417, ZSNHC is already a capacity DIVIDED by PTMST
      ! (ZTMST=1/PTMST), so this returned C*dT in J m-2, not a flux
      -  PDHTSS(JL,JK,15)=ZSNHC(JL,JK)*PTMST*(PTSN(JL,JK)-PTSNM1M(JL,JK))
      +  PDHTSS(JL,JK,15)=ZSNHC(JL,JK)*(PTSN(JL,JK)-PTSNM1M(JL,JK))
      ! srfsn_webal_mod.F90:415, sign now matches -RLMLT*PMSN elsewhere
      +  PDHTSS(JL,JK,14)=-(PMELTSN(JL,JK)+PFREZSN(JL,JK))
      ! upddiag.F90:276,453 -- the column, not layer 1
      +  D1STNM  = SUM(PDDHS%PDHTSS(KIDIA:KFDIA,1:KLEVSN,14),DIM=2)
      +  D1STNDH = SUM(PDDHS%PDHTSS(KIDIA:KFDIA,1:KLEVSN,15),DIM=2)
      ```

      plus `PDHSSS(JL,JK,5)` rewritten from `PMELTSN`/`PFREZSN` directly so
      the sign fix cannot move `Qsm`, `srfsn_driver_mod.F90`'s own check made a
      column budget, and `PDHTSS(JL,2:,14:15)=0` in the single-layer schemes,
      which never fill those layers although `KLEVSN=NCSNEC` regardless of
      `LESNML`. Verified four ways:

      1. **Diagnostic only.** `restartout.nc`, `o_gg.nc` and `o_wat.nc` are all
         three md5-identical to the pre-fix run, and of every variable in
         `o_efl.nc` only `DelColdCont` and `Qfsn` changed. `DelColdCont`'s peak
         went from **2.24E5** to **220.5 W m-2** -- the old value was not a flux.
      2. **ecLand's own per-grid-point check, which is the authoritative one.**
         `LESNCHECK=.TRUE.` (`NAMPHYOFF`) makes `srfsn_driver_mod.F90` test the
         snow column's energy balance at every snow point and timestep against
         1E-6 W m-2: **242,225 failing point-timesteps in 4 timesteps before
         the fix, 0 in 6 timesteps after.** Template
         `namelist/templates/namelist_ecland_50R1_ctl_sncheck`.
      3. **Exact against the state fields.** Regressed on
         `sum_k cice*min(SWE_k, rsn_k*RDSNMAX)*dT_k`, built from `SWEML`,
         `SnowTML` and `snowdensML` in `o_gg.nc`: slope **0.99295**, corr
         **0.990054**. The cap matters -- `RDSNMAX = 1 m` leaves only **9.06%**
         of global SWE thermally active, so an uncapped prediction is ~6x too
         big (slope 0.169, corr 0.451) and is what made the first version of
         this test disagree. Not 1.000000 like the soil, because the snow
         layers are regridded every step, so layer *k* at *t+1h* is not the
         same mass as at *t*.
      4. **ecLand's own test suite passes.** `ctest -R "ecland_test|ecland_ifsbench"`
         in `build-dsh`: **9 of 9 runnable tests Passed**, 311 s
         (`insitu_US-Ha1_1991-1996`, `2D_EU-001`, five `ifsbench_v1_EU`
         variants, and both `2d_gl_t21` global tests with and without CaMa;
         `ifsbench_v1_EU_forward_dp` is disabled upstream). Expected, since
         the references under `tests/` are `AvgSurfT`, `SoilMois` and
         `SoilTemp` -- all state -- and all three output files are
         bit-identical.

- [ ] **The all-surface energy residual is NOT a closure -- NOT VERIFIED, and
      cannot be one from `o_efl.nc` as it stands.**
      The ~1% figure never was one, and the old 0.53-0.96% "band" was three
      defects partly cancelling. Measured, not argued: *(a)* it
      **double-counted the soil column** -- `Qg` already equals
      `-(DelSoilHeat - Qf)` to 3E-10, so adding `Qg` *and* `+Qf - DelSoilHeat`
      counts that storage twice; *(b)* it omitted `Qfsn`; *(c)* `DelColdCont`
      was wrong, now fixed (entry above). `check_budgets.py` now writes the
      equation as `SWnet+LWnet+Qle+Qh - (DelSoilHeat-Qf) - (DelColdCont-Qfsn)`:
      on the 1994-01-01 day the old form gives **3.556%** of net radiation and
      this one **1.262%**. It is still not gated, and the reason is now a
      *named* one rather than a defect: **FLake, sea ice, interception and the
      skin layer have no storage diagnostic in `o_efl.nc`**, so there is
      nothing to put on the right-hand side for them. Closing it needs a FLake
      heat-content diagnostic, which does not exist.

- [x] **The snow column IS now checked from output, via `LWRTIL=.TRUE.` --
      DONE and VERIFIED BOTH WAYS 2026-10-11.** An earlier version of this
      entry said it could not be done at all; that was wrong. `o_efl.nc` indeed lacks the snow tiles'
      atmospheric flux -- of DDH slots 7-12 (snow SW down/up, LW down/up,
      sensible, latent) `upddiag.F90` reads only 7-10, into
      `D1STNSRD/SRU/TRD/TRU`, `wrtdcdf.F90` writes none of the four, and slots
      11-12 have no `D1S` variable at all. But `LWRTIL=.TRUE.` writes
      `o_til.nc` with per-tile, already-fraction-weighted `SWnet`, `LWnet`,
      `Qh`, `Qle` and `tifr`, and summing tiles 5 and 7 gives the snow tiles'
      flux. Measured on a 3 h run (template
      `namelist_ecland_50R1_ctl_sntile`), against
      `Qgsn + (DelColdCont - Qfsn)`: slope **0.979**, corr **0.998**, mean
      |residual| **1.49 W m-2** on 171,585 snow samples where the flux itself
      averages 13.7 W m-2.
      It is not exact, and the reason is worth knowing before anyone trusts
      `o_til.nc` for any budget: **ecLand's per-tile radiation diagnostics are
      approximations, while its per-tile turbulent fluxes are exact.** Summed
      over all ten tiles, `o_til.nc`'s `Qh` and `Qle` reproduce `o_efl.nc`'s
      grid-box values to **1e-7 W m-2**, but `SWnet` is out by **1.29** and
      `LWnet` by **2.44 W m-2** on average (max 40 and 31). `PDHTLS(:,JTILE,6)`
      is built as `PFRTI*PSLRFL/PEMIS`, the grid-box net LW redistributed by
      fraction, not the per-tile `PSLRFLTI` the snow solver actually uses
      (`surfexcdriver_ctl_mod.F90:1171`). Consistent with that, the
      reconstruction residual is **0.80 W m-2 at night and 1.96 by day**, and
      correlates with the radiation terms (-0.61 with `SWnet_sn`, +0.62 with
      `LWnet_sn`) and not with the forest-snow latent split (+0.04 with tile
      7's `Qle`). The exact test remains ecLand's own `LESNCHECK`; one new
      output field carrying `ZHFLUX` (`srfsn_driver_mod.F90:298`) would make
      the offline check exact, and is the cheapest upstream fix.
      It is wired into `check_budgets.py` as a **gated** check whenever
      `o_til.nc` is present (`--no-snow-check` to report without gating,
      `--snow-corr` / `--snow-slope-tol` to retune). It is judged by regression
      and not by the global integral, because the two sides are a few EJ each
      with heavy cancellation -- the integral's relative error is ~37% even
      when the fields agree pointwise at corr 0.998.
      **Verified both ways, which is the part that matters.** The tolerances
      (corr >= 0.95, |slope-1| <= 0.10) are calibrated by perturbing one term
      at a time on real output, not guessed:

      | perturbation | slope | corr | verdict |
      |---|---|---|---|
      | none (correct run) | 0.97898 | 0.99841 | PASS |
      | `DelColdCont` x 1.10 | 0.92188 | 0.99779 | PASS |
      | `DelColdCont` x 1.20 | 0.86871 | 0.99587 | **FAIL** |
      | `DelColdCont` x 1.50 | 0.73275 | 0.98600 | **FAIL** |
      | `DelColdCont` x 0.50 | 1.28093 | 0.95345 | **FAIL** |
      | `Qfsn` sign flipped | 0.68038 | 0.67774 | **FAIL** |
      | `Qgsn` sign flipped | 0.68112 | 0.61709 | **FAIL** |
      | `DelColdCont` sign flipped | -0.26891 | -0.24098 | **FAIL** |
      | `DelColdCont` dropped | 1.13792 | 0.67562 | **FAIL** |
      | `Qfsn` dropped | 0.99092 | 0.91596 | **FAIL** |

      So it catches every sign error, any term silently dropped, and a scale
      error from about **15%** up; a smaller scale error passes, which is the
      honest limit of a check with a 1.5 W m-2 floor, and is why the coarse
      1e4 W m-2 magnitude test stays as the first line of defence. The FAIL
      path was exercised end to end on a copy of the real output with
      `DelColdCont` multiplied by 1.5 (`slope 0.732746`, exit 1), and the
      pre-fix run reports INCONCLUSIVE via the magnitude test before the gate
      is reached (its statistic is `slope 0.000763`, `corr 0.680`).
      Noted in passing, not acted on: `netcdf_utils.F90:105` labels tile 5
      "shaded snow" and tile 7 "exposed snow", while `srfsn_driver_mod.F90:298`
      pairs `PEVAPSNW` ("evaporation from snow under forest") with tile 7 --
      the two disagree about which snow tile is which. The check sums both
      tiles, so it does not depend on the answer.
      Original entry: `validation/check_budgets.py`,
      area-weighted global land totals. On the validated 1988 year:
      residual **+2347 EJ = 0.680% of net radiation**, **PASS**.
      Terms: SWnet 660354, LWnet -315357, Qle -201593, Qh -140360 EJ.
      Fluxes are downward-positive (`SurfSgn_convention = "Mathematical"`),
      so the turbulent terms are ADDED, not subtracted — subtracting them
      doubles the imbalance, the energy-side twin of the Qs/Qsb trap.
- [ ] Verify water budget — **NOT VERIFIED** (was marked DONE 2026-09-24; that
      label was **wrong and is retracted 2026-09-28**). The global closure
      figure passes only because two large errors of OPPOSITE SIGN cancel.
      Measured on 1994: residual over all land -1210.6 Gt (1.069%), but over
      non-glaciated land alone **-2883.8 Gt = 2.605% of precipitation**, with
      **+2072 Gt** of the opposite sign over ice-sheet points. Excluding the
      ice sheets makes closure ~4x WORSE, which is how the cancellation was
      found. 2.6% is ~2.6x the 1.0% tolerance, over exactly the land where the
      hydrology, runoff and discharge happen.
      Two distinct mechanisms, one understood and one being quantified:
      1. **Ice sheets (+2072 Gt)**: `SWEML` is hard-capped at exactly
         10000.000 kg m-2 (10 m w.e.) and 18584 points -- **21% of land** --
         sit at that cap. They receive 2301 Gt of snowfall in 1994 (25% of the
         global land total) and shed only ~753 Gt via evaporation and runoff;
         the rest cannot accumulate and is discarded. Real model behaviour, not
         a bug, but it means a global water budget INCLUDING ice sheets cannot
         close and should never have been used as the acceptance test.
      2. **Lakes (-2670 Gt, CONFIRMED 2026-09-28)**: 92.6% of the
         non-glaciated imbalance sits on lake-bearing cells; the worst are Lake
         Turkana, Lake Victoria and Lake Maracaibo, all with `SWEML=0`. The
         term is lake evaporation: -2670 Gt/yr over 3.37e6 km2 of `CLAKE` is
         **793 mm/yr**, squarely physical for open water. FLake carries lake
         temperature with a FIXED DEPTH and no water mass budget, so that water
         leaves the column having come from nowhere.
         ecLand's own check does not conserve it either -- it **cancels** the
         term, adding `ZLAKEE = PFRTI(:,9)*PEVAPTI(:,9)+PFRTI(:,1)*PEVAPTI(:,1)`
         to BOTH storage and flux so lake points cannot fail
         (`surftstp_ctl_mod.F90:1234-1245`; the commented-out line above shows
         the earlier version simply skipped lake points).
         **There is a closure path in CaMa-Flood and it does not work.** ecLand
         already sends lake-tile evaporation on channel 3 of the coupling
         buffer (`cnt41s.F90:220`), unconditionally; CaMa discards it unless
         `LWEVAP=.TRUE.`. Measured A/B on 1994 (job 32308283, the archived
         Y1994 being the LWEVAP=false arm):

             lake evaporation demanded   2670.0 Gt
             LWEVAP actually extracted      2.8 Gt   ->  0.1% recovered
             discharge change                        -0.023%

         The demand arrives (24603 cells extract, so the coupling is fine), but
         `DWEVAPEX = MIN(P2FLDSTO, D2FLDFRC*DT*D2WEVAP)` confines extraction to
         FLOODPLAIN storage scaled by flood fraction. 13876 of the 14065 cells
         that HAVE floodplain storage do extract -- the mechanism works where
         floodplains exist. Permanent lakes are not floodplains, so ~0 is
         recoverable there. The unmet demand is dropped silently; `D2WEVAPEX`
         records what was extracted, never what was asked.
         The two switches meant to address exactly this, **`LWEVAPFIX` and
         `LWEXTRACTRIV`, are DEAD CODE** -- declared, defaulted, logged,
         MPI-broadcast, consistency-checked, and never read by any
         computational routine, while shipping in three namelist files
         (`namelists/namelist_cmf_48R1`, `tutorials/`, `tests/ifsbench/`) that
         advertise them as working. Their consistency checks only `WRITE`, with
         no `STOP`. **So there is no namelist route to closing this**; it needs
         `LWEXTRACTRIV` implemented upstream.
         **The archive is NOT materially affected**: enabling `LWEVAP` moves
         discharge by -0.023%, so all 37 years remain usable and the dams
         control stands.
      The residual is negative in **every one of the 33 years swept so far**
      (-522 to -1211 Gt). A closure error with a constant sign is a missing
      term, not noise -- that was the clue that broke this open.
      Do NOT "fix" this by widening `--water-tol`. The tolerance is not the
      problem; the budget equation is incomplete, and 1994/1995 merely sit
      closest to the line.
- [x] ~~Verify water budget~~ — superseded; original 2026-09-24 entry follows
      for the record. On 1988:
      residual **-525 Gt = 0.452% of precipitation**, **PASS**.
      Terms: precipitation 116090 Gt, evaporation -80302 Gt, runoff
      (Qs+Qsb) -42410 Gt, DelSoilMoist -3429 Gt — all independently
      credible against global land hydrology, which matters as much as the
      residual closing. `Del*` terms are `kg m-2`/`J m-2` (already
      integrated), NOT rates; the script scales by the units attribute, not
      the variable name.
      `run/check_run.py` remains a NaN/crash check only; these are separate.
- [x] Multi-year campaign, 1988-2024 — **COMPLETE** 2026-09-28. All **37
      years** run, chained and archived to `ec:/pad/wfde5-ecland`; every year
      verified present with its full file set (`o_gg`, `o_wat`, `o_efl`,
      `restartout`, `restartout_cmf`, `input.namelist`, `run.log`, `cmf/`).
      The 2002-2024 resubmission (jobs 31744027..31744076) ran **23 of 23
      segments COMPLETED, zero failures and zero requeues**, 52:53-1:00:44
      each (~56 min/year including forcing preprocessing and ECFS archiving).
      Restart continuity verified per segment, not assumed.
      Endpoints confirmed at both ends of the archive: 2024 (leap) has 366
      daily records ending `2025-01-01 00:00`, which also exercises the 2025
      boundary stub. Lake temperatures stay physical 23 restarts downstream of
      the FLake fix -- `TLWML` max 306.3 K (2013), 308.3 K (2017), 306.9 K
      (2024), against 313.5 K with the nudge active.
      Budget closure: **the earlier "all PASS, water 0.452-0.611%" claim was
      from an 8-year sample and is retracted.** The full sweep (33 of 37 years
      done) gives water 0.449-1.069% with **1994 and 1995 FAILING** the 1.0%
      gate, and the global figure is itself unsafe -- see the retracted water
      budget entry above for why it closes only by cancellation. Energy sits in
      a 0.53-0.96% band. The residuals oscillate rather than climb, so there is
      still **no accumulating drift through the restart chain**; that
      conclusion survives, unlike the closure claim.
      A full 37-year `check_run.py` + `check_budgets.py` sweep is **IN
      PROGRESS**; until it finishes, per-year validation is verified on the 8
      sampled years above and NOT on the remaining 29.
      **A real bug in ecLand's FLake stopped this chain dead at 2001** and is
      worth recording in full, because the crash surfaced three layers away
      from its cause. Symptom: `forrtl: error (75): floating point exception`
      in `cotworestress_mod.F90:430`, reproducibly at step 8913, on different
      nodes (which should have ruled out infrastructure immediately — it did
      not, and a `--requeue` was added as a remedy for what was never a
      transient). Cause, from a core dump rather than from reasoning:
      `flakeene_mod.F90:467-470` nudges mean lake temperature toward soil
      temperature at level 1 with no validity condition, full strength at the
      0.5 m minimum depth, and a clamp that bounds only from below. At
      lake-dominated points the soil column is degenerate (`sotype=0`,
      `SoilMoist=0`) and runs hotter than any lake, so the lake follows it
      without bound: `T_MNW` reached **1.9e7 K**, dragging tile-1 skin
      temperature to **11,451 K**, and `EXP(RSHP2AMMAX*(ZTSK-T2))` overflowed
      in the carbon code. All forcing inputs at that point were normal.
      Fixed by `TMNW_NDG_TIMESCL = 1.0E30` in both namelist templates (job
      31717620: full year, 59:35, endpoint `2002-01-01T00`). Lake state after:
      `TLWML` max **307.20 K**, mean 279.348 K — against 313.53 K / 279.352 K
      for Y2000 with the nudge active. Unchanged mean, truncated warm tail.
      In Y2000 the mixed layer, mean water and bottom temperatures all peaked
      at the *same* 313.5258 K, which is a column slaved to the soil rather
      than a lake in equilibrium — **so the nudge biased the warm tail in
      every year of the archive**, and 2001 is only where it went
      superexponential. Corroborates finding 4 of the user's `ifs-lakebench`
      (368 K at Lake Chilwa), which anticipated this exact switch.
      Nine wrong hypotheses preceded the core dump; the lesson is that when a
      trap moves as you perturb rounding, stop guarding arithmetic and go read
      the state.
      2001 is fully validated: `run/check_run.py` **PASS** (no NaN/Inf in
      30 GB), water residual **-577 Gt = 0.504% of precipitation**, energy
      residual **+3242 EJ = 0.940% of net radiation**, both **PASS**; restart
      continuity from Y2000 `3.19e-06` against a cold-start distance of
      `169.2`; output ends at `2002-01-01T00` as required. Energy closure is
      looser than 1988's 0.680% but inside tolerance; not investigated.
      **Caveat on attributing the lake numbers**: the 307.2 K / 313.5 K
      comparison above is Y2001 against Y2000, which confounds the switch with
      interannual variability. The clean test is
      `run/configs/ab_flake_{on,off}.env` -- the same 90 days from the same
      restart, configs differing only in `NAMELIST_TEMPLATE` -- which is what
      any claim about the nudge's magnitude should rest on.
      **A/B result** (jobs 31737035/31737036, 2001-01-01 -> 2001-04-01,
      each verified to have used its intended `TMNW_NDG_TIMESCL`):

        lake temperature  TLWML max   304.52 K (off)  318.97 K (on)   +14.4 K
                          worst point                                 +24.7 K
                          lake pts shifted >1 K                         2.05%
                          lake pts shifted >5 K                         0.25%
                          global lake mean                            +0.035 K
        water cycle       Evap                                        -0.345%
                          Qs                                          -0.005%
                          Qsb                                         +0.004%
                          Rainf, Snowf                                 0.000%

      So the nudge is a severe *lake temperature* error -- +24.7 K in 90 days,
      diverging without bound over a year -- but its effect on the water cycle
      is 0.005% in runoff, **two orders of magnitude below the 0.45-0.50%
      budget-closure residual**, and it touches 0.044% of points at even
      0.001 kg m-2 in 90-day evaporation. Identical `Rainf`/`Snowf` confirms
      the two runs were otherwise the same run.
      **Therefore 1988-2000 do NOT need rerunning for the water cycle, runoff,
      discharge or the dam experiment**, which is what this archive exists for.
      They WOULD need rerunning for any lake-temperature or surface-energy
      analysis, where the 2000/2001 join is a real inhomogeneity. An earlier
      recommendation in this file to rerun all 37 years was based on the
      confounded year-to-year comparison and is withdrawn.
      Caveat on scope: the A/B window is January-March, while the runaway
      occurred in July, so the warm-season lake-temperature effect is likely
      LARGER than +14.4 K. The water-cycle sensitivity would have to change by
      ~100x to alter the conclusion above.
- [ ] Quantify global runoff totals — **NOT STARTED**.

**A real bug was found and fixed getting here (2026-09-19)**: WFDE5 is a
**land-only** product (masks ocean intentionally, unlike ERA5, which has no
gaps) — `forcing/preprocess_wfde5.py`'s first version filled masked
(ocean) cells with `0.0`, and ecLand's Fortran `surfexcdriver_ctl` is not
tolerant of `Tair=0 K`/`PSurf=0 Pa` at masked points: it crashed with a
floating-point invalid-operation signal on the very first timestep. Fixed
by filling masked cells with numerically-safe reference-atmosphere
constants instead (`MASKED_FILL_VALUES` in that script) — ocean-cell
*outputs* are meaningless regardless (surfclim's own land-sea mask is what
determines scientific validity), confirmed by ecLand's own output correctly
using its `1e20` fill marker over those cells rather than propagating the
placeholder values. Covered by `tests/test_preprocess_wfde5.py`.

**Path taken for the run driver**: not a hand-rolled namelist/run script.
`namelist/templates/namelist_ecland_50R1_ctl` is ecland's own official,
currently-shipped `{}`-placeholder template (ported unchanged from
`/perm/pad/ecland/namelists/`, the same one its own
`tests/2D_EU-001_20220101-20220102` test case uses), and `run/run_ecland.sh`
calls ecland's own official `share/ecland/scripts/ecland_create_namelist.py`
+ `ecland_run_model.sh` rather than reimplementing namelist patching. Direct
execution, no `sbatch`/`srun` (matches `benchmark.yaml`'s `smoke` profile,
`require_confirmation: false`).

**Environment gotcha worth remembering**: `ecland-master-dp` is MPI-linked
(`hpcx-openmpi/2.9.0`) and needs `module load prgenv/intel intel/2021.4
hpcx-openmpi/2.9.0` before it will run (`libmpi_usempif08.so.40` missing
otherwise). Loading `nco` in the same `module load` invocation as the MPI
stack silently breaks `LD_LIBRARY_PATH` again (observed directly, order
didn't matter) — load them separately. Also: piping a `module load`
command's output through anything (e.g. `| tail`) forks a subshell and the
environment changes never reach the calling shell — redirect
(`>file 2>&1`), never pipe, when you need the loaded modules to stick.

## Milestone 4 — runoff-to-CaMa interface

**Important scope correction (2026-09-20)**: this milestone was written
assuming an *offline/decoupled* hand-off (ecLand writes runoff → a separate
tool remaps it → CaMa-Flood reads it), matching `liaise-ecland`'s
CaMa-Flood-GPU bridge work. The path this repo actually took is the
**online, in-memory 1-way coupling** built into ecLand itself:
`cnt41s.F90` calls `CMF_FORCING_PUT` + `CMF_DRV_ADVANCE` directly every
`TCOUPFREQ`, with no runoff file ever written or read, and the
Qs/Qsb sign handling done inside ecLand's own Fortran. The items below are
therefore only needed if this repo later wants a decoupled chain as well.

- [x] Define Qs + Qsb convention — **DONE as a design decision**,
      `total_runoff = -(Qs + Qsb)`, verified in the reference project against
      real Fortran discharge (0.2-3% agreement) — see
      `docs/forcing_variables.md`. Not re-verified in this repo's own code,
      and **not needed for the online coupled path actually used**.
- [x] Derive conservative mapping weights — **DONE** 2026-09-20,
      `cama_flood/derive_global_cmf_weights.sh` (new; generalises
      `derive_cmf_weights.sh` by dropping its clip and mpireg-flattening
      steps entirely). Real run at `glb_15min`: `inpmat.nc` mapping this
      repo's own 360x720 ecLand grid onto the global river network,
      **0.00% area-conservation error** after correction. That figure is the
      weight-generation step's own area check. The complementary question --
      how much of *ecLand's* land area the network accepts -- is a different
      quantity, answered by `validate_remapping.py`: **90.8%**, the shortfall
      being Antarctica (no catchments south of ~56S) plus coastal
      partial-land cells.
- [x] Offline conservation check — **DONE** 2026-10-15,
      `cama_flood/validate_remapping.py` (new). Compares what ecLand
      produces against what CaMa receives through `inpmat.nc`, prints the
      numbers and the per-cause decomposition, and exits nonzero above
      `--tolerance`. Measured on Y2001: **1,229.1 km3 = 3.3732%** under the
      land-area convention (PASS at the 5% default) and **3,373.7 km3 =
      8.7443%** under the grid-box convention (FAIL, deliberately). The
      second reproduces the 8.86% computed by hand from `inpmat.nc` in
      Milestone 5, from a different direction.
      `aggregate_runoff_to_daily.py` remains **NOT STARTED, and not on the
      critical path** for the online coupled configuration (see scope
      correction above).

## Milestone 5 — CaMa-Flood

- [x] Global routing — **DONE** 2026-09-20: a full calendar month
      (1988-01-01 → 1988-01-31, 1486 half-hour steps) of global 0.5°
      ecLand coupled to CaMa-Flood at `glb_15min`, **hourly coupling**
      (`TCOUPFREQ=1`, matching operational configuration), real 2-rank MPI
      with a genuine 2-region `mpireg.nc` (126,192/126,191 cell split, not
      flattened). Ran via `run/run_ecland_cmf.slurm` (SLURM batch,
      `--mem=32G`, submitted only after explicit approval per `AGENTS.md`).
      743 `CMF_FORCING_PUT`/`CMF_DRV_ADVANCE` cycles — exactly hourly over
      744 h.
- [x] Output Q, river storage, flood storage, flood depth — **DONE**, same
      run: `o_totout.nc`, `o_rivsto.nc`, `o_fldsto.nc`, `o_rivdph.nc`
      (124 MB each) plus ecLand's own `o_gg.nc`/`o_wat.nc`/`o_efl.nc`.
- [ ] Pilot basin first if useful — skipped; went straight to global, which
      worked.

**Performance, measured (not estimated)**: 2901 s wall for 31 simulated
days on 2 ranks = **938.8 forecast days per day** (the model's own metric),
1.92 s per 30-min step, ~93.6 s per simulated day. CaMa coupling accounted
for ~890 s (~31%) of the 2849 s time-step loop, at ~1.1-1.7 s per hourly
coupling call. **Parallel efficiency is poor and needs attention before
scaling**: the uncoupled 1-rank one-day run (Milestone 3) reported 875.5
forecast days per day, so doubling ranks *and* adding CaMa netted only ~7%
more throughput. Extrapolated, 1988-2024 would be ~14.4 wall-clock days
continuous at this configuration.

**Output volume is the bigger practical blocker than runtime**: one
simulated month produced ~60 GB (`o_gg.nc` alone 38.5 GB), i.e. ~27 TB for
37 years. `NFRPOS`/`LWRGG` and the output-variable selection need
revisiting before any multi-year run, ahead of the forcing-memory question
in "Open blockers".

**Four real bugs were found and fixed getting here** — see
`cama_flood/README.md` for the full account: a `gen_inpmat.py` netCDF
chunking/HDF5 crash needing `liaise-ecland`'s `cdo` re-write step;
`ecland-master-cmflood-dp` being a *standalone* CaMa-only driver rather
than the coupled executable (the coupled one is plain `ecland-master-dp`);
`TCOUPFREQ` being read in **hours**, not seconds; and CaMa's `COUTDIR`
defaulting relative to an ephemeral run directory. A fifth, cosmetic, was
found by this run's own tail: `ecland_run_model.sh` hardcodes
`mv restart<YYYYMMDDHH>.nc`, so `LRESTCDF=.FALSE.` (binary restarts, the
T21 reference's default) made that last step fail after an otherwise fully
successful run — `namelist/templates/namelist_cmf_global.tmpl` now sets
`LRESTCDF=.TRUE.` (netCDF restarts), which both matches operations and
fixes the mismatch.

## Milestone 6 — validation

- [ ] GRDC / existing river benchmark framework — **NOT STARTED** (the
      *formulas* — KGE/NSE/PBIAS — are verified in `liaise-ecland` against the
      official CaMa-Flood package's own reference script and are safe to
      reuse verbatim once there is discharge to score).
- [ ] Selected large basins — **NOT STARTED**.
- [ ] Global water balance — **NOT STARTED**.
- [ ] Seasonal hydrographs — **NOT STARTED**.
- [ ] KGE / NSE / correlation / bias / RMSE — **NOT STARTED**. Note from the
      reference project, worth carrying forward: a mean-flow prediction scores
      NSE = 0 but KGE = 1 − √2 ≈ −0.41 (Knoben, Freer & Woods 2019) — do not
      use KGE > 0 as if it were the same "beats climatology" bar as NSE > 0.

## Milestone 7 — forcing sensitivity

- [ ] WFDE5_CRU_GPCC baseline — **NOT STARTED** (depends on Milestones 1-6).
- [ ] ERA5 comparison — **NOT STARTED**.
- [ ] MSWEP precipitation sensitivity — **NOT STARTED**.

## Milestone 8 — agent/cascade interface

Not a scientific milestone: makes this repo's checks callable by a future
cross-repo orchestrator (e.g. a not-yet-built `ecland-cascade`) or a
low-footprint local coding agent (e.g. `qwen2.5-coder:7b` via Ollama), without
requiring it to read the full scientific codebase or parse prose logs.

- [x] `AGENTS.md` — short operating contract (safe/approval-needed/forbidden
      commands, fast entrypoint, escalation rule).
- [x] `docs/agent_quickstart.md` — under ~1500 words, what/status/first
      command/where results land.
- [x] `docs/benchmark_contract.md` — Gate 0-5 definitions, JSON result
      schema, failure-code vocabulary.
- [x] Benchmark profiles (`benchmark.yaml`: fast/smoke/intermediate/
      reference/production).
- [x] JSON result schema (`benchmark_result.json`, one per experiment run).
- [x] `scripts/benchmark.py` — deterministic CLI, `--profile {...}`, writes
      the JSON result, compact per-check progress lines, exit code 0/1/2.
- [x] Synthetic tests for the interface itself (`tests/test_benchmark.py`) —
      no WFDE5 archive or ecLand executable required.

**Honest current scope**: only Gate 0 (repository: Python/Bash syntax) is a
real, executable check right now. `--profile fast` also runs `pytest tests/`
(all synthetic). `--profile smoke/intermediate/reference/production` exit
with status `NOT_IMPLEMENTED` (exit code 2). That is now a gap in the
*interface*, not in the science: Milestones 1-5 have since produced real,
validated results (14 archived annual segments, budget closure measured), so
Gates 1-5 are implementable and simply have not been wired to the checks that
already exist (`run/check_run.py`, `validation/check_budgets.py`,
`init_clim/validate_init_grid.py`, `cama_flood/validate_remapping.py`).
Do not read "the CLI exists" as "the pipeline works" — see `CLAUDE.md`'s
single most important rule.

## Water-cycle bugs found and fixed (2026-09-29)

Two independent bugs in ecLand, same shape -- a correction that clips a
reservoir and silently drops the residue. Fixed on the user's `develop` fork
(`0d07a86`), NOT yet upstream.

1. **Snow cap discarded mass** (`surftstp_ctl_mod.F90:731`). The permanent-snow
   cap truncates the pack to 10000 kg/m2 and threw the excess away. `ZROFS`
   exists to carry it to surface runoff as ice calving and was declared,
   zeroed and added to `PROFS` -- but **never assigned**. ~1673 Gt/yr,
   Greenland and the Antarctic margin. A third defect in the same place: the
   calving add sat inside `IF (LEROLAKE)`, gating an ICE term on a LAKE switch.
2. **Deepest soil layer discarded a deficit** (`srfwng_mod.F90:176`). The
   negative-soil-moisture correction cascades the deficit downward, but at the
   bottom layer `IF (JK < KLEVS_WB)` does not fire and it is clipped away.
   ~214 Gt/yr at 1860 hyper-arid points -- Sahara/Sahel, Atacama, Peruvian
   coast -- the only places where the whole column runs dry.

**Verified by ecLand's own per-grid-point checker** (`LEWBCHECK`, 1 day,
global coupled): violations **172828 -> 96093 -> 0**, `sum|residual|`
**8.12e-01 -> 4.29e-02 -> 0**, `run.log` **280 MB -> 109 KB**. Zero at a
~machine-epsilon threshold. Full-year 1994 decomposed by surface (Gt):

        ice-capped     +1673.2  ->    -0.1
        all other land  -213.8  ->    -0.0
        lake-bearing   -2670.0  -> -2376.3
        TOTAL          -1210.6  -> -2376.4

The TOTAL rises, and that is the correct result: the old global figure closed
by **cancellation** of +1673 (ice) against -2670 (lakes), and removing the ice
error unmasks the lake term. A larger headline residual now means a more
trustworthy archive. Discharge impact **-0.52%**.

**What remains is not an ecLand bug**: ~2400 Gt/yr of lake evaporation with no
source, because FLake carries lake temperature with a fixed depth and no water
mass budget. CaMa's closure path is `LWEVAP` (recovers 0.1%, floodplain-limited)
plus `LWEXTRACTRIV`, which is **dead code**. Closing this needs upstream work.

**Performance note, measured**: two nodes (16 ranks x 16 threads, 256 CPU, `np`)
is **not** faster for annual segments -- 13964 forecast days/day against 14964
on one node at 16x8. A one-month test suggested 20437 and did not reproduce at
annual scale; do not extrapolate node scaling from short runs. The real win is
the validated forcing cache (604 s/year, ~18%).

## Campaign v2: 1988-2024 re-run with the water fixes (2026-10-01)

**COMPLETE and fully validated.** 37/37 segments, zero failures, zero requeues,
~47 min/simulated year, archived to `ec:/pad/wfde5-ecland-v2` (all 37 years
verified present with their full file set). The pre-fix archive stays at
`ec:/pad/wfde5-ecland` as the comparison control -- do not overwrite it.

**Validation sweep over all 37 years** (`check_run.py` + budget + per-surface
decomposition + lake temperature):

        check_run (NaN/Inf)   37/37 PASS
        ice-capped points     -0.6 .. -0.0 Gt   (was +1673 Gt/yr)
        all other land        +0.0 Gt           (was  -214 Gt/yr)
        lake-bearing       -2470 .. -2324 Gt
        water residual     1.977% .. 2.191%     (0 failures)   [see 2026-10-10 note]
        TLWML max         304.95 .. 308.46 K

**2026-10-10:** these numbers come from a script that is not in this
repository -- they were never saved at all -- and the committed
`validation/check_budgets.py` disagrees with them by a factor of four. See the
note under "Campaign v4" below. That note
applies to this table too: the v2 and v4 tables are identical to four
significant figures in every row, which means one was copied from the other
rather than independently measured. Which campaign the numbers were actually
taken on is now unknown.

Both leaks closed to within rounding in **every year**, not a sample. Lakes
carry the entire remaining residual; there is no fourth unexplained term.

The headline residual RISES (~1% -> ~2%) and that is the improvement: the old
figure closed by **cancellation** between the +1673 ice error and the -2670
lake term, so it drifted year to year and 1994/1995 failed outright. There is
now one physical term, steady to +-5%.

Lake temperatures are homogeneous end to end (304.95-308.46 K). The previous
archive ran the FLake nudge ON 1988-2000 and OFF from 2001, leaving a **6.3 K
step** at the join; that inhomogeneity is gone.

**CI**: full ecLand suite **20/20 green** with `LEWBCALVFIX`/`LEWBDEEPFIX`
defaulting `.TRUE.` -- 4 reference tests + 16 ifsbench including the global T21
coupled case, dp 2D at 1e-8 tolerance. Taking these changes upstream would NOT
require regenerating reference values: the fixed paths do not activate in the
reference domains (no >10 m w.e. snowpack, no fully drained soil column).
**The ecLand tests cannot be run with `ctest -j`** -- the sp and dp variants
share a working directory and clobber each other's restart, producing an
NCERROR in `sucdfres` at init that looks like a physics failure and is not.

## The DROFUNIT bug: all discharge was 24x too small (2026-10-02)

`DROFUNIT` is the runoff-to-CaMa coupling interval **in seconds** and must
equal `TCOUPFREQ * 3600`. This repo's template carried `DROFUNIT = 86400`
with `TCOUPFREQ = 1`, so every discharge in campaigns v1 and v2 is **24x too
small**. Verified three ways: in code (CaMa's runoff buffer is zeroed at each
handover, so the divisor is the handover interval, not a day), by magnitude
(Amazon annual mean 6,022 m3/s against an observed ~175,000), and by the
correction landing within 15% on three of four large rivers.

The same error was present in the **shipped ecLand T21 reference**
(`tests/ifsbench/namelist_cmf_2d_gl_t21`) at 2x, fixed upstream in `eca7b93`
and measured at **2.005x**.

Two process failures let this survive two complete 37-year archives:

- **The validation sweep never looked at discharge.** Budgets closed and
  `check_run` passed throughout, because `DROFUNIT` affects only CaMa's
  internal scaling and not ecLand's water balance at all. Gauge comparison
  is now part of the sweep.
- **A hollow verification.** The T21 test fetches `namelist_cmf_2d_gl_t21`
  into `input_cmf.nam` only *when absent*, so a cached copy from an earlier
  run is reused silently. "4/4 tests pass with the corrected value" was
  measured against the stale namelist and was meaningless. CI provably
  cannot catch a wrong `DROFUNIT`; any upstream fix should carry a runtime
  assertion in `CMF_FORCING_INIT` instead of relying on a reference value.

`run/run_ecland.sh` now asserts `DROFUNIT == TCOUPFREQ*3600` and refuses to
run otherwise.

## Campaign v4: the naturalised control (2026-10-02)

**COMPLETE and fully validated.** 37/37 segments, zero failures, archived to
`ec:/pad/wfde5-ecland-v4`. This is the naturalised (no-dam) control the dams
experiment is measured against. v3 was stopped deliberately once the
`DROFUNIT` error was understood, rather than being allowed to finish as a
third unusable archive.

        check_run (NaN/Inf)   37/37 PASS
        ice-capped points     -0.6 .. -0.0 Gt
        all other land        +0.0 Gt
        lake-bearing       -2470 .. -2324 Gt
        water residual     1.977% .. 2.191%                   [see note below]
        TLWML max         304.95 .. 308.46 K   (no 2000/2001 step)

**The three per-surface lines and the ~2% water residual in the table above
were computed ad hoc and never saved, so they cannot be reproduced.** No script
producing that decomposition exists anywhere -- not in the working tree, not in
any commit reachable from any branch, and no `*.py` was ever deleted from this
repo (`git log --diff-filter=D -- "*.py"` is empty). They were almost certainly
one-off inline Python in a shell command. An earlier version of this note said
they "come from a script that is NOT in this repository", which wrongly implied
the script exists somewhere else; it does not. They
**disagree with the committed checker by a factor of four**. `validation/check_budgets.py` -- one commit, never modified -- gives
0.057-0.491% of precipitation on v4 1988/1989/2000/2012/2024 (all PASS),
never ~2%. The two are also self-inconsistent: if lakes carry -2,400 Gt and
all other land ~0, the total cannot be the -568 Gt the checker measures for
1989. Until the decomposition is reproducible, treat the committed checker's
numbers as this repo's water closure and the per-surface split as
**unverified** -- it may well be right, but nothing here can re-run it.

Discharge against observed annual means: Mississippi 99%, Congo 106%,
Amazon 77%. Yangtze (62%) and Yenisei (41%) remain low and want a proper
GRDC comparison -- **NOT STARTED**.

Remaining residual is lake evaporation: FLake has a fixed depth and no water
mass budget, so ~2% of land precipitation leaves the system unsourced. With
`DROFUNIT` corrected, `LWEVAP` recovers **19.6%** of that term (464.6 of
2,376 Gt in 1994) and costs 3.28% of discharge. The earlier "0.1%, not worth
it" measurement was taken with the 24x bug in place: extraction is capped by
floodplain storage, and there was almost none to draw on. v4 and the dams
campaign both run `LWEVAP=false`; turning it on is a defensible third
configuration and must not be mixed into either archive mid-stream.

## Dams campaign: year-by-year commissioning 1988-2024 (2026-10-08)

**IN PROGRESS** -- 35/37 segments COMPLETED, zero failures, archived to
`ec:/pad/wfde5-ecland-dams`. Y2022 running, Y2023/Y2024 queued.
Identical to v4 in every respect except `namelist_cmf_global_dams.tmpl`
(`LDAMOUT`, `LDAMYBY`, `LDAMH22=.FALSE.`), so the pair isolates dams.

Dam parameters (`cama_flood/dams/dam_params.csv`) are derived from v4's own
discharge: Gumbel/L-moments Q100 per cell, `Qf = 0.3*Q100`, `FldVol`/`ConVol`
split 37/63. 3,982 GRanD dams merge to **3,697 cells** (CaMa allows one dam
per cell via `I1DAM`), capacity 6,642.7 km3 preserved exactly through the
merge, 0 duplicate cells. The 3,127 sub-grid dams remain excluded; the 20
above 1 km3 could be hand-reallocated.

**`LDAMYBY` VERIFIED** by `validation/check_dam_commissioning.py`. This took
three failed attempts and the failures are the useful part -- each wrong test
looked convincing:

- `damsto > 0` proves nothing. `CMF_DAMOUT_WATBAL` advances storage for every
  in-domain dam, `DamStat==-1` included, and init seeds an un-built dam to
  `rivsto+fldsto`. "Active cells" returns ~3,696 of 3,697 in **every** year
  whether commissioning works or not.
- `allocated dams: 108` of 3,697 is not dams being dropped. CaMa logs per MPI
  region; that is rank 1's share. The 16 regions sum to **exactly 3,697** --
  a clean partition.
- "differs from the control at a dam cell" is not regulation. Dams sit on a
  network, so a cell downstream of a commissioned dam differs without being
  regulated. This flags 78% of the not-yet-built dams in 1988.

What works is the asymmetry plus a before/after on it. `CMF_CALC_DAMOUT`
cycles on `DamStat<=0`, so an un-built dam leaves `D2RIVOUT` natural, and you
cannot get bit-identical annual-mean discharge at a cell whose dam regulates
it:

        DamYear <= 1988 (2,920 cells)  identical to control:  1988: 0   2020: 0
        DamYear >  1988 (  670 cells)  identical to control:  1988: 148 2020: 0

All 148 provably-inert 1988 cells (DamYear 1989-2017) differ by 2020, mean
|dQ| 12.8 m3/s. Dams switch on in their build year and not before.

Two properties of this configuration that belong in the experiment metadata:

- **107 cells carry `DamYear = -99`** (missing in GRanD). `DAMOUT_INIT`'s
  branch requires `DamYear > 0`, so they fall through to `DamStat=2` and are
  present for all 37 years. The data chose that, not us.
- **`ISYYYY` is the simulation START year**, read once in `DAMOUT_INIT`.
  Commissioning is only correct because the campaign is chained one calendar
  year per segment; a single multi-year segment would freeze every dam at its
  start-year status.

CaMa's `log_CaMa.txt-<rank>` and `damtxt-<year>.txt` -- the only direct record
of `DamStat` -- are written into `ecland_run_model.sh`'s ephemeral run
directory and deleted on success. They were recoverable here only because a
segment happened to be running. Worth archiving.

## ROOT CAUSE: CaMa-Flood was cold-started every year, in BOTH campaigns (2026-10-10)

**This supersedes the section below it.** The symptom recorded there -- the
dams archive carrying ~866 km3/yr that does not come from the forcing -- is
real. The cause attributed to it was wrong. There is no bug in CaMa's dam
physics. The bug is in this repository's own run driver.

`run/run_ecland.sh` never staged a CaMa-Flood restart, and the CaMa namelist
templates hardcode `LRESTART=false`. ecLand chained correctly the whole time
via `RESTART_FROM` -> `soilinit`, so **every one of the 37 segments of both
campaigns restarted CaMa from an EMPTY river network on 1 January**, while
every other signal said the run was healthy: exit 0, all output present and
nonzero, land-side water and energy budgets closed, ecLand restart continuity
verified by `VERIFY_RESTART`. Confirmed three independent ways:

1. **The run's own log.** `log_CaMa.txt-1` from the real 2022 dams segment:
   `LRESTART  F`. The rendered `input_cmf.nam` from that run: `LRESTART=false`,
   `CRESTSTO=""`.
2. **The source.** `run_ecland.sh` has no CaMa-restart staging at all;
   `ecland_run_model.sh` links `restartin_cmf.nc` only under its own `-R`
   route, which `run_ecland.sh` deliberately does not use. With
   `LRESTART=.FALSE.`, `CMF_RESTART_INIT` sets `P2RIVSTO=P2FLDSTO=0`
   (`cmf_ctrl_restart_mod.F90:100-101`).
3. **The archived output.** On 1 Jan 2000 the Amazon discharges **-369 m3/s**,
   the Congo **7 m3/s** (annual median 39,324), the Mississippi **exactly 0 for
   nine days**; the Amazon then climbs to 50,617 by day 30 and 148,247 by day
   90. `validation/check_cmf_restart_continuity.py --gauge-series` flags
   **38 of 38** gauge-years, exit 1.

### Why this produced exactly the numbers that were measured

With an annual reset, each year's budget is `Out = In + S_start - S_end`, so
whatever storage stands at 31 December is simply discarded.

| | measured independently | predicted by the annual reset |
|---|---|---|
| v4 deficit | +1,894 km3/yr | `S_end(v4)` = 2,041-2,358 km3 |
| dams deficit | +1,028 km3/yr | `S_end(dams) - ConVol` = 5,331 - 4,185 = 1,146 km3 |
| dams minus control | +866 km3/yr | `ConVol - S_end(d) + S_end(v4)` = +895 km3/yr |

The extra term in the dams run is genuine water creation, and it is the
`LDAMOUT` cold-start branch: `DAMOUT_INIT` with `.not. LRESTART` sets
`P2DAMSTO=ConVol` **and `P2RIVSTO=ConVol`** for every activated dam
(`cmf_ctrl_damout_mod.F90:266-269`, ungated by `LiVnorm`). That re-creates the
whole conservative volume of every reservoir **every 1 January**: 3,425 km3 in
1988 rising to 4,185 km3 in 2024 (3,027 -> 3,697 activated dams). Flat in time,
concentrated at dammed rivers, not scaling with reservoir operation -- which is
exactly the signature that was measured and could not be explained.

The Zambezi case resolves the same way: Kariba + Cahora Bassa hold 264 km3
total, ~166 km3 of it `ConVol`, re-created annually -- against a measured flat
excess of 70-83 km3/yr at Tete and a 467 km3 cumulative excess over 2019-2024.

`LiVnorm=.TRUE.` in `namelist_cmf_global_dams.tmpl` is **not** the culprit: it
gates only the *restart* branch (`:274-284`), which never executed.

### What this means for the two archives

- **Neither archive's discharge is usable as it stands.** Both discard
  ~2,100 km3/yr of river storage (5.5% of global runoff) at every segment
  boundary, and the early months of every year are spin-up from an empty
  network rather than simulation.
- **The dams archive is worse**, additionally creating 3,425-4,185 km3/yr.
- **The ecLand side of both archives is unaffected and remains valid** --
  one-way coupling, `LECMF1WAY=.TRUE.`, and ecLand's own restart chaining was
  always correct and verified. All land-surface results, budgets and the
  Milestone 1-3 conclusions stand.
- v4's interannual *signal* is still real where it was checked -- the Zambezi
  tracking its own forcing (-97% discharge on -50% precipitation, -85% runoff)
  is a property of the forcing, not of the initial state.

### The fix (committed 2026-10-10, NOT YET RUN)

- `run/run_ecland.sh`: new `CMF_RESTART_FROM`. Patches the rendered CaMa
  namelist to `LRESTART=.TRUE.` and `CRESTSTO=<abs path>`, which is all CaMa
  needs (`READ_REST_CDF` does `CFILE=TRIM(CRESTSTO)`). Guards that a
  `LDAMOUT=.TRUE.` run is not chained from a control restart, which has no
  `damsto` and would die in `NF90_INQ_VARID`.
- `run/run_ecland.sh`: `VERIFY_CMF_RESTART` compares the first CaMa output
  day's global `rivsto` against the staged restart's and fails the run if they
  differ by more than a factor two. The old `VERIFY_RESTART` passes happily
  while CaMa cold-starts -- that is precisely how this survived a whole
  campaign.
- `run/submit_campaign.py`: `--cmf-restart-from`, chains
  `restartout_cmf.nc` per segment, and the dry-run line now prints **both**
  restarts (`ecland=... cama=...`) because a campaign that chains one and not
  the other looks entirely healthy.
- `validation/check_cmf_restart_continuity.py`: new. Rigorous mode (restart vs
  first output day) and a cheap gauge-series screen. **Run against the real
  archive: FAIL, 38/38 gauge-years, exit 1.**
- All three `namelist_cmf_global*.tmpl` headers now say `LRESTART` is patched
  at render time and the literal value is not what ran.

### Staged two-year check: the fix WORKS (2026-10-10, jobs 37007228/37007229)

**VERIFIED in a real coupled run.** Two chained v4-configuration segments,
1988 (CaMa cold start, correct for a first segment) then 1989 (chained). Both
COMPLETED, exit 0:0, ~57 min each. Distinct `STA` and no `ECFS_DIR`, so the
real archives could not be touched.

        == CaMa restart chaining: CRESTSTO <- .../CMFRST88_.../restartout_cmf.nc ==
        == Verifying CaMa-Flood restart continuity ==
          staged restart rivsto   =     2001.4 km3
          first output day rivsto =     2003.7 km3
          ratio = 1.001
          OK: CaMa river storage was carried from the previous segment

`validation/check_cmf_restart_continuity.py --gauge-series` on the chained
1989: **PASS, 0 of 19 gauges below threshold, exit 0** -- against **FAIL, 38 of
38**, on the archive. The Congo starts 1989 at 66,724 m3/s against a 62,409
median (ratio 1.07); in the archive it started at 7 m3/s.

**The recovered water matches the prediction to 0.2%.** 1989 annual outflow to
ocean plus inland terminations, same year, same gauge cells:

        fixed   (restart chained)   ocean 36,373  inland 638  total 37,011 km3
        archive (cold-started)      ocean 34,643  inland 471  total 35,114 km3
        recovered                                                  +1,897 km3/yr

against the independently measured v4 deficit of **+1,894 km3/yr**.

**And it independently confirms the remap loss.** With storage now continuous
the 1989 budget can be closed from this run alone: S_start 2,357.5 km3,
S_end 2,557.6, dS +200.1, so CaMa accounted for 37,211 km3 against ecLand's own
40,646 km3 of runoff (`-(Qs+Qsb)`, `check_budgets.py` on the same run) -- a
shortfall of **3,435 km3 (8.45%)**, against the **3,390 km3 (8.86%)** computed
by hand from `inpmat.nc`. Two independent routes to the same ~3,400 km3/yr.
That is now the *only* large unexplained term, and it is exactly what
`cama_flood/validate_remapping.py` was specified to catch. Caveat: `totout`
excludes `pthout`, so any bifurcation flow reaching the ocean is uncounted and
3,435 km3 is an upper bound on the remap loss, not a closure.

**The test run IS a byte-level reproduction of v4's ecLand.** Verified by
md5, not assumed:

        4d073a0159a16f6e89f12bbf96277784  Y1989/restartout.nc    (v4 archive)
        4d073a0159a16f6e89f12bbf96277784  CMFRST89/restartout.nc (staged test)
        32a2044a081775c51fabdb8bdd1ff8a2  Y1988/restartout.nc
        32a2044a081775c51fabdb8bdd1ff8a2  CMFRST88/restartout.nc

and the rendered ecLand namelists are byte-identical (`diff` is empty). So the
+1,897 km3 recovery was measured against a land model that is bit-for-bit the
archive's, and nothing on the ecLand side confounds it. This is a stronger
result than was first written up here.

**An earlier version of this section claimed the opposite and was wrong.** It
said v4's 1989 ran the FLake nudge ON while the test ran it OFF, and attributed
a budget difference to that. Every one of the 37 campaign-year namelists has
`TMNW_NDG_TIMESCL = 1.0E30` -- nudge OFF; the only rendered namelist in this
repo with the nudge on is `ABFLAKEON`, the deliberate A/B test. The retracted
paragraph also invented a mechanism and a quantification for a difference that
does not exist. `check_budgets.py` FAILED, and instead of chasing the
measurement I reached for the most interesting switch I knew of and wrote it up
as established -- the exact failure mode already recorded in this repo's own
memory as "don't explain away your own check", for the third time. The
disproof was one `diff` away and was not run.


Other verification: `bash -n`, `compileall`, `--help`, the namelist `sed` tested
against the real `input_cmf.nam` (patches `LRESTART`, leaves `LRESTCDF`
untouched, `LDAMOUT` detection correct both ways), restart files confirmed to
contain every variable `READ_REST_CDF` requires (`rivsto`, `fldsto`,
`rivout_pre`, `fldout_pre`, `rivdph_pre`, `fldsto_pre`, `pthflw_pre`, plus
`damsto` in the dams archive). Status: **DONE** -- the fix is exercised and
verified in a real coupled run; see the staged check above.

A second instance of the same bug was found while setting that check up:
`run/run_ecland_cmf.slurm` sources its config but only exports named
variables, and `CMF_RESTART_FROM` was not among them, so the fix would have
been silently inert and the staged check would have "passed" by cold-starting
again. Fixed in 6e9c905. The wrapper's own comments already warned about
exactly this for `ECLAND_EXE` and `NAMELIST_CMF_TEMPLATE`.

### Required next step

Both campaigns need re-running with the restart chained (~28 h each; the
staged segments took 57 min each at 16 ranks). **Nothing has been submitted.**

**There is no configuration question to settle first.** An earlier version of
this section asked whether to keep `TMNW_NDG_TIMESCL = 1.0E30` or "match the
archive's nudge-on setting"; the archive's setting IS `1.0E30` and always was.
Keep every template exactly as committed. The re-run then changes one thing
only -- the CaMa restart -- which is what makes it interpretable.

Note `run/configs/campaign/Y*.env` as committed carry no `CMF_RESTART_FROM`;
they are rewritten by `submit_campaign.py` at submission, so they will pick it
up automatically.

### What was wrong in my own earlier reasoning, and why

Recorded because the failure was one of method, not of arithmetic. I tested
whether CaMa's dam *physics* conserved water -- `UPDATE_INFLOW`, the operating
rule, the flow limiter, `CMF_DAMOUT_WATBAL` -- found them all conservative,
and then concluded the leak must be in the dam path anyway, because the dam
path was the only thing that differed between the experiments. It was not: the
*run configuration* differed from what I believed it to be. I never checked
`LRESTART` in a rendered namelist or a run log, having assumed that because
ecLand's restart chaining was carefully built and verified, CaMa's existed too.
The one-line check that would have settled it on day one -- `grep LRESTART` in
the real `input_cmf.nam` sitting in the scratch directory the whole time --
came only after reading the dam module end to end twice.

## Dams archive: the earlier, SUPERSEDED diagnosis (2026-10-09)

Kept for the record. The measurements here are sound and were what led to the
root cause above; the attribution to "CaMa's dam path" is **withdrawn**.


**The dams archive is COMPLETE and verified, and must NOT be used for
discharge or anything downstream of it.** CaMa's dam code path adds roughly
866 km3/yr (2.3% of global runoff) that does not come from the forcing.
~~The v4 naturalised control is unaffected and remains valid.~~ **WITHDRAWN
2026-10-10: v4's discharge is affected too** -- it discards ~2,100 km3/yr at
every annual segment boundary. Only v4's *ecLand* side is unaffected. See the
root-cause section above. 37/37 segments, every file present and nonzero,
~35.3 GiB each (~1.3 TB), `ec:/pad/wfde5-ecland-dams`.

### What is established

- `LDAMYBY` commissions dams in their build year -- `validation/check_dam_commissioning.py`, PASS.
- The coupling is genuinely one-way: ecLand `restartout.nc`, `o_gg.nc` and
  `o_wat.nc` are **byte-identical** between the dams archive and v4 for 1988,
  2000, 2012 and 2024. v4's validated ecLand budgets therefore apply to the
  dams archive by construction, and only `cmf/` + `restartout_cmf.nc` carry
  the experiment (~30 GiB/year of the dams archive duplicates v4 exactly).
- CaMa state does differ, as it must: 172,591 `rivsto` cells.
- `rivdph` differences up to 468 m are **100% confined to dam cells** at every
  threshold tested (10/50/100/200/400 m), with zero spread into the network.
  Control depth at those same cells peaks at 10.7 m. CaMa holds reservoir
  volume as `rivsto` in the dam's own cell, so `rivdph` is a diagnostic that
  does not apply there. Not an instability -- and easy to mistake for the
  run-of-river instability under "Open blockers".
- Peak attenuation -5.5% and Q10 +86% (median over 19 gauges, 2010-2024):
  reservoirs behave as reservoirs.

### The unexplained difference

From **byte-identical runoff input**, the dams run carries ~866 km3/yr more
water than the control:

        In (ecLand runoff, 2020)                 38,261 km3
        reaching CaMa through inpmat             34,871 km3   (remap loss 3,390, 8.86%)

        run    Out(totout, mouths)  Out(inland)     dS    imbalance vs CaMa input
        v4              32,866           625      -515        +1,894 km3 (5.0%)
        dams            33,503           677      -338        +1,028 km3 (2.7%)

**Both runs LOSE water in this accounting; neither creates it.** The absolute
residual is very likely my accounting, not the model: `totout` is
`rivout+fldout` and **deliberately excludes bifurcation flow**
(`cmf_calc_stonxt_mod.F90:77` -- adding `pthout` was "a bug before v4.2"),
`LPTHOUT=.TRUE.`, and year-end `pthflw_pre` sums to ~4,300-4,500 km3/yr if
sustained -- more than enough to cover it. `pthflw` was not in `CVARSOUT` for
either archive, so this cannot be closed from existing output.

The **inter-run difference of 866 km3/yr (2.3% of input) is water the dams run
creates.** This is now established, not inferred. Bifurcation does not account
for it (dams has +114 km3/yr *more* bifurcation flow -- same sign, an order of
magnitude too small), and the Zambezi closes the argument:

        Zambezi box, 1988 -> 2024
          precipitation (WFDE5)        2,747 -> 1,385 km3/yr   -50%
          ecLand runoff (both runs)      494 ->    72 km3/yr   -85%
          v4 discharge at Tete         4,292 ->   138 m3/s     -97%
          dams discharge at Tete       5,310 -> 2,750 m3/s     -48%

The control is CORRECT: its discharge tracks its input, with the strong
nonlinear amplification a semi-arid basin gives (a 36-50% precipitation
decline produces an 85% runoff decline). In 2024 the dams run delivers
86.9 km3/yr at Tete from a box producing 72.1 km3/yr -- and that box is larger
than Tete's catchment, so the true exceedance is worse.

Single-year excess could be legitimate reservoir drawdown, so the integral:

        dams-minus-control at Tete, 2019-2024   467 km3 cumulative
        total configured Zambezi capacity       264 km3  (Kariba 185, Cahora Bassa 63)
        ratio                                  1.77x

and the annual excess is FLAT (70.9, 70.4, 81.5, 80.5, 81.0, 82.6 km3/yr), not
decaying. A reservoir releases its capacity once and a drawdown signal decays.
A flat excess exceeding total capacity, with storage steady, is a source.

It is sharply localised: the **top 20 river-mouth cells carry 92%** of it, all
on heavily dammed rivers, and the control is implausibly low at exactly those
mouths --

        Dnieper  (46.62N  32.38E)  ctl    314 -> dams  1,132   (obs ~1,670)
        Don      (47.12N  39.12E)  ctl    116 -> dams    462
        Zambezi  (-18.62N 36.38E)  ctl  1,770 -> dams  3,949   (obs ~3,400)
        Plata    (-34.12N -58.38E) ctl 11,031 -> dams 15,048

and the excess is **flat in time** (+628/+608/+636 km3/yr for 1995/2010/2020)
while active dams rise 3,203 -> 3,697, so it does not scale with reservoir
operation.

### The confound, which stands regardless

`CMF_CALC_DAMOUT` calls `UPDATE_INFLOW`, which replaces the local-inertial
outflow with a **kinematic-wave** estimate at every cell whose downstream is a
dam (`I1DAM==10`), explicitly "to suppress storage buffer effect (Shin et al.
2019)". The control never gets that treatment. So **dams-vs-control is not a
clean single-variable experiment at the discharge level**, even though ecLand
is bit-identical: it conflates

1. reservoir operation -- the intended signal, and
2. a routing-scheme change at upstream-of-dam cells -- an unintended confound.

This confound stands on its own merits even once the water-creation bug is
fixed: isolating the dam effect needs the same kinematic treatment in the
control, or a comparison restricted to cells far from dams. It is NOT, however,
the explanation for the 866 km3/yr -- that is a source, per the Zambezi
integral above. An earlier draft of this section had it the other way round,
reasoning that the control looked "implausibly low" at the affected mouths.
Part of that lowness is real drying in the forcing, and that reasoning was
wrong.

### One real conservation violation found in CaMa

`cmf_ctrl_damout_mod.F90:266-269` sets `P2RIVSTO = ConVol` where capacity
exceeds natural storage on a **cold start**, ungated by `LiVnorm` (the restart
branch at 274-284 *is* gated, default `.FALSE.`). That created ~2,800 km3 once,
in 1988. One-off, stays in storage, does not drive the gauge signal -- but it
is water from nothing and belongs in an upstream report.

### To close it

A short diagnostic year, both configurations, with `pthflw` and `damsto` in
`CVARSOUT`, which makes the balance closable instead of inferred. Needs a
SLURM launch -- **approval required, NOT STARTED**.

### Process notes

Four of my own measurement errors shaped intermediate conclusions and are
recorded so the same ground is not re-walked:

- `nextx < 0` as a river-mouth mask swept in all 784,417 non-land cells
  alongside the 18,481 real mouths (`-9` ocean, `-10` inland, `-9999` not land).
- `|Qs| + |Qsb|` as total runoff gave 66,000 km3/yr against a true ~38,000.
  The convention is `-(Qs+Qsb)`; `Qs>=0` and `Qsb<=0`, so abs-then-add
  over-counts by `2*Qs`. This is exactly the error `docs/cama_interface.md`
  exists to prevent.
- A driver script re-snapped gauge cells per invocation, so two year batches
  read **different cells** for Orinoco and Amur; Amur's resulting +5.75% was
  briefly reported as a conservation failure.
  `validation/compare_discharge.py` now **hard-fails** on inconsistent cells.
- `damsto` was reported as absent from the CaMa restart; it is present. The
  diff that "showed" it missing skipped variables absent from the control.

Also: **`cama_flood/validate_remapping.py` now exists** (2026-10-15), the
hard water-conservation gate CLAUDE.md specifies. It reproduces the ~3,400
km3/yr from a third direction and, more usefully, says where it goes. On
Y2001, grid-box convention:

        unmapped land, lat < -60 (Antarctica)      113.3 km3    0.29%
        unmapped land, elsewhere                     0.2 km3    0.00%
        mapped cells, inpa < source area          3287.6 km3    8.52%
        mapped cells, inpa > source area           -27.4 km3   -0.07%
        total                                     3373.7 km3    8.74%

**It is not Antarctica.** 98% of the *unmapped area* is Antarctic (26,678 of
26,690 unmapped land cells, 1.387e13 of 1.389e13 m2) but it carries 3% of the
loss, because Antarctic runoff per m2 is negligible -- an area table read
without weighting by runoff says the opposite of the truth, and I made exactly
that error before computing this. The loss is on *mapped* cells, and it is the
land-area convention: `inpa` tracks `gridbox area x landsea` to a median ratio
of **1.0011** (against 0.9983 for `inpa/gridbox area`), so `inpa` IS the land
area. 85% of the deficit comes from cells with `landsea < 0.95`, i.e. coastal
partial-land cells where ecLand's land mask and CaMa's catchment map disagree.
Against `area x landsea` the residual falls to **1,229.1 km3 (3.373%)** and is
two-sided -- 1,951.5 km3 where the catchment is smaller, 722.4 km3 where it is
larger -- so it is a coverage mismatch between two land masks, not a one-way
leak from a sign or weight error. Per cell the two masks agree poorly (1st
percentile of `inpa/source` 0.354, 99th 1.773); only the global integral
agrees to a few percent, which is worth remembering before using `inpa` as a
per-cell land area.

The 1e-9 bar `docs/cama_interface.md` asks for is therefore unreachable here,
and saying so is part of the check: the two models do not agree about where
the land is. The default `--tolerance` is 5%, which the land convention passes
with room to see drift and the grid-box convention fails.

## Open blockers

- `liaise-ecland`'s own reservoir/dam-module investigation (CaMa-Flood v4.20
  `LDAMOUT`) found a real, only partially understood numerical instability at
  fine time/space scales for run-of-river-type reservoirs — irrelevant to a
  first global naturalised (no-dam) pilot, but worth knowing before this repo
  ever turns dams on.
- ~~**ecLand's offline driver loads the ENTIRE declared forcing period into
  memory upfront, not streamed**~~ — **RESOLVED 2026-09-22** by implementing
  windowed forcing reads upstream in `/perm/pad/ecland` (user's `develop`
  branch, commits `fa34baa`..`b217d5a`). The diagnosis stands as recorded:
  `SUFCDF`, called once at init, read each variable wholesale into
  `GFOR(NPOI, JPSTPFC, 12)` sized for the FULL declared forcing length, and
  `dtforc.F90` only ever interpolated within that resident array. At 87,798
  land points a leap year of hourly forcing would have needed ~74 GB.
  The fix adds one namelist integer `NFORCWINDOW` (`NAMDIM`, **default 0 =
  disabled**, so every existing namelist keeps today's behaviour bit for
  bit): when set, `JPSTPFC = NFORCWINDOW`, `GFOR` is allocated small, and a
  guard at the top of `DTFORC` refills it through a shared read routine
  before any of that routine's dozen index formulas run — none of which were
  touched. Verified by equivalence (windowed vs. full-load output identical)
  and in production: the campaign runs `NFORCWINDOW=744`, and a full year
  does 12 refills at 0.70 h/simulated year.
  Two real bugs in the first cut of that work, both fixed before merge: an
  EOF latch that fired on "window didn't move" rather than on reaching the
  end of the record axis (out-of-bounds at small windows — there is now a
  hard refusal below `NFORCWINDOW=8`), and `RDFVAR`'s `ZTIMEN` being
  computed relative to call time, which is only correct when called once.
  `LOADIAB` and `LPREINT` are refused in combination with windowing rather
  than silently mis-handled.
- **FLake nudges mean lake temperature to soil temperature unconditionally**
  (found 2026-09-27, `flakeene_mod.F90:467-470`). Worked around in this
  repo's namelist templates with `TMNW_NDG_TIMESCL = 1.0E30`; **the code
  itself is unchanged upstream**, so any other user of that source still has
  it. The nudge has no lake/soil-validity condition, its depth weighting
  reaches full strength at the minimum lake depth (0.5 m in this archive, so
  one 1800 s step is one e-folding time), and its security clamp
  `MAX(T_MNW, RTPL_T_F)` bounds the result from below only. At lake-dominated
  points the soil column is degenerate and free to run hotter than any lake,
  so the lake is slaved to it unbounded. This stalled the campaign at 2001
  for four days; see Milestone 3 for the measured numbers. Whether a
  conditional guard belongs on `develop` in addition to the namelist switch
  is **an open decision, not done**.

## Immediate next step

**Campaign status (2026-10-08).** Four archives exist; only the last two are
scientifically usable, and the reason is recorded under "The DROFUNIT bug".

        ec:/pad/wfde5-ecland       v1  37/37  discharge 24x too small, and the
                                           two water leaks still open
        ec:/pad/wfde5-ecland-v2    37/37  water leaks fixed, discharge still 24x
                                           too small
        (v3)                              stopped deliberately mid-flight
        ec:/pad/wfde5-ecland-v4    37/37  ecLand USABLE; DISCHARGE NOT usable
                                           (annual CaMa cold start, -2,100 km3/yr)
        ec:/pad/wfde5-ecland-dams  37/37  ecLand USABLE (byte-identical to v4);
                                           DISCHARGE NOT usable (annual cold start
                                           PLUS 3,425-4,185 km3/yr created)

v1 and v2 are kept as comparison controls for the fixes themselves. **Do not
use either for discharge or for anything downstream of it.**

37 annual segments exist as real, verified output — daily-frequency
`o_gg`/`o_wat`/`o_efl` plus CaMa-Flood `rivsto`/`fldsto`/`totout`/`rivdph`,
each chained from the previous year's `restartout.nc` with continuity
verified rather than assumed (`VERIFY_RESTART`, which compares the model's
first output against the previous restart AND against climatology, and
requires the chain distance to be under 1% of the cold-start distance).
**That applies to ecLand only.** CaMa-Flood was never restart-chained in any
of these archives and cold-started at every segment boundary -- see "ROOT
CAUSE: CaMa-Flood was cold-started every year" above. `VERIFY_RESTART` passes
regardless, which is why it went unnoticed; `VERIFY_CMF_RESTART` now covers
the CaMa side.

2001 is the only segment produced with `TMNW_NDG_TIMESCL = 1.0E30`, so there
is a real physics discontinuity at the 2000/2001 join. The A/B experiment
recorded under Milestone 3 **sized** it, rather than leaving it a worry:
0.005% in runoff (negligible — two orders of magnitude below the budget
residual) against up to +24.7 K in lake temperature at individual points in
only 90 days. So the archive is homogeneous for the water cycle and is NOT
homogeneous for lake temperature or surface energy. **No rerun of 1988-2000
is needed for this repo's purpose**; anyone doing lake or energy work across
the join must know. An earlier draft of this file recommended rerunning all
37 years on the strength of a Y2001-vs-Y2000 comparison that confounded the
switch with interannual variability — that recommendation is withdrawn.

Next, in order:
1. ~~Resubmit 2002-2024~~ — **DONE** 2026-09-28, 23/23 segments COMPLETED.
2. ~~Decide the 1988-2000 lake question~~ — **DONE**, settled by the A/B
   experiment above: no rerun needed for the water cycle. Document the join
   for lake/energy users instead.
2a. **Finish the dams campaign** (Y2022-Y2024) and run the full validation
   sweep over its 37 years, then the dams-vs-v4 comparison this whole chain
   was built for — **IN PROGRESS**. `LDAMYBY` is verified; the archive itself
   is **NOT YET VALIDATED** beyond per-segment job success.
2b. **Archive `log_CaMa.txt-<rank>` and `damtxt-<year>.txt`.** They are the
   only direct record of `DamStat` and are currently deleted on success.
3. **Quantify global runoff totals** and the remaining Milestone 6
   validation — still **NOT STARTED**.
4. **`forcing/validate_wfde5.py` still does not exist.** The grid facts in
   `docs/forcing_variables.md` came from ad hoc inspection, not an automated
   check, and every forcing verification in this campaign has been manual.
   This is the largest unautomated gap in the chain.
5. **Upstream the two ecLand fixes** (the C4 `ICTYPE` bug in
   `farquhar_mod.F90:451` and the FLake nudging) to `ecmwf-ifs/ecland`. Both
   are on the user's `develop` fork only; the C4 bug affects 6.2% of land
   points and ~44% of `Anday` at the worst point, so other users are
   silently affected. Outward-facing — needs explicit approval.
