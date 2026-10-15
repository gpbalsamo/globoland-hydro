# AGENTS.md

Short operating contract for ANY coding agent working in this repository —
Claude Code, OpenCode, a local Ollama model (`qwen2.5-coder:7b` or similar),
or a future cross-repo orchestrator. Deliberately short so a small local
model can load it cheaply. For the fuller lab-notebook history and detailed
scientific rules, see `CLAUDE.md`; for a longer walkthrough of this repo,
see `docs/agent_quickstart.md`.

## Purpose

This repo is the **global** stage (Level 3) of the ecLand benchmark cascade
— see `README.md`'s "Role in the ecLand benchmark cascade". It builds a
WFDE5-forced global ecLand run and prepares its runoff for CaMa-Flood.

## Fast entrypoint

Run this first, always:

```bash
python3 scripts/benchmark.py --profile fast
```

It requires no downloaded data and no ecLand executable. It runs Python/Bash
syntax checks and the synthetic test suite, then writes
`reports/<experiment>/benchmark_result.json` and exits 0 (PASS), 1 (FAIL), or
2 (NOT_IMPLEMENTED — see below).

## Pass criteria

Success is determined by the JSON result file's `"status"` field
(`PASS`/`FAIL`/`NOT_IMPLEMENTED`) and the process exit code, **not** by
reading prose output. See `docs/benchmark_contract.md` for the full schema
and the Gate 0-5 definitions. Do not decide "close enough" yourself where a
script computes a numeric threshold (e.g. water-balance error %) — that
threshold is the deterministic pass/fail authority, not your judgement.

## Safe commands (no approval needed)

- `git status`, `git diff`, `git log`
- Reading/searching any file in the repo
- `python3 -m compileall .`, `bash -n <script>.sh`
- `python3 scripts/benchmark.py --profile fast`
- `pytest tests/`
- `python3 forcing/validate_wfde5.py --help` (or any script's `--help`)
- `scripts/publish_site.sh ... --dry-run` (prints the command, uploads nothing)

## Requires human approval first

- Anything beyond `--profile fast`: `smoke`/`intermediate`/`reference`/
  `production` (multi-day to multi-decade runs)
- Any `sbatch`/SLURM submission or other HPC job launch
- Any download of real WFDE5/CaMa-Flood data (CDS quota, large transfers)
- Any `scripts/publish_site.sh` invocation without `--dry-run` — it
  publishes to the public https://sites.ecmwf.int/pad/wfde5/ site, visible
  to others, same approval bar as a real data download
- Editing `ecland` source code outside the current, explicitly-scoped task

## Forbidden

- `git reset --hard`, `git clean -fd`, force-push
- Deleting or overwriting `tests/fixtures/`, `cama_flood/data/`, or any
  other committed reference/observation data
- Committing credentials, CDS API keys, or machine-specific paths (see
  `.gitignore` and `CLAUDE.md`'s data policy)
- Launching a multi-decade global run without the staged day→month→year
  pilot passing first (`README.md` "Pilot strategy", `PLAN.md` Milestone 3)
- Claiming a workflow step "works" because its script exists rather than
  because it ran and its checks passed (`CLAUDE.md`'s single most important
  rule)

## Escalation rule

If the same check fails twice after two reasonable, targeted fixes: **stop**.
Summarize what was tried and what the evidence shows (the JSON result and
its `log` file are the evidence), and ask for human or higher-capability
review rather than continuing to retry. Do not loop.
