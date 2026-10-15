#!/usr/bin/env python3
"""Minimal "did this actually run" check for an ecLand output directory
(run/run_ecland.sh's ${OUTPUT_DIR}/${STA}/) -- see run/README.md.

Checks, in order (any failure is reported, first failure sets the exit code):
  1. run.log exists and does not contain a Fortran abort/floating-point-
     exception trace (a real run can still produce output files right up to
     the point it crashed -- see PLAN.md Milestone 3's 2026-09-19 note on
     the WFDE5-ocean-placeholder crash this caught).
  2. restartout.nc exists (the model reached its final timestep and wrote
     restart state -- a partial/crashed run does not produce this).
  3. Every o_*.nc file has no NaN/Inf in any variable. 1e20 is ecLand's own
     fill value for masked (ocean) points and is NOT flagged.

This is deliberately minimal -- NOT a water/energy budget closure check
(that is Milestone 3's separate, still-NOT-STARTED check_water_budget.py/
check_energy_budget.py, per run/README.md).

Usage:
    python3 run/check_run.py --output-dir run/output/GLOBAL_19880101-19880102
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

FORTRAN_ABORT_MARKERS = (
    "forrtl: error",
    "Floating point exception",
    "ECLAND FAILED EXECUTION",
    "Caught signal",
)
FILL_VALUE = 1.0e20
FILL_ATOL = 1.0e10  # generous: only meant to exclude ecLand's own ~1e20 fill marker


def check_run_log(output_dir: Path) -> list[str]:
    errors = []
    log_path = output_dir / "run.log"
    if not log_path.is_file():
        return [f"missing run.log: {log_path}"]
    text = log_path.read_text(errors="replace")
    for marker in FORTRAN_ABORT_MARKERS:
        if marker in text:
            errors.append(f"run.log contains abort marker: {marker!r}")
    return errors


def check_restart_exists(output_dir: Path) -> list[str]:
    if not (output_dir / "restartout.nc").is_file():
        return [f"missing restartout.nc in {output_dir} -- run did not reach its final timestep"]
    return []


def _count_bad_slice(data: np.ndarray) -> tuple[int, int]:
    """NaN/Inf counts for one slice, ignoring ecLand's own fill value."""
    finite_mask = ~np.isclose(data, FILL_VALUE, atol=FILL_ATOL, rtol=0.0)
    n_nan = int(np.count_nonzero(np.isnan(data) & finite_mask))
    n_inf = int(np.count_nonzero(np.isinf(data) & finite_mask))
    return n_nan, n_inf


def check_no_nan_inf(output_dir: Path) -> list[str]:
    errors = []
    o_files = sorted(output_dir.glob("o_*.nc"))
    if not o_files:
        return [f"no o_*.nc output files found in {output_dir}"]
    for path in o_files:
        with Dataset(path) as ds:
            for name, var in ds.variables.items():
                if var.ndim < 2:
                    continue
                # Stream along the first (time) dimension rather than
                # materialising the whole variable: a month of global 0.5
                # degree output is tens of GB per file, and loading one
                # variable whole (plus a float64 upcast and a boolean-mask
                # copy) got this script OOM-killed against the real
                # 1988-01 coupled run. Keep peak memory to one slice.
                n_nan = n_inf = 0
                for i in range(var.shape[0]):
                    n_bad = _count_bad_slice(np.ma.filled(var[i], FILL_VALUE))
                    n_nan += n_bad[0]
                    n_inf += n_bad[1]
                    if n_nan or n_inf:
                        break  # one bad value is enough to fail; stop reading
                if n_nan or n_inf:
                    errors.append(f"{path.name}:{name}: {n_nan} NaN, {n_inf} Inf (excluding fill value)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.output_dir.is_dir():
        print(f"FAIL: output dir does not exist: {args.output_dir}")
        return 1

    errors = []
    errors += check_run_log(args.output_dir)
    errors += check_restart_exists(args.output_dir)
    errors += check_no_nan_inf(args.output_dir)

    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"PASS: {args.output_dir} -- run.log clean, restartout.nc present, no NaN/Inf in any o_*.nc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
