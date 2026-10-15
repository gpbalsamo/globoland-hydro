#!/usr/bin/env python3
"""Deterministic benchmark CLI -- see docs/benchmark_contract.md.

Only Gate 0 (repository: Python/Bash syntax + synthetic tests) is actually
implemented. `smoke`/`intermediate`/`reference`/`production` report
status "NOT_IMPLEMENTED" rather than pretending to run a pipeline that does
not exist yet in this repository -- see PLAN.md Milestone 8's own note on
this. The functions below are split out and kept pure/side-effect-free
where possible so tests/test_benchmark.py can exercise them directly
without needing a real WFDE5 archive or ecLand executable.

Usage:
    python3 scripts/benchmark.py --profile fast
    python3 scripts/benchmark.py --profile smoke --experiment my-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - pyproject.toml declares pyyaml
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_STATUSES = ("PASS", "FAIL", "NOT_IMPLEMENTED")
VALID_CHECK_RESULTS = ("PASS", "FAIL", "NOT_RUN")

FAILURE_CODES = (
    "CONFIG_ERROR",
    "MISSING_DATA",
    "GRID_ERROR",
    "UNIT_ERROR",
    "BUILD_ERROR",
    "RUNTIME_ERROR",
    "NAN_ERROR",
    "WATER_BALANCE_ERROR",
    "REMAP_CONSERVATION_ERROR",
    "CAMA_ERROR",
    "UNKNOWN_ERROR",
)

# Maps a check name to the failure code it should report when it FAILs.
# Unmapped check names fall back to UNKNOWN_ERROR (see classify_failure) so
# a not-yet-classified check never crashes result generation.
_CHECK_FAILURE_CODES = {
    "python_syntax": "BUILD_ERROR",
    "bash_syntax": "BUILD_ERROR",
    "unit_tests": "RUNTIME_ERROR",
    "forcing_availability": "MISSING_DATA",
    "forcing": "MISSING_DATA",
    "grid_consistency": "GRID_ERROR",
    "grid": "GRID_ERROR",
    "units": "UNIT_ERROR",
    "water_balance": "WATER_BALANCE_ERROR",
    "energy_balance": "WATER_BALANCE_ERROR",
    "runoff_remap_conservation": "REMAP_CONSERVATION_ERROR",
    "runoff_remap": "REMAP_CONSERVATION_ERROR",
    "cama_flood": "CAMA_ERROR",
    "nan_check": "NAN_ERROR",
    "config": "CONFIG_ERROR",
}

REQUIRED_RESULT_FIELDS = (
    "stage",
    "experiment",
    "profile",
    "status",
    "exit_code",
    "repository_commit",
    "checks",
    "log",
    "output_dir",
)


def classify_failure(check_name: str) -> str:
    """Map a failing check's name to a fixed failure-code vocabulary entry."""
    return _CHECK_FAILURE_CODES.get(check_name, "UNKNOWN_ERROR")


def load_profiles(config_path: Path = REPO_ROOT / "benchmark.yaml") -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml is required to load benchmark.yaml")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data["profiles"]


def compute_overall(checks: dict[str, str], implemented: bool) -> tuple[str, int]:
    """Pure status/exit-code decision, given a completed checks dict.

    implemented=False means the requested profile has stages this repo does
    not implement yet, regardless of what checks[*] says -- always
    NOT_IMPLEMENTED/2 in that case, never a false PASS.
    """
    if not implemented:
        return "NOT_IMPLEMENTED", 2
    if any(v == "FAIL" for v in checks.values()):
        return "FAIL", 1
    return "PASS", 0


def run_python_syntax_check(repo_root: Path) -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(repo_root)],
        capture_output=True,
        text=True,
    )
    status = "PASS" if proc.returncode == 0 else "FAIL"
    return status, (proc.stdout + proc.stderr)


def run_bash_syntax_check(repo_root: Path) -> tuple[str, str]:
    scripts = sorted(repo_root.rglob("*.sh"))
    output_lines = []
    ok = True
    for script in scripts:
        proc = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True
        )
        if proc.returncode != 0:
            ok = False
            output_lines.append(f"{script}: {proc.stderr.strip()}")
    status = "PASS" if ok else "FAIL"
    return status, ("\n".join(output_lines) if output_lines else f"{len(scripts)} script(s) OK")


