#!/usr/bin/env python3
"""Detect and measure CaMa-Flood's annual cold-start discontinuity.

Background
----------
Until 2026-10-10 ``run/run_ecland.sh`` never staged a CaMa-Flood restart, and
the CaMa namelist templates hardcode ``LRESTART=false``. ecLand chained
correctly via ``RESTART_FROM``, so every segment of both 37-year campaigns
looked healthy -- exit 0, output present, land-side budgets closed -- while
CaMa restarted from an EMPTY river network every 1 January. The failure is
silent; this script is the check that makes it loud.

Two modes, because the rigorous test needs ~1.5 GB of daily output per year and
the cheap one needs 120 kB:

``--restart R --first-output O``
    Rigorous. Global river storage in restart ``R`` (the previous segment's
    ``restartout_cmf.nc``) against the first daily record of ``O``
    (``o_rivsto.nc``). One day of global runoff is ~100 km3 against ~2,100 km3
    of standing storage, so a genuine continuation cannot move the total by
    anything like a factor two. This is the same test ``run_ecland.sh`` now runs
    inline after every coupled segment.

``--gauge-series S [S ...]``
    Cheap screen over already-extracted gauge series (``validation/
    extract_gauges.py`` output). The test is the 1 JANUARY discharge as a
    fraction of the gauge's own annual median. That ratio is the right metric
    because it is robust to seasonality: a continued run starts the year at its
    31 December value, and no real river falls to a per-cent of its annual
    median on 1 January -- the Congo, which has almost no seasonal cycle, came
    out of this archive at 7 m3/s against a 39,324 m3/s median.

    A "days to recover" column is reported alongside, but it is NOT the pass
    criterion and must not be read as a spin-up length: for snow-fed and
    monsoon rivers (Lena, Yenisei, Ob, Niger, Mekong, Nile) a long delay before
    half the annual median is the natural hydrograph, not an artefact. Only the
    1 January ratio separates the two.

    Use this to decide which months of an ALREADY-RUN archive are usable rather
    than re-running it.

Exit status: 0 continuous / within tolerance, 1 discontinuity detected,
2 usage or data error. Nonzero means the archive's early-year discharge is
spin-up, not simulation.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

KM3 = 1e-9


def _total_km3(a):
    a = np.ma.masked_invalid(np.ma.masked_greater(np.asarray(a, dtype="f8"), 1e19))
    return float(a.sum()) * KM3


def check_storage(restart, first_output, lo, hi):
    from netCDF4 import Dataset

    with Dataset(restart) as d:
        if "rivsto" not in d.variables:
            print(f"FAIL: {restart} has no 'rivsto'", file=sys.stderr)
            return 2
        staged = _total_km3(d["rivsto"][:])
    with Dataset(first_output) as d:
        if "rivsto" not in d.variables:
            print(f"FAIL: {first_output} has no 'rivsto'", file=sys.stderr)
            return 2
        first = _total_km3(d["rivsto"][0])

    print(f"  staged restart rivsto   = {staged:10.1f} km3   ({restart})")
    print(f"  first output day rivsto = {first:10.1f} km3   ({first_output})")
    if staged <= 0:
        print("FAIL: staged restart holds no river storage", file=sys.stderr)
        return 2
    ratio = first / staged
    print(f"  ratio = {ratio:.3f}   (continuous if {lo} < ratio < {hi})")
    if not lo < ratio < hi:
        print("FAIL: CaMa COLD-STARTED -- the first output day does not continue "
              "the staged restart. Check LRESTART/CRESTSTO in the rendered CaMa "
              "namelist, and CMF_RESTART_FROM in run/run_ecland.sh.")
        return 1
    print("PASS: CaMa river storage was carried across the segment boundary")
    return 0


def check_gauges(paths, frac, warn_days, min_day1):
    """1 January discharge as a fraction of the gauge's own annual median.

    Seasonality-robust (see module docstring): a continued run starts the year
    at its 31 December value. The days-to-recover column is diagnostic only --
    for a snow-fed river a long delay is the real hydrograph.
    """
    rows = []
    for p in paths:
        try:
            d = json.loads(Path(p).read_text())
            series = d["series"]
            label, year = d.get("label", "?"), d.get("year", "?")
        except Exception as exc:                      # noqa: BLE001
            print(f"FAIL: cannot read {p}: {exc}", file=sys.stderr)
            return 2
        for name, vals in sorted(series.items()):
            v = np.asarray(vals, dtype="f8")
            v = v[np.isfinite(v)]
            if v.size < 60:
                continue
            med = float(np.median(v))
            if med <= 0:
                continue                              # dry or sign-flipped gauge
            hit = np.nonzero(v >= frac * med)[0]
            day = int(hit[0]) + 1 if hit.size else v.size
            rows.append((label, year, name, float(v[0]) / med, day, med, float(v[0])))

    if not rows:
        print("FAIL: no usable gauge series found", file=sys.stderr)
        return 2

    print("  1 Jan discharge as a fraction of the gauge's own annual median")
    print(f"  (pass criterion: ratio >= {min_day1:.2f}. 'day' = first day reaching "
          f"{frac:.0%} of the median -- DIAGNOSTIC ONLY, confounded by seasonality)")
    print(f"  {'run':6s} {'year':>5s} {'gauge':18s} {'1Jan/med':>9s} "
          f"{'day':>4s} {'median m3/s':>12s} {'1 Jan m3/s':>11s}")
    bad = 0
    for label, year, name, ratio, day, med, d1 in sorted(rows, key=lambda r: r[3]):
        flag = ""
        if ratio < min_day1:
            flag = "  <-- cold start"
            bad += 1
        print(f"  {label:6s} {year:>5} {name:18s} {ratio:9.3f} "
              f"{day:>4d} {med:12.0f} {d1:11.0f}{flag}")

    print(f"\n  {bad} of {len(rows)} gauge-years start below {min_day1:.2f} "
          "of their own annual median")
    if bad:
        print("FAIL: CaMa started these years from an empty river network. The "
              "early part of each year is spin-up, not simulation. Check "
              "CMF_RESTART_FROM / LRESTART -- see run/run_ecland.sh.")
        return 1
    print("PASS: every gauge-year starts at a plausible fraction of its median")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restart", help="previous segment's restartout_cmf.nc")
    ap.add_argument("--first-output", help="this segment's o_rivsto.nc")
    ap.add_argument("--gauge-series", nargs="+", default=None,
                    help="extract_gauges.py JSON files (cheap archive screen)")
    ap.add_argument("--ratio-lo", type=float, default=0.5)
    ap.add_argument("--ratio-hi", type=float, default=2.0)
    ap.add_argument("--frac", type=float, default=0.5,
                    help="fraction of the annual median to reach (default 0.5)")
    ap.add_argument("--warn-days", type=int, default=10,
                    help="diagnostic column only; not the pass criterion")
    ap.add_argument("--min-day1", type=float, default=0.2,
                    help="fail if 1 Jan discharge is below this fraction of the "
                         "gauge's own annual median (default 0.2)")
    a = ap.parse_args()

    if a.restart and a.first_output:
        return check_storage(a.restart, a.first_output, a.ratio_lo, a.ratio_hi)
    if a.gauge_series:
        return check_gauges(a.gauge_series, a.frac, a.warn_days, a.min_day1)
    ap.error("give --restart with --first-output, or --gauge-series")


if __name__ == "__main__":
    sys.exit(main())
