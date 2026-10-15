# Agent quickstart

Read this, `AGENTS.md`, and `PLAN.md` before touching anything else in this
repository. This file is kept short on purpose — a 7B local model should be
able to read all three cheaply. Everything here is a summary; when in doubt,
`PLAN.md`'s status labels are the source of truth, not this file's prose.

## What this repo does

Builds a **global** ecLand run driven by WFDE5_CRU_GPCC forcing, and prepares
its runoff for CaMa-Flood river routing. It generalises a validated regional
version of the same chain (`liaise-ecland`) — see `README.md`. It is Level 3
of a larger site→region→global→routing→benchmark cascade spanning several
sibling repositories (`README.md`, "Role in the ecLand benchmark cascade").

## Current status (check `PLAN.md` for the live version of this)

**Scaffolding and design only.** No WFDE5 data has been downloaded, no
ecLand run has been made in this repository, and no CaMa-Flood routing has
been run here. A few scripts have been ported unchanged from `liaise-ecland`
(Milestone 0) but not yet executed. Do not trust any claim that a stage
"works" unless `PLAN.md` marks it DONE.

## First safe command

```bash
python3 scripts/benchmark.py --profile fast
```

No download, no ecLand executable, no HPC needed. Runs in well under a
minute. It writes `reports/<experiment>/benchmark_result.json` and exits 0
(PASS) or 1 (FAIL). Do this before anything else, and again after any change,
to confirm the repository is still internally consistent.

## Main scripts (as of this writing — grep for new ones, this list will lag)

| Path | What it does | Status |
|---|---|---|
| `scripts/benchmark.py` | Deterministic benchmark CLI (this file's subject) | Gate 0 only implemented |
| `forcing/download_wfde5.py` | Global WFDE5 CDS retrieval + assembly | **Run for real**: one month, 1988-01 |
| `forcing/preprocess_wfde5.py` | WFDE5 -> ecLand `met_2DHT` forcing format | **Run for real**, used in the one-day pilot |
| `init_clim/build_global_surfclim_soilinit.sh` | Builds global `surfclim`/`soilinit` (ecland's own tooling) | **Run for real**, validated grid match |
| `run/run_ecland.sh` | Runs `ecland-master-dp` for a global window | **Run for real**: one-day global pilot, PASS |
| `run/check_run.py` | NaN/crash check on ecLand output | Real check, not yet a budget-closure check |
| `cama_flood/build_global_cmf_fixdir.sh` | Builds the global CaMa-Flood fix bundle | Ported, not yet run here |
| `cama_flood/aggregate_runoff_to_daily.py` | Hourly->daily runoff aggregation | Reference copy, LIAISE-specific, not generalised |

## Where configs live

- `config/wfde5.yaml` — WFDE5 CDS request settings
- `config/ecland.yaml` — grid/coupling/threading settings
- `config/paths.yaml` (gitignored, machine-specific) / `config/paths.example.yaml` (template)
- `benchmark.yaml` (repo root) — benchmark profiles (`fast`/`smoke`/`intermediate`/`reference`/`production`)

## How success is measured

By `scripts/benchmark.py`'s JSON output (`docs/benchmark_contract.md` has the
full schema), never by reading a wall of stdout. Key fields:

- `"status"`: `"PASS"` / `"FAIL"` / `"NOT_IMPLEMENTED"`
- `"checks"`: per-check `"PASS"` / `"FAIL"` / `"NOT_RUN"`
- `"error_code"` (only present when not PASS): one of a fixed vocabulary
  (`CONFIG_ERROR`, `MISSING_DATA`, `GRID_ERROR`, `UNIT_ERROR`, `BUILD_ERROR`,
  `RUNTIME_ERROR`, `NAN_ERROR`, `WATER_BALANCE_ERROR`,
  `REMAP_CONSERVATION_ERROR`, `CAMA_ERROR`, `UNKNOWN_ERROR`)
- `"log"`: path to the full log — read this, not stdout, for detail

The process exit code mirrors `"status"`: `0` PASS, `1` FAIL, `2`
NOT_IMPLEMENTED (the requested profile needs a stage that doesn't exist in
this repo yet — check `PLAN.md`, don't treat it as a bug to fix blindly).

## Where logs/results go

`reports/<experiment>/benchmark_result.json` plus a full log file at the path
its `"log"` field names. Gitignored — these are run artifacts, not something
to commit (see `.gitignore` and `CLAUDE.md`'s data policy).

## What not to do

See `AGENTS.md` for the full list. In short: don't run a `smoke`/
`intermediate`/`reference`/`production` benchmark profile, submit an HPC job,
or download real forcing data without asking first; don't claim a script
"works" because it exists; don't retry the same failing check more than
twice without stopping to report evidence; don't touch committed reference
data (`cama_flood/data/`, `tests/fixtures/`).
