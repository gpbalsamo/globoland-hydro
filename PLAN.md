# PLAN.md — wfde5-glofas

Status labels mean what they say: **DONE** = executed and its check passed; **NOT VERIFIED** =
ran but unchecked; **NOT STARTED** = no run. A script existing is never "done".

Created 2026-10-15 to run LISFLOOD globally on WFDE5 and **retain the runoff**, for comparison
with ecLand and for aiLand cross-training.

## Milestone 0 — scaffold

- [x] Repository generalised from `<exp>-glofas` — **DONE** 2026-10-15. A global run *removes*
      machinery: no `make_mask.py`, no `cut_inputs.py`, no `extract_forcing.py`, and none of the
      family's basin code (`contained_basins`, `last_in_box`, the 0.05 deg window slicing),
      because there is no clip. Verified that the operational settings are already global:
      `MaskMap = $(PathRoot)/template_Global_03min.nc`, `PathRoot -> assets/5.0/staticMaps`
      (a symlink), 6,221,926 land cells, `DtSec=86400`, `InitLisflood=0`, `repEndMaps=1`.
- [x] `work_dir` on `$SCRATCH`, not `$PERM` — **DONE**. A global year is ~45 GB of meteo plus
      ~25 GB of LISVAP output, so 37 years is ~2.6 TB. `$PERM` is 10 TB in total and hit that
      ceiling on 2026-10-15 (git could not write a 41-byte lock file).
- [x] Unit tests, no data needed — **DONE**, 6 passed. They cover the regridding algebra; the
      one claim that cannot be unit-tested (runoff options are output-only) is measured below.

## Milestone 1 — the 10:1 nesting, proved rather than assumed

- [x] **DONE** 2026-10-15. `common/glofas.nesting()` derives the alignment from the two
      coordinate vectors and refuses if it fails: WFDE5 rows 60..359 (lat -59.75..89.75), flipped,
      cover exactly 3000 GloFAS rows; 720 x 10 = 7200 columns.
- [x] Precipitation regridding is **exact and conservative** — **DONE**. Block replication, then
      measured on a real global day: area-weighted global total agrees to **4.6e-9** relative,
      max per-cell residual 3.7e-6 mm/day on a field reaching 123.2 mm/day (float32 storage
      rounding; every sub-cell is bit-identical to its parent in f8).
- [x] Bilinear regridding is **bounded** — **DONE**. Zero overshoot on either side of the coarse
      range (coarse [-57.699, 35.768] degC -> fine [-57.493, 35.737]), and it reproduces a coarse
      centre value to 4e-3 K.

## Milestone 2 — the pilot ladder (1 day -> 1 month -> 1 year)

### Rung 1: one global day — **DONE** 2026-10-15, every stage measured

| stage | wall | peak RSS | result |
|---|---|---|---|
| `prepare_meteo.py --days 1` | 25 s | **1.2 GB** | 7 variables, 123 MB; sane fields |
| `run_lisvap.py --days 1` | 58 s | **5.0 GB** | exit 0, e0/es/et written |
| `lisflood` (job 38653727) | 1255 s | **35.5 GB** | exit 0, `trun`/`srun`/`dis` written |
| `aggregate_runoff.py` | 5 s | — | 68,559 cells on the 0.5 deg grid |
| `compare_runoff.py` | 2 s | — | ran; see the caveat below |

**Memory was the open feasibility question and it is answered.** The global window is 21.6e6
cells against amazex's 417,600, a 52x jump, and no epilog in the family recorded MaxRSS. 35.5 GB
fits the `nf` QoS ceiling of 128 GB with room to spare. (A first submission at `--mem=200G` was
rejected with `QOSMaxMemoryPerJob`; the ceiling is 128 GB.)

Runoff output is present and internally consistent: `trun.nc` carries all 6,221,926 land cells
(mean 0.7028 mm/day, max 124.2), and `srun <= trun` everywhere, as surface ⊆ surface+UZ+LZ.

