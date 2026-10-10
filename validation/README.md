# validation/

Verification, not aspiration: every check here either passes against real
output or is marked NOT VERIFIED. Nothing in this directory should claim a
workflow step works because the code exists — see `CLAUDE.md`.

- `forcing/` — WFDE5 structural QC results.
- `runoff/` — conservation checks for the ecLand → CaMa-Flood transfer.
- `discharge/` — gauge-based skill scoring (KGE/NSE/correlation/PBIAS), reusing
  the formulas verified in `liaise-ecland/cama_flood/skill_benchmark_*.py`
  (checked there against the official CaMa-Flood package's own reference
  script) without reusing that repo's LIAISE-specific gauge set.
- `water_balance/` — global, area-weighted water-balance closure.

## Scripts

- `check_budgets.py` — global, area-weighted water and energy closure for one
  ecLand run. **Water closure VERIFIED; energy closure CANNOT BE PERFORMED.**
  The "VERIFIED against all 37 years of v2 and v4" label this entry used to
  carry was wrong: run on v4's 1989 the script prints `BUDGETS FAIL`, so it was
  never actually run over those 37 years with its result recorded. Measured
  2026-10-10 on v4 1988/1989/2000/2012/2024: water 0.057–0.491% of
  precipitation, all PASS — and **not** the 1.977–2.191% that PLAN.md's sweep
  tables report, which come from a script that is not in this repository.
  Energy is reported INCONCLUSIVE, not FAIL, because ecLand writes
  `DelSoilHeat` as identically zero over land (`min = max = 0` across 88,373
  land points × 365 records), so the sum is missing soil-heat storage and is
  not a closure; the leftover is a near-constant 3,202–3,583 EJ that straddles
  the 1% default tolerance. Only the water result gates exit status.
- `check_dam_commissioning.py` — proves CaMa's `LDAMYBY` stages dams in at
  their `DamYear`. **VERIFIED** 2026-10-08 against the v4/dams archive pair
  (PASS, exit 0). Its docstring records three obvious tests that do *not* work;
  read it before writing a fourth.
- `river_gauges.csv` — the gauge table. Its `obs_m3s` are approximate
  literature values for catching order-of-magnitude errors, **not** a GRDC
  extraction and not to be quoted as observations.
- `extract_gauges.py` — daily series at each gauge from one `o_totout.nc`, so a
  multi-year comparison does not need 100+ GB resident. **Always pass
  `--snap-from`** when comparing experiments: if each run snaps independently
  they can select different cells, and that shows up as a peak-attenuation
  signal that is really a cell mismatch.
- `check_cmf_restart_continuity.py` — detects CaMa-Flood's annual cold-start
  discontinuity. **VERIFIED both ways** 2026-10-10: FAIL, 38/38 gauge-years,
  exit 1 against the real v4 and dams archives; PASS, 0/19, exit 0 against a
  re-run with the restart chained (jobs 37007228/37007229). Its rigorous mode
  is also what `run_ecland.sh` runs inline after every coupled segment, where
  it reported `ratio = 1.001`. Rigorous mode compares a staged
  restart's global `rivsto` against the first output day; the cheap mode tests
  1 January discharge against the gauge's own annual median. Read its
  docstring on why "days to recover" is *not* the criterion — that column is
  confounded by seasonality and a long delay on the Lena is the real
  hydrograph.
- `compare_discharge.py` — dams-vs-control at the gauges. Its load-bearing
  check is the **annual mean**, not the peak: a reservoir redistributes water
  and consumes none here, so a mean that moves is a conservation failure. Only
  watching peaks is how the 24x `DROFUNIT` error survived two full archives.

## NEITHER archive's discharge is usable: CaMa cold-started every year

**Root cause found 2026-10-10. The previous version of this section blamed
CaMa's dam code path; that attribution is withdrawn.** CaMa's dam physics is
conservative. What was wrong is this repository's own run driver:
`run/run_ecland.sh` never staged a CaMa-Flood restart and the CaMa namelist
templates hardcode `LRESTART=false`, so **every annual segment of both
campaigns restarted CaMa from an empty river network**, while ecLand chained
correctly throughout.

Proof, in the archived output itself — 1 January 2000:

        Amazon        -369 m3/s   (annual median 140,553)
        Congo            7 m3/s   (annual median  39,324)
        Mississippi      0 m3/s   for nine consecutive days

Then the Amazon reaches 50,617 by day 30 and 148,247 by day 90. Confirmed
independently by the run's own `log_CaMa.txt-1` (`LRESTART  F`) and its
rendered `input_cmf.nam` (`LRESTART=false`, `CRESTSTO=""`).

Two consequences:

- **Both archives** discard the ~2,100 km3 of global river and floodplain
  storage standing at 31 December — 5.5% of global runoff, every year. This is
  exactly the control's previously unexplained 1,894 km3/yr deficit.
- **The dams archive additionally creates water.** `DAMOUT_INIT`'s
  `.not. LRESTART` branch sets `P2DAMSTO=ConVol` *and* `P2RIVSTO=ConVol` for
  every activated dam (`cmf_ctrl_damout_mod.F90:266-269`, ungated by
  `LiVnorm`), re-creating every reservoir's conservative volume each
  1 January: 3,425 km3 in 1988 rising to 4,185 km3 in 2024. Flat in time,
  concentrated on dammed rivers, not scaling with reservoir operation — the
  signature that was measured and could not be explained.

So: use neither archive for discharge, and do not treat v4 as the clean
reference it was described as here until it is re-run with
`CMF_RESTART_FROM` set.

**What does still hold.** The ecLand side of both archives is unaffected and
valid — the coupling is one-way and ecLand's own restart chaining was always
correct and verified. And v4's interannual *signal* is real where it was
checked: Zambezi-box precipitation falls 50% over the record and runoff 85%, so
the control's 97% discharge decline tracks its own input. Do not read "the
control looks too low" as evidence the control is broken — that inference was
made here and was wrong, twice.

The earlier Zambezi arithmetic that opened this investigation is still sound,
and is what led to the root cause:

        cumulative dams-minus-control at Tete, 2019-2024   467 km3
        total configured Zambezi reservoir capacity        264 km3
        annual excess                      70-83 km3/yr, FLAT (not decaying)

A reservoir releases its capacity once and a drawdown decays; a flat excess
larger than total capacity is a source. It just was not the source that was
assumed.

## Reading the dams archive: two further traps

**`rivdph` is meaningless at dam cells.** CaMa holds reservoir volume as
`rivsto` in the dam's own cell, so `rivdph = rivsto/(rivlen*rivwth)` reports a
"river depth" for a reservoir filling that cell — up to 468 m against a
control maximum of 10.7 m at the same cells. Measured on the 2024 CaMa
restart, 100% of differences above 10 m (and above 50, 100, 200, 400 m) fall on
dam cells, with **zero** spread into the network. This is a diagnostic that
does not apply, not an instability, and it is easy to confuse with the
run-of-river reservoir instability recorded under PLAN.md "Open blockers".
Exclude dam cells from any flood-depth or inundation analysis.

**ecLand output is byte-identical between the dams archive and v4.** With
`LECMF1WAY` the coupling is genuinely one-way: `restartout.nc` md5s match for
1988, 2000, 2012 and 2024, and so do `o_gg.nc`/`o_wat.nc`. So v4's validated
budgets apply to the dams archive by construction, there is no reason to run
an ecLand budget sweep over it, and only `cmf/` plus `restartout_cmf.nc`
carry the experiment. A future one-way CaMa experiment should skip ecLand
output entirely rather than duplicating ~30 GiB/year.
