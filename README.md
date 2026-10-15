# wfde5-glofas

GloFAS v5 (LISFLOOD 5.0.0, operational configuration) run **globally**, forced by the **same
WFDE5_CRU_GPCC forcing** as the sibling [`wfde5-ecland`](../wfde5-ecland), **retaining LISFLOOD's
runoff** so that it can be compared with ecLand's and used to cross-train aiLand.

```text
Model:    LISFLOOD 5.0.0 (module lisflood/5.0.0), GloFAS v5 operational settings:
          calibrated parameters, water use, lakes, reservoirs, MCT routing -- all ON
Grid:     GloFAS 0.05 deg (3 arcmin) global, 3000 x 7200, 6,221,926 land cells, 90N..60S
Forcing:  WFDE5-CRU-GPCC 0.5 deg hourly -> daily 0.05 deg, ET0/E0/ES0 from LISVAP 1.4.2
Initial:  GloFAS reanalysis states valid 01/01/1988 00:00, then chained year to year
Retained: trun (total runoff = surface + upper zone + lower zone), srun (surface runoff), dis
Product:  runoff aggregated to ecLand's 0.5 deg grid -- ~14 GB for 1988-2024, kept permanently
```

## Why this is a separate repository, not a seventh `<exp>-glofas`

The six `<exp>-glofas` repositories (amazex, calife, mekrex, murrex, portex, reprex) are regional
and share byte-identical code; their `AGENTS.md` forbids changing operational options "beyond
paths/mask/dates/discharge maps". This repository does change two more --
`repTotalRunoffMaps` and `repSurfaceRunoffMaps` -- because retaining runoff is its entire purpose.
It is also global, which removes machinery rather than adding it: there is no mask rule, no domain
clip, no `make_mask.py` and no `cut_inputs.py`, because the operational `MaskMap` and static maps
already are global and are used in place, read-only.

`scripts/compare_siblings.sh` therefore does not apply here, and this repository is deliberately
not kept identical to the six.

## Pipeline

| # | Step | Output (on `$SCRATCH`) |
|---|---|---|
| 1 | `glofas/prepare_meteo.py` | `meteo/glofas_{tp,ta,tx,tn,pd,ws,rg}_<Y>.nc` (0.05 deg daily) |
| 2 | `glofas/run_lisvap.py` | `lisvap_out/<Y>/{e0,es,et}.nc` |
| 3 | `glofas/link_forcing.sh` | `forcing_lisflood/glofas_{tp,ta,e0,eS0,eT0}_<Y>.nc` |
| 1-3 | `glofas/build_forcing.py` | the three above, idempotent, one year at a time |
| 4 | `glofas/make_settings.py` + `glofas/run_lisflood.slurm` | `runs/<tag>/out/{trun,srun,dis}.nc` |
| 5 | `glofas/aggregate_runoff.py` | `products/runoff_05deg_<Y>.nc` (0.5 deg, **kept**) |
| 6 | `glofas/compare_runoff.py` | LISFLOOD vs ecLand on the shared grid |

`work_dir` is on `$SCRATCH` by design: a global 0.05 deg year is ~45 GB of meteo plus ~25 GB of
LISVAP output, so 37 years would be ~2.6 TB. `$PERM` is 10 TB in total and shared with everything
else, and it hit that ceiling on 2026-10-15. Only the 0.5 deg product and the reports live with
the repository.

## Measured cost (not estimated)

| stage | one global day | per year | peak RSS |
|---|---|---|---|
| `prepare_meteo.py` | 25 s | ~2.5 h | 1.2 GB |
| `run_lisvap.py` | 58 s | ~6 h | 5.0 GB |
| `lisflood` | 1255 s (incl. init) | see `PLAN.md` | **35.5 GB** |

Memory, not wall time, was the open feasibility question: the global window is 21.6e6 cells
against amazex's 417,600. 35.5 GB fits the `nf` QoS ceiling of 128 GB with room to spare.

Steps 1-3 are independent per year and can run as a 37-way array. **LISFLOOD itself is serial in
time**, because each year warm-starts from the previous year's end states (`repEndMaps=1`,
`PathInit`). Cold-starting each year independently would be faster and wrong -- `wfde5-ecland`
already lost 37 segments of CaMa-Flood spin-up to exactly that mistake without noticing.

## Status

See `PLAN.md`. Nothing here is claimed to work because a script exists; each step records what was
actually run and measured.

## Quick start

```bash
python3 -m pytest tests/ -q                                     # no data needed
python3 glofas/prepare_meteo.py --years 1988 1988 --days 1       # one global day
/usr/local/apps/lisflood/5.0.0/lisflood-env/bin/python glofas/run_lisvap.py 1988 --days 1
./glofas/link_forcing.sh /ec/res4/scratch/pad/wfde5-glofas 1988
python3 glofas/make_settings.py --tag pilot1d --start "02/01/1988 00:00" --end "02/01/1988 00:00"
sbatch glofas/run_lisflood.slurm pilot1d                        # approval required
python3 glofas/aggregate_runoff.py --tag pilot1d --year 1988
python3 glofas/compare_runoff.py --year 1988 --days 1
```
