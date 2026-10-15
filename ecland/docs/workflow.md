# Workflow

```
WFDE5_CRU_GPCC hourly forcing (global, 0.5 deg)
        |
        v
forcing acquisition / QC / unit conversion      (forcing/)
        |
        v
ecLand global simulation                        (run/, using init_clim/'s
        |                                         surfclim + soilinit)
        v
surface + subsurface runoff (Qs, Qsb)
        |
        v
conservative mapping to CaMa-Flood              (cama_flood/)
        |
        v
CaMa-Flood river/floodplain routing
        |
        v
discharge / storage / flood diagnostics and benchmarking   (validation/)
```

Each stage has a corresponding validation step (`validation/`), and none is
considered trustworthy until its own check has actually been run against
real output and passed — see `CLAUDE.md`.

## Stage-by-stage status

| Stage | Directory | Status |
|---|---|---|
| Forcing acquisition/QC | `forcing/` | not started |
| ecLand climatology/init | `init_clim/` | not started |
| ecLand run | `run/` | not started |
| Runoff → CaMa-Flood | `cama_flood/` | not started |
| Validation | `validation/` | not started |

See `PLAN.md` for the milestone breakdown and `docs/migration_from_liaise.md`
for what each stage reuses from the reference project and why.

## Two grids, one pipeline

See `docs/grid_strategy.md`: the ecLand runoff-generation grid (0.5°, matching
WFDE5's native resolution) and the CaMa-Flood routing grid (potentially much
finer) are deliberately different concepts. The pipeline above has exactly
one point where that distinction is bridged — "conservative mapping to
CaMa-Flood" — and that step's correctness (conservation, sign convention) is
this project's single most important validation target. See
`docs/cama_interface.md`.
