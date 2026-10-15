# Benchmark contract

Defines the machine-readable result format and pass/fail gates that
`scripts/benchmark.py` implements (or, honestly, does not yet implement —
see "Current implementation status" at the bottom). This is the contract a
future cross-repo orchestrator or a local coding agent should rely on
instead of parsing prose logs.

## Gates

Each gate must PASS before the next is attempted. `scripts/benchmark.py`
never proceeds past a failed gate to a more expensive one.

**GATE 0 — repository/software**
- Python syntax PASS (`python -m compileall .`)
- Bash syntax PASS (`bash -n` on every `*.sh`)
- Synthetic tests PASS (`pytest tests/`, no real data required)

**GATE 1 — forcing**
- Time axis valid (matches the declared forcing convention, see
  `docs/forcing_variables.md`)
- Grid valid (dimensions, coordinates, ordering, longitude convention)
- Units valid
- Missing-value check PASS

**GATE 2 — initialization**
- forcing/`surfclim`/`soilinit` grid relationship PASS (see
  `docs/grid_strategy.md`)
- No unexplained axis reversal
- No unintended flattening/reordering

**GATE 3 — ecLand**
- Executable exits 0
- Mandatory outputs exist
- No NaNs in required variables
- Water-balance tolerance PASS
- Energy sanity checks PASS

**GATE 4 — CaMa interface**
- Runoff sign verified (`total_runoff = -(Qs+Qsb)`, see
  `docs/cama_interface.md`)
- Area conversion verified
- Volume-conservation check PASS

**GATE 5 — routing**
- CaMa-Flood exits successfully
- Expected Q/storage outputs exist

## JSON result schema

One `benchmark_result.json` per experiment run, written to
`reports/<experiment>/benchmark_result.json`.

```json
{
  "stage": "global",
  "experiment": "wfde5-fast-20260917-101500",
  "profile": "fast",
  "status": "PASS",
  "exit_code": 0,
  "repository_commit": "e3395e6...",
  "ecland_commit": null,
  "forcing": null,
  "start_date": null,
  "end_date": null,
  "runtime_seconds": 4.2,
  "checks": {
    "python_syntax": "PASS",
    "bash_syntax": "PASS",
    "unit_tests": "PASS",
    "forcing": "NOT_RUN",
    "grid": "NOT_RUN",
    "water_balance": "NOT_RUN",
    "energy_balance": "NOT_RUN",
    "runoff_remap": "NOT_RUN"
  },
  "metrics": {},
  "error_code": null,
  "failure_reason": null,
  "log": "reports/wfde5-fast-20260917-101500/benchmark.log",
  "output_dir": "reports/wfde5-fast-20260917-101500"
}
```

Required fields: `stage`, `experiment`, `profile`, `status`, `exit_code`,
`repository_commit`, `checks`, `log`, `output_dir`. All others may be `null`
or `{}` when not applicable — never omitted (a consumer should not need to
distinguish "missing key" from "not applicable").

`status` is one of `PASS`, `FAIL`, `NOT_IMPLEMENTED`. `checks[*]` is one of
`PASS`, `FAIL`, `NOT_RUN`. Never put a stack trace in this file — point
`log` at the full log instead.

## Failure classification

When `status != PASS`, `error_code` is one of:

`CONFIG_ERROR`, `MISSING_DATA`, `GRID_ERROR`, `UNIT_ERROR`, `BUILD_ERROR`,
`RUNTIME_ERROR`, `NAN_ERROR`, `WATER_BALANCE_ERROR`,
`REMAP_CONSERVATION_ERROR`, `CAMA_ERROR`, `UNKNOWN_ERROR`

`scripts/benchmark.py`'s `classify_failure()` maps known check names to
these codes; anything unmapped falls back to `UNKNOWN_ERROR` rather than
raising, so the JSON is always produced even for a check nobody has
classified yet.

## Benchmark profiles

Defined in `benchmark.yaml` (repo root):

| Profile | Scope | HPC | Confirmation |
|---|---|---|---|
| `fast` | Gate 0 only: syntax + synthetic tests | never | not needed |
| `smoke` | + Gate 1-5 for 1 day, global | never | not needed |
| `intermediate` | 1 month, global | never | required |
| `reference` | 1 year, global | never | required |
| `production` | multi-year/decadal, global | allowed | required |

A local agent should default to `fast` or `smoke` and never invoke
`production` on its own initiative — see `AGENTS.md`.

## Design principle: agents orchestrate, code decides

The agent (human, Claude, or a small local model) chooses which command to
run next and interprets a `FAIL`/`NOT_IMPLEMENTED` result. It must never
itself decide "the water balance looks close enough" — every PASS/FAIL in
`checks` comes from a deterministic, configurable numeric threshold in the
underlying validation code (see `docs/cama_interface.md`'s conservation
tolerance for the pattern to follow when Gate 4 is actually implemented).

## Current implementation status

**Only Gate 0 is real.** `scripts/benchmark.py --profile fast` runs Python
syntax, Bash syntax, and `pytest tests/` (all synthetic, no WFDE5 archive or
ecLand executable needed) and reports a genuine PASS/FAIL. `smoke`,
`intermediate`, `reference`, and `production` all report `status:
"NOT_IMPLEMENTED"` (exit code 2) — Gates 1-5 depend on Milestones 1-5 in
`PLAN.md`, none of which are done yet. Do not read the existence of this
document, `benchmark.yaml`, or the CLI as evidence that those gates work —
see `CLAUDE.md`'s single most important rule.
