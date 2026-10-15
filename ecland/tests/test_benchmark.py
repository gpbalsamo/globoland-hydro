"""Synthetic tests for scripts/benchmark.py's interface.

No WFDE5 archive, ecLand executable, or CaMa-Flood run required -- these
exercise the pure decision logic (status/exit-code mapping, schema
validation, failure classification) and the benchmark.yaml profile
config directly, so they run in well under a second on a laptop.
"""
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import benchmark  # noqa: E402


def test_profiles_parse():
    profiles = benchmark.load_profiles()
    for name in ("fast", "smoke", "intermediate", "reference", "production"):
        assert name in profiles, f"missing profile: {name}"
    assert profiles["fast"]["allow_hpc"] is False
    assert profiles["production"]["allow_hpc"] is True


def test_compute_overall_pass():
    checks = {"python_syntax": "PASS", "bash_syntax": "PASS", "unit_tests": "PASS"}
    status, exit_code = benchmark.compute_overall(checks, implemented=True)
    assert status == "PASS"
    assert exit_code == 0


def test_compute_overall_fail():
    checks = {"python_syntax": "PASS", "bash_syntax": "FAIL"}
    status, exit_code = benchmark.compute_overall(checks, implemented=True)
    assert status == "FAIL"
    assert exit_code == 1


def test_compute_overall_not_implemented_even_if_checks_pass():
    # NOT_IMPLEMENTED must win regardless of what the attempted checks say --
    # a profile this repo can't run yet must never report a false PASS.
    checks = {"python_syntax": "PASS", "bash_syntax": "PASS"}
    status, exit_code = benchmark.compute_overall(checks, implemented=False)
    assert status == "NOT_IMPLEMENTED"
    assert exit_code == 2


def test_classify_failure_missing_data():
    assert benchmark.classify_failure("forcing_availability") == "MISSING_DATA"


def test_classify_failure_grid_error():
    assert benchmark.classify_failure("grid_consistency") == "GRID_ERROR"


def test_classify_failure_remap_conservation():
    assert benchmark.classify_failure("runoff_remap_conservation") == "REMAP_CONSERVATION_ERROR"


def test_classify_failure_unknown_defaults_safely():
    assert benchmark.classify_failure("some_future_check_nobody_classified_yet") == "UNKNOWN_ERROR"


def _minimal_valid_result():
    return benchmark.build_result(
        experiment="unit-test-experiment",
        profile="fast",
        status="PASS",
        exit_code=0,
        checks={"python_syntax": "PASS"},
        log_path="reports/x/benchmark.log",
        output_dir="reports/x",
        runtime_seconds=1.0,
        repository_commit="deadbeef",
    )


def test_validate_result_schema_valid():
    result = _minimal_valid_result()
    assert benchmark.validate_result_schema(result) == []


def test_validate_result_schema_missing_field():
    result = _minimal_valid_result()
    del result["status"]
    errors = benchmark.validate_result_schema(result)
    assert any("status" in e for e in errors)


def test_validate_result_schema_invalid_status():
    result = _minimal_valid_result()
    result["status"] = "MAYBE"
    errors = benchmark.validate_result_schema(result)
    assert any("invalid status" in e for e in errors)


def test_validate_result_schema_invalid_check_value():
    result = _minimal_valid_result()
    result["checks"]["python_syntax"] = "MOSTLY_PASS"
    errors = benchmark.validate_result_schema(result)
    assert any("invalid check result" in e for e in errors)


def test_build_result_has_all_required_fields():
    result = _minimal_valid_result()
    for field in benchmark.REQUIRED_RESULT_FIELDS:
        assert field in result


def test_benchmark_yaml_is_valid_yaml():
    with open(REPO_ROOT / "benchmark.yaml") as f:
        data = yaml.safe_load(f)
    assert "profiles" in data
