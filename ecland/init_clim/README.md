# init_clim/

ecLand `surfclim` (time-invariant surface climatology) and `soilinit` (initial
soil/snow state) construction, on the exact global ecLand grid.

Status: **DONE for a 1988 global build, real files, real validation** — see
`PLAN.md` Milestone 2. Path taken: ecland's own actively-maintained
`tools/create_forcing/ecland_create_forcing.py` (config-driven, MARS/CDS,
ERA5-based), **not** the older `init_clim.py` — that script's own
`osm_pyutils.grid_gaussian` import no longer resolves against the current
`/perm/pad/ecland` checkout (see `docs/migration_from_liaise.md`'s corrected
entry), so it is not used here.

- `config_global.yaml.tmpl` — template for `ecland_create_forcing.py`'s `2D`
  config, rendered via `envsubst`. Bounding box is the whole globe at
  cell-center corners (`clatn=89.75/clats=-89.75/clonw=-179.75/clone=179.75`,
  `dx=0.5`) — this specific parameterisation is what makes the output land
  exactly on WFDE5's real grid, not the naive `90/-180/-90/180` corners.
- `build_global_surfclim_soilinit.sh` — runs the tool, then
  `flip_latitude_to_ascending.py`, then `validate_init_grid.py` as a real
  gate (non-zero exit if the grids don't match). Requires `module load nco`
  first.
- `flip_latitude_to_ascending.py` — **new, needed script**: the tool writes
  latitude in native MARS/GRIB order (descending); WFDE5 is ascending. This
  is not automatic — the older `init_clim.py`'s `grib2nc_LL` used to handle
  it via `flip_lat=True`, the newer tool doesn't. Found and fixed on the
  first real run, 2026-09-19.
- `validate_init_grid.py` — compares the forcing grid, `surfclim` grid, and
  `soilinit` grid pairwise; PASS only when coordinate arrays and ordering
  agree exactly (hard requirement, see `CLAUDE.md`'s "Grid invariants").
  Land-mask agreement between surfclim's ERA5-derived mask and WFDE5's own
  coverage is reported (98.0% on the real 1988 run) but never asserted as
  pass/fail — they're independently derived and not required to match
  bit-for-bit.
- `init_clim.py`, `init_clim.sh`, `clim.sh` — the originally-planned
  `liaise-ecland` port. **Not used** for the reason above; kept for
  reference/provenance, not deleted.

Real output lands in `init_clim/work/` (gitignored, matches `.gitignore`'s
existing rule) — nothing here is committed, per the repo's data policy.
