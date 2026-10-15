# namelist/

ecLand namelist templates for a global configuration.

Status: **`templates/namelist_ecland_50R1_ctl` DONE, ported unchanged and
already used in a real run** (`PLAN.md` Milestone 3, 2026-09-19). Not
`liaise-ecland`'s own namelist pattern — this is ecland's own official
`{}`-placeholder template
(`/perm/pad/ecland/namelists/namelist_ecland_50R1_ctl`, ecland VERSION
2.0.0), the same one its own currently-shipped
`tests/2D_EU-001_20220101-20220102` test case uses. `run/run_ecland.sh`
calls ecland's own `share/ecland/scripts/ecland_create_namelist.py` to
render `{nstart}`/`{nstop}`/`{nlat}`/`{nlon}`/etc. from the actual
forcing/surfclim files at run time — nothing here is hand-patched.

`liaise-ecland`'s CaMa-Flood coupling namelist pattern (`TCOUPFREQ`-derived
`IFRQ_INP`/`DROFUNIT`/`DT` relationship, the `CMPIREGNC`-required-even-for-
a-single-process-run gotcha) is still relevant once CaMa-Flood coupling is
turned on (Milestone 4/5) — see `docs/migration_from_liaise.md` — but that
namelist doesn't exist here yet.

`global/` will hold per-experiment namelists as pilots extend beyond one day.
