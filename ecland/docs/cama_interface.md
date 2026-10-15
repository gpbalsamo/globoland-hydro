# ecLand → CaMa-Flood runoff interface

Status: **design document**, except for the conservation gate, which is
implemented: `cama_flood/validate_remapping.py` (2026-10-15). See `PLAN.md`
Milestone 4. The offline hand-off this document describes is not the
architecture in use -- the repo couples online, in memory -- but the remap
itself and its conservation requirement are identical either way, because
both paths use the same `inpmat.nc`.

## Pipeline

```
ecLand hourly Qs, Qsb  (kg m-2 s-1, on the 0.5 deg grid)
    |
    v
sign-correct + combine: total_runoff = -(Qs + Qsb)   <- see docs/forcing_variables.md
    |
    v
temporal aggregation (hourly -> whatever CaMa-Flood's coupling frequency needs)
    |
    v
convert rate -> volume per ecLand cell (multiply by interval seconds and cell area)
    |
    v
conservative area-weighted remap onto CaMa-Flood unit catchments
    |
    v
CaMa-Flood runoff forcing
```

## Why the sign correction is step one, not an afterthought

This is the single most consequential correctness issue found anywhere in
the `liaise-ecland` project's CaMa-Flood work. `Qsb` is a *signed*
soil-column-loss term in ecLand's own convention, not a plain positive flux
like `Qs`. The naive `Qs - Qsb` is dimensionally plausible, passes a
"discharge is non-negative" sanity check, and is *still wrong* — verified by
comparing against real Fortran-coupled discharge at multiple real gauges,
where `Qs - Qsb` matched to only ~2-3x the correct magnitude while
`-(Qs+Qsb)` matched to within 0.2-3%. See `docs/forcing_variables.md` for the
full account. `remap_runoff.py` must implement `-(Qs+Qsb)` from the start,
not discover this the way the reference project did.

**The mechanism, read out of ecLand's own writer** (`wrtdcdf.F90:799-815`,
confirmed 2026-09-27) — worth recording, because until now this repo only had
the empirical gauge comparison above, and a rule you cannot derive is a rule
someone will eventually "simplify":

    Qs  <-  D1STSRO2                 ! surface runoff,        >= 0
    Qsb <-  -D1STRO2 - D1STSRO2      ! -(total + surface),    <= 0

`D1STRO2` is **total** runoff and `D1STSRO2` is surface runoff — confirmed
independently by the coupling path, `cnt41s.F90:218-219`, which hands
CaMa-Flood `D1STSRO2` and `D1STRO2-D1STSRO2` as two channels that sum to
`D1STRO2`. Therefore

    Qs + Qsb = D1STSRO2 - D1STRO2 - D1STSRO2 = -D1STRO2 = -(total runoff)

The surface term cancels **by construction**, which is the whole reason the
correct combination is a sum and not a difference. Two consequences:

- `Qsb` is *not* subsurface runoff, despite its `long_name` saying
  "subsurface runoff". It is `-(total + surface)`. Do not use it alone as a
  drainage diagnostic.
- Both components are needed. `Qs` alone and `-Qsb` alone are each wrong, and
  `Qs - Qsb` double-counts surface runoff: on the validated 2001 year it gives
  64744 Gt against the correct 38890 Gt, **+66.5%**.

Sanity anchor for any future change: on 2001, `-(Qs+Qsb)` is 38890 Gt, i.e.
33.9% of precipitation, and the global water budget closes to 0.504%. A
runoff ratio far from ~1/3, or a budget residual that jumps, means the
combination was changed.

## Conservation is the acceptance criterion, not a nice-to-have

`aggregate_runoff_to_daily.py` (ported from `liaise-ecland`, see
`docs/migration_from_liaise.md`) was checked there to conserve volume to
1e-9 relative error — that is the bar for any temporal-aggregation step here
too. The area-weighted remap onto CaMa-Flood catchments must clear the same
bar: `validate_remapping.py` computes, for every tested period,

```
total ecLand runoff volume
total mapped CaMa-Flood input runoff volume
absolute difference
relative difference
```

and **fails** (nonzero exit) if the relative difference exceeds a
configurable tolerance. This check must exist and pass before any routing
run is trusted, and its numbers are reported, not just its pass/fail — a
near-precision-level residual and a residual just under the tolerance are
both "PASS" but are not the same finding.

**Measured, 2026-10-15, and the 1e-9 bar above is not attainable here.**
`inpa` is the *land* area of each source cell (median `inpa/(area x landsea)`
= 1.0011), so the comparison depends on which source area you use, and
`validate_remapping.py` makes that a flag rather than a hidden default. On
Y2001: 36,436.9 km3 produced against 35,207.8 km3 received = **3.373%** with
`--convention land`, and 38,581.5 against 35,207.8 = **8.744%** with
`--convention gridbox`. The residual is a coverage mismatch between two land
masks, not a leak: it is two-sided (1,951.5 km3 where CaMa's catchment is
smaller, 722.4 km3 where it is larger), and per cell the two disagree by far
more than the integral does (1st percentile of `inpa/source` 0.354, 99th
1.773). Antarctica is 98% of the unmapped *area* and 3% of the loss -- do not
read the area table without weighting by runoff. The default tolerance is
therefore 5%, not 1e-9, and the number is printed every time so drift shows.

## Weight generation, reused from liaise-ecland with the domain-clip removed

`derive_cmf_weights.sh`'s conservative remap-weight generation
(`gen_inpmat.py`, from the `ecland` repo's own `tools/create_forcing/`) runs
against whatever ecLand grid it's given; the LIAISE-specific step is the
domain clip that comes *before* it (`sel_region.py`, the `CLATN`/`CLATS`/
`CLONW`/`CLONE` box). For a global run there is no clip: the full global
CaMa-Flood network is the target. See `docs/migration_from_liaise.md` for the
two `ecland`-side source patches this machinery needed in the reference
project (a real memory-safety bug in `cnt41s.F90`, and an
out-of-bounds-pixel handling fix in `cython_ext.pyx`) — check whether a
global (non-clipped) run still exercises the same code paths that needed
those patches before assuming they're unnecessary here.

## Routing resolution is a CaMa-Flood-side choice, not a runoff-side one

See `docs/grid_strategy.md`. `build_global_cmf_fixdir.sh` already supports
building the global fix bundle at multiple resolutions
(`glb_15min`/`glb_06min`/`glb_03min`/`glb_01min`); which one to route at is
an independent decision from the ecLand runoff-generation grid, made after
Milestone 4's conservation check passes, informed by the kind of
resolution-comparison result documented in `liaise-ecland/PLAN.md`.
