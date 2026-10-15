# CLAUDE.md

Guidance for Claude Code and any other coding agent. Read `AGENTS.md` first, then `PLAN.md`
(status). This is the **global, runoff-retaining** instance of the `<exp>-glofas` family.

## What this is

LISFLOOD 5.0.0 run as **GloFAS v5** (calibrated parameters, water use, lakes, reservoirs and MCT
routing ON, as operationally) over the **whole global 0.05 deg river network**, with **WFDE5**
forcing instead of the operational meteo, warm-started from the reanalysis states valid
01/01/1988 00:00, and **retaining total and surface runoff**.

It is an **independent hydrological model run**, not a router for ecLand runoff. The comparison
with `wfde5-ecland` is GloFAS-on-WFDE5 against ecLand-CaMa-Flood-on-WFDE5, both from the same
precipitation and temperature.

## The single most important rule, inherited from wfde5-ecland

**Never claim a step is working merely because the script exists.** A step is working when it has
been executed successfully and its check passed. `PLAN.md`'s labels exist to make that distinction
impossible to paper over.

## Invariants

1. **Grid direction.** The GloFAS 0.05 deg grid nests exactly 10x10 inside the WFDE5/ecLand 0.5
   deg grid; `common/glofas.nesting()` proves it from the coordinate vectors and refuses if it
   ever stops holding. Precipitation is regridded by **block replication**, which is exact and
   conservative (verified: 4.6e-9 relative on the area-weighted global total); everything else is
   separable bilinear, which is bounded by the coarse field (verified: zero overshoot).
2. **Aggregate up, never interpolate down.** LISFLOOD runoff is aggregated to 0.5 deg for the
   comparison. Interpolating ecLand's 0.5 deg runoff down to 0.05 deg and treating the result as
   hydrological information is forbidden -- the same scientific-validity invariant as
   `wfde5-ecland/docs/grid_strategy.md`, not a style preference.
3. **Day convention.** The step stamped D+1 00:00 holds day D, for meteo, LISFLOOD output and the
   reanalysis alike. WFDE5 hourly fluxes are means stamped at the END of their hour.
4. **Operational configuration.** Only the paths, dates, `repDischargeMaps` and the two runoff map
   options change. The runoff options are output-only; that is checked, not assumed (`PLAN.md`).
5. **Warm-start chain.** Year N+1's `PathInit` is year N's `PathOut` (`repEndMaps=1`). LISFLOOD is
   therefore serial in time. Do not cold-start years to parallelise.
6. **Two area conventions, both reported.** `aggregate_runoff.py` writes runoff per m2 of GloFAS
   land AND per m2 of the 0.5 deg box, plus the per-cell `cover` fraction. Picking one silently is
   how `wfde5-ecland` hid a 3,400 km3/yr remap term for weeks.
7. **`work_dir` is never on `$PERM`.** See `AGENTS.md`.

## Known limitations

- **LISVAP ET0 is low.** Measured here on one global day: 2.139 mm/d against an independent
  FAO-56 estimate of 2.656 (**-19.5%**), consistent with the -22 to -24% `liaise-glofas`
  documented every year. A LISFLOOD wet bias relative to ecLand is therefore expected a priori
  and is not evidence about either model's runoff physics.
- **The two land masks disagree cell by cell.** ecLand's mask and the GloFAS catchment map differ,
  badly on coasts. `compare_runoff.py` screens on `cover` and prints what the screen excluded.
- **GloFAS stops at 60S**, so Antarctica is in ecLand's totals and not in LISFLOOD's.
- **The reanalysis is calibrated to the operational meteo**, so a WFDE5-forced run is expected to
  trail it at calibration stations.
- No gauge observations here yet: the reanalysis is the reference, not the truth.

## Sources

- `<exp>-glofas` (amazex/calife/...) -- the pipeline this generalises; regional, no runoff output.
- `/perm/pad/liaise-glofas/lisflood/` -- the original LIAISE/Ebro pipeline behind those.
- `wfde5-ecland` -- the sibling ecLand-CaMa-Flood chain and the shared WFDE5 archive.
