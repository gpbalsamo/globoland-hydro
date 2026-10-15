# Grid strategy: two grids, not one

This is a project invariant (also stated in `CLAUDE.md`), because it is the
single easiest thing for an agentic or human contributor to get wrong by
"helpfully" simplifying:

```
WFDE5 / ecLand runoff-generation grid   (0.5 degree, global)
                ↓  conservative runoff transfer
CaMa-Flood routing / unit-catchment grid  (e.g. 3 arcmin)
```

**Do not interpolate WFDE5 to the CaMa-Flood routing grid and treat that as
additional hydrological information.** Fine river-routing resolution does not
create fine meteorological information. A 3 arcmin CaMa-Flood network resolves
channel geometry and unit catchments far more precisely than a 0.5° runoff
field can justify; the runoff feeding every unit catchment inside one 0.5°
ecLand cell is, correctly, the same value, area-weighted by each catchment's
share of that cell — not independently varying.

## Why this matters concretely

`liaise-ecland` ran the *same* ecLand runoff through CaMa-Flood at three
routing resolutions (15/6/3 arcmin) and found 6 arcmin scored measurably
better against real gauges than 15 arcmin (median KGE 0.005 → 0.120, NSE
crossing from failing to beating climatology). That is a genuine, measured
routing-resolution effect — better channel/catchment delineation improving
how the *same* water is routed. It is not evidence that finer routing
resolution should be paired with finer runoff-generation resolution; the
runoff input was identical across all three routing resolutions by
construction, and that is exactly what let the comparison isolate the
routing effect. See `liaise-ecland/PLAN.md`, "CaMa-Flood resolution
comparison", for the full result.

## What "the exact ecLand grid" means in practice

`surfclim`, `soilinit`, and the ecLand forcing files must all describe
**exactly** the same grid — not merely the same nominal resolution. Silent
mismatches to guard against:

- `(lat, lon)` vs `(lon, lat)` axis order
- a flattened/reduced-Gaussian point representation vs. a regular lat/lon grid
- ascending vs. descending latitude
- longitude convention (−180..180 vs. 0..360)
- a land mask that doesn't agree cell-for-cell between `surfclim` and the
  forcing grid

`init_clim/init_clim.py` (ported from `liaise-ecland`, see
`docs/migration_from_liaise.md`) already supports both a flattened
representation (`gen_file`) and a regular grid (`gen_file_LL`) — the risk is
not that the tooling can't handle either, it's silently mixing them.
`init_clim/validate_init_grid.py` exists specifically to make this an
explicit, automated check rather than a trusted assumption, comparing the
forcing grid, `surfclim` grid, and `soilinit` grid pairwise and returning
PASS only when they agree exactly.