- [x] **The runoff options are output-only — MEASURED, not assumed.** This repository changes two
      operational options the six siblings forbid changing, on the premise that `rep*Maps` only
      control writing. Premise tested by running the same global day with and without them
      (`--no-runoff-maps`, job 38660999) and comparing the data:

          dis     bit-identical, 0 of 6,221,926 cells differ, max |d| 0.000e+00
          chanq.end, lz.end, uz.end   all bit-identical, max |d| 0.000e+00

      The end states matter as much as the discharge, because the 37-year chain propagates
      through them. NOTE: the *files* differ by md5 — NetCDF embeds creation time and the
      `PathOut` string — so a file checksum is the wrong test and was discarded for an array
      comparison.

- [ ] **The day-1 ecLand comparison is NOT a scientific result.** It ran, so the plumbing is
      proved, but the numbers are dominated by an initialisation mismatch: LISFLOOD is
      warm-started from the GloFAS reanalysis, while ecLand's Y1988 is the first year of its
      campaign. Measured in ecLand's own output:

          day 1   237.8 km3      day 10   95.7       day 45    99.4
          day 2   108.9          day 20  103.4       days 31-45 mean 109.9
          day 3   107.8          day 30   99.4       2001 annual mean 106.5 km3/day

      Day 1 is **2.16x** the following fortnight — a cold-start spike that decays within one day.
      The day-1 comparison (LISFLOOD 102.0 km3 vs ecLand 229.0, -55.5%, correlation 0.115)
      therefore measures that spike more than it measures either model. **This is what rung 2 is
      for.** Do not quote the -55%.

### Rung 2: one month — **NOT STARTED**
Needs 31 days of meteo (~13 min) and LISVAP (~30 min), then LISFLOOD. Expected LISFLOOD cost
~1.7 h: the two one-day runs (1255 s and 1023 s) bound the fixed initialisation at ~1000-1100 s,
and amazex's marginal rate (106,894 s / 13,514 days at 305,343 cells = 7.9 s/day, x20.4 for
6.22e6 cells = 161 s/day) gives 31 x 161 s on top.

### Rung 3: one year — **NOT STARTED**
~16.6 h of LISFLOOD by the same arithmetic (1094 + 365 x 161 s), inside the 24 h wall limit.

## Milestone 3 — the 37-year campaign — **NOT STARTED**

- Forcing (steps 1-3) is independent per year: a 37-way array, ~8.5 h each.
- **LISFLOOD is serial in time.** Year N+1 warm-starts from year N (`PathInit`/`repEndMaps`), so
  the campaign is ~16.6 h x 37 ≈ 25 days of wall clock. Cold-starting years to parallelise is
  forbidden: `wfde5-ecland` lost 37 segments of CaMa-Flood spin-up to exactly that, unnoticed,
  for weeks.
- Retention, as agreed: the 0.5 deg aggregate (~14 GB total) stays in `products/`; native 0.05 deg
  output goes to `ec:/pad/wfde5-glofas/<year>/` and is then deleted from `$SCRATCH`.

## Open questions

- **LISVAP ET0 is 19.5% below FAO-56** on the pilot day (2.139 vs 2.656 mm/d), consistent with the
  -22 to -24% `liaise-glofas` documented. A LISFLOOD wet bias relative to ecLand is expected a
  priori; it is not evidence about runoff physics and must not be reported as such.
- The two land masks disagree cell by cell; `cover` and `--min-cover` exist for that, and the
  day-1 screen at 0.9 kept 47,986 of 68,559 cells.
- aiLand cross-training consumes `products/runoff_05deg_<Y>.nc`. `ailand_v1`'s own roadmap already
  lists runoff as a target output, so the interface is a 0.5 deg daily field, not a new concept.
- No gauge observations here; the GloFAS reanalysis is the reference, not the truth.