def run_unit_tests_check(repo_root: Path) -> tuple[str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    status = "PASS" if proc.returncode == 0 else "FAIL"
    return status, (proc.stdout + proc.stderr)


def run_gate0_checks(repo_root: Path) -> tuple[dict[str, str], str]:
    """Run the only gate actually implemented today. Returns (checks, log_text)."""
    checks = {}
    log_parts = []

    for name, fn in (
        ("python_syntax", run_python_syntax_check),
        ("bash_syntax", run_bash_syntax_check),
        ("unit_tests", run_unit_tests_check),
    ):
        status, detail = fn(repo_root)
        checks[name] = status
        log_parts.append(f"=== {name}: {status} ===\n{detail}\n")

    return checks, "\n".join(log_parts)


def build_result(
    *,
    experiment: str,
    profile: str,
    status: str,
    exit_code: int,
    checks: dict[str, str],
    log_path: str,
    output_dir: str,
    runtime_seconds: float,
    repository_commit: str,
    error_code: str | None = None,
    failure_reason: str | None = None,
    metrics: dict | None = None,
) -> dict:
    return {
        "stage": "global",
        "experiment": experiment,
        "profile": profile,
        "status": status,
        "exit_code": exit_code,
        "repository_commit": repository_commit,
        "ecland_commit": None,
        "forcing": None,
        "start_date": None,
        "end_date": None,
        "runtime_seconds": round(runtime_seconds, 3),
        "checks": checks,
        "metrics": metrics or {},
        "error_code": error_code,
        "failure_reason": failure_reason,
        "log": log_path,
        "output_dir": output_dir,
    }


def validate_result_schema(result: dict) -> list[str]:
    """Return a list of schema problems; empty list means valid."""
    errors = []
    for field in REQUIRED_RESULT_FIELDS:
        if field not in result:
            errors.append(f"missing required field: {field}")
    if "status" in result and result["status"] not in VALID_STATUSES:
        errors.append(f"invalid status: {result['status']!r}")
    if "checks" in result:
        for name, value in result["checks"].items():
            if value not in VALID_CHECK_RESULTS:
                errors.append(f"invalid check result for {name!r}: {value!r}")
    if result.get("error_code") is not None and result["error_code"] not in FAILURE_CODES:
        errors.append(f"invalid error_code: {result['error_code']!r}")
    return errors


def _git_commit(repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _print_progress(step: int, total: int, label: str, status: str) -> None:
    dots = "." * max(1, 24 - len(label))
    print(f"[{step}/{total}] {label} {dots} {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="wfde5-ecland deterministic benchmark CLI")
    parser.add_argument(
        "--profile",
        required=True,
        choices=["fast", "smoke", "intermediate", "reference", "production"],
    )
    parser.add_argument("--experiment", default=None, help="Experiment name (default: auto-timestamped)")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports"), help="Base directory for reports")
    args = parser.parse_args(argv)

    profiles = load_profiles()
    if args.profile not in profiles:
        print(f"Unknown profile: {args.profile}", file=sys.stderr)
        return 2

    experiment = args.experiment or f"wfde5-{args.profile}-{time.strftime('%Y%m%d-%H%M%S')}"
    output_dir = Path(args.output_dir) / experiment
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "benchmark.log"

    start = time.monotonic()

    if args.profile == "fast":
        checks, log_text = run_gate0_checks(REPO_ROOT)
        implemented = True
        error_code = None
        failure_reason = None
        status, exit_code = compute_overall(checks, implemented)
        if status == "FAIL":
            failing = [k for k, v in checks.items() if v == "FAIL"]
            error_code = classify_failure(failing[0])
            failure_reason = f"check(s) failed: {', '.join(failing)} -- see log"
    else:
        # Gates 1-5 (forcing/init/ecLand/CaMa interface/routing) are not
        # implemented in this repository yet -- see PLAN.md Milestones 1-5.
        # Still run Gate 0 so the result carries real signal about the repo
        # itself, but never claim PASS for a profile this repo can't run.
        checks, log_text = run_gate0_checks(REPO_ROOT)
        for name in ("forcing", "grid", "water_balance", "energy_balance", "runoff_remap"):
            checks[name] = "NOT_RUN"
        implemented = False
        status, exit_code = compute_overall(checks, implemented)
        error_code = None
        failure_reason = (
            f"profile '{args.profile}' requires Gates 1-5, not yet implemented "
            f"in this repository -- see PLAN.md Milestones 1-5"
        )

    runtime_seconds = time.monotonic() - start
    log_path.write_text(log_text)

    result = build_result(
        experiment=experiment,
        profile=args.profile,
        status=status,
        exit_code=exit_code,
        checks=checks,
        log_path=str(log_path.relative_to(REPO_ROOT)) if log_path.is_relative_to(REPO_ROOT) else str(log_path),
        output_dir=str(output_dir.relative_to(REPO_ROOT)) if output_dir.is_relative_to(REPO_ROOT) else str(output_dir),
        runtime_seconds=runtime_seconds,
        repository_commit=_git_commit(REPO_ROOT),
        error_code=error_code,
        failure_reason=failure_reason,
    )

    schema_errors = validate_result_schema(result)
    if schema_errors:
        # A schema bug in this script is itself a BUILD_ERROR, surfaced loudly
        # rather than silently writing an invalid JSON file.
        print("INTERNAL ERROR: benchmark_result.json failed its own schema:", file=sys.stderr)
        for e in schema_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    result_path = output_dir / "benchmark_result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n")

    total = len(checks)
    for i, (name, value) in enumerate(checks.items(), start=1):
        _print_progress(i, total, name, value)

    print(f"\nRESULT: {status}")
    print(f"JSON: {result_path.relative_to(REPO_ROOT) if result_path.is_relative_to(REPO_ROOT) else result_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
