# cama_flood/

Conservative runoff transfer from the ecLand 0.5° grid to CaMa-Flood's
unit-catchment routing network, and the routing run itself.

Status: **online 1-way coupling (real MPI) built and debugged, one real crash
still open** — see `PLAN.md` Milestone 4/5, 2026-09-20.

- `build_global_cmf_fixdir.sh` — already ported, and **run for real**:
  `CMF_RES=glb_15min NPES_CMF=2` produces `ncdata.nc`/`rivpar.nc`/`outclm.nc`/
  `bifprm.txt`/`mpireg.nc` (a genuine 2-region map, not flattened — confirmed
  126,192/126,191 cell split). No clip needed; already global by construction.
- `derive_global_cmf_weights.sh` — **new**, not a port. Generalises
  `liaise-ecland`'s `derive_cmf_weights.sh` by *removing* its two
  LIAISE-specific steps entirely (the regional clip, and flattening
  `mpireg.nc` to a single region) rather than adapting them — global means
  using `build_global_cmf_fixdir.sh`'s own output as-is. Run for real:
  `inpmat.nc` mapping this repo's own 360x720 ecLand grid onto the global
  river network, conserved to 0.00% area error. **Found and fixed a real
  bug getting here**: `gen_inpmat.py`'s raw netCDF4-python output crashes
  `ecland-master-dp`'s Fortran/HDF5 reader (deep inside zlib's `inflate`) —
  needed the same `cdo -f nc4 -z zip_6` re-write `liaise-ecland`'s validated
  pipeline always applied, even though there's nothing to clip.
- `derive_cmf_weights.sh` (`liaise-ecland`'s own, LIAISE-specific) — not
  used here; superseded by the above for a global run.
- Coupled run driver lives in `run/run_ecland.sh` (`RUN_CMF=true`) and
  `run/run_ecland_cmf.slurm`, not here — see `run/README.md`.
- `validate_remapping.py` — the water-conservation gate CLAUDE.md requires.
  **Implemented 2026-10-15 and it applies to the online path**, which was
  the error in the earlier note here: the remap is not an offline step this
  repo skips, it is what `CMF_FORCING_PUT` does in memory every coupling
  step, using the same `inpmat.nc` this script reads. Given a grid file and
  `inpmat.nc` it reports coverage from the weights alone; add `--runoff` and
  it computes what ecLand produced against what CaMa received, decomposes
  the difference by cause, and exits nonzero above `--tolerance`. Measured
  on Y2001: 3.3732% (land convention, PASS) / 8.7443% (grid-box convention,
  FAIL). The 1e-9 bar the design doc asks for is unreachable because ecLand's
  land mask and CaMa's catchment map disagree cell by cell; the script says
  so rather than hiding it in a loose tolerance.
- `aggregate_runoff_to_daily.py`, `remap_runoff.py`: these describe an
  **offline/decoupled** runoff hand-off (matching `liaise-ecland`'s
  CaMa-Flood-GPU bridge work), a different architecture from the **online
  in-memory** 1-way coupling this repo actually uses
  (`CMF_FORCING_PUT`/`CMF_DRV_ADVANCE`, called directly from ecLand's own
  offline driver, no runoff file ever written or read). Still relevant if
  this repo later wants a decoupled chain (e.g. feeding CaMa-Flood-GPU), but
  **not** needed for the online coupled path already built. Not started.

## What actually works, confirmed 2026-09-20

Real 2-rank MPI: region decomposition, river topology, and the coupling loop
(`CMF_COUPLING: CALLING DRV_PUT & DRV_ADVANCE`, firing exactly on the
configured `TCOUPFREQ` schedule) all execute correctly against this repo's
real WFDE5 forcing and real surfclim/soilinit. Two more real bugs found on
the way here, beyond the `inpmat.nc` one above:

1. **`ecland-master-cmflood-dp` is not the coupled executable it sounds
   like.** Confirmed via `src/surf/cmflood.cmake`: it's built from
   `offline/cmfld1s.F90`, a *standalone* CaMa-Flood-only driver (reads
   pre-computed runoff from plain binary files, `./runoff/Roff____
   YYYYMMDD.one`) — unrelated to online coupling. The real online-coupled
   executable is plain `ecland-master-dp` (built from `master1s.F90`,
   linked against `libecland_cmflood_dp.so`; its own driver chain calls
   `CMF_FORCING_PUT`/`CMF_DRV_ADVANCE` directly, never touches the binary
   runoff-file path at all). `run/run_ecland.sh` uses the correct one.
2. **`TCOUPFREQ` (`NAMDYN1S`) is read in HOURS, not seconds** — confirmed
   against `cnt41s.F90`'s own trigger check and ecland's official global
   coupled reference (`tests/ifsbench/namelist_2d_gl_t21`, which documents
   "in hours"). The uncoupled namelist template's inherited default (86400)
   is meaningless there (coupling off) but, taken literally as hours, would
   mean "couple every 3600 days" — i.e. never.

## What's still open

A 2-rank coupled run needs ~4.3-4.5 GiB resident **per rank** — comfortably
exceeds this project's interactive session's fixed 8 GiB memory cgroup
almost immediately, independent of run length or coupling frequency (a
5-day test crashed by model step 6). Not a memory leak — confirmed via the
kill report's own `requested/default memory limit for job/session: 8192MiB`.
Currently running via `run/run_ecland_cmf.slurm` (a real SLURM batch
allocation, `--mem=32G`, submitted only after explicit user approval per
`AGENTS.md`) to get real headroom — see `PLAN.md` Milestone 4/5 for the
outcome once that run completes.

Separately: `PLAN.md`'s "Open blockers" now documents a real, confirmed
architectural finding — ecLand's offline driver loads the *entire* declared
forcing period into memory upfront (not streamed), which will matter for
any multi-year run regardless of this session's constraints.
