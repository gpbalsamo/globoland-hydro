#!/usr/bin/env python3
"""Compare discharge between two experiments at the river gauges.

Built for dams-vs-naturalised-control, and it reports the three things a
reservoir is supposed to do, so that "the dams did something" is a measurement
rather than an impression:

  peak attenuation      annual maximum daily discharge should FALL
  low-flow augmentation annual minimum (and Q10) should RISE
  annual mean           should be nearly UNCHANGED

That third line is the most useful one, but read it carefully. A reservoir
redistributes water in time and consumes none here (LDAMOUT has no reservoir
evaporation and LWEVAP is off in both archives), so a moved annual mean needs
explaining. It is NOT by itself proof of non-conservation, and this script used
to claim that it was. Two innocent explanations come first:

  - CaMa's dam path also swaps the routing scheme. CMF_CALC_DAMOUT calls
    UPDATE_INFLOW, which replaces local-inertial outflow with a KINEMATIC-WAVE
    estimate at every cell whose downstream is a dam (I1DAM==10), explicitly
    "to suppress storage buffer effect" (Shin et al. 2019). The control never
    gets that treatment, so dams-vs-control conflates reservoir operation with
    a routing change -- and the routing change alone moves annual means in flat,
    heavily dammed basins.
  - A single cell is not a basin. Bifurcation (LPTHOUT) splits flow between
    channels, so one channel can gain while a parallel one loses.

So a moved mean is a flag to investigate, not a verdict. The real conservation
test is basin- or globe-integrated, and it must include bifurcation discharge:
`totout` is rivout+fldout and deliberately EXCLUDES pthout
(cmf_calc_stonxt_mod.F90:77), so a mouth-cell sum of totout under-counts ocean
outflow wherever LPTHOUT is on. Measured here: bifurcation carries
~4,300-4,500 km3/yr, against a residual of ~1,000-1,900, so omitting it is
enough on its own to fake a multi-percent "leak" in BOTH runs.

Also prints the control against the approximate observed means from
river_gauges.csv. Those are order-of-magnitude guards, not scores: see the
header of that file. Several listed rivers are heavily regulated in reality,
so a naturalised control SHOULD overshoot them -- Nile, Volga, Columbia and
Yangtze especially -- and the dams run should close part of that gap. That is
the one place these crude obs numbers carry real information, so the
direction of travel is reported for them.
"""
import argparse, csv, json, sys
from pathlib import Path

import numpy as np


def load(paths):
    series, years, cells = {}, [], {}
    for p in paths:
        d = json.loads(Path(p).read_text())
        years.append(d["year"])
        for k, v in d["series"].items():
            series.setdefault(k, {})[d["year"]] = np.asarray(v, dtype=float)
        for k, v in d.get("cells", {}).items():
            cells.setdefault(k, {})[d["year"]] = tuple(v)
    return series, sorted(years), cells


def cell_disagreements(*cellmaps):
    """Every file must read the SAME grid cell for a gauge, in both experiments.

    This is not a formality. extract_gauges.py snaps to the largest-discharge
    cell within a radius, so two extraction runs can legitimately choose
    different cells for the same gauge -- and then the comparison reports the
    difference between two *places* as a dam effect. That happened here:
    a driver script re-snapped per invocation, Orinoco and Amur ended up on
    different cells between year batches, and Amur's resulting +5.75% was
    briefly reported as a conservation failure. So this is a hard FAIL, not a
    warning: a contaminated gauge is worse than a missing one.
    """
    merged = {}
    for cm in cellmaps:
        for g, per_year in cm.items():
            merged.setdefault(g, set()).update(per_year.values())
    return {g: sorted(v) for g, v in merged.items() if len(v) > 1}


def obs_table(path):
    rows = [l for l in Path(path).read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("#")]
    return {r["name"]: (float(r["obs_m3s"]), r["station"])
            for r in csv.DictReader(rows)}


def stats(per_year, years):
    # Per-year statistics first, then averaged across years: a single pooled
    # series would let one extreme year dominate the "annual maximum".
    mean, mx, mn, q10 = [], [], [], []
    for y in years:
        s = per_year.get(y)
        if s is None or not np.isfinite(s).any():
            continue
        s = s[np.isfinite(s)]
        mean.append(s.mean()); mx.append(s.max())
        mn.append(s.min());    q10.append(np.percentile(s, 10))
    if not mean:
        return None
    return dict(mean=float(np.mean(mean)), peak=float(np.mean(mx)),
                low=float(np.mean(mn)), q10=float(np.mean(q10)), n=len(mean))


def pct(new, old):
    return float("nan") if old == 0 else 100.0 * (new - old) / old


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--control", nargs="+", required=True, help="control .json files")
    p.add_argument("--experiment", nargs="+", required=True, help="experiment .json files")
    p.add_argument("--gauges", required=True, help="river_gauges.csv")
    p.add_argument("--allow-cell-mismatch", action="store_true",
                   help="drop gauges whose cell differs between input files "
                        "instead of failing (default: fail)")
    p.add_argument("--mean-tol", type=float, default=5.0,
                   help="percent change in annual mean that is treated as a "
                        "conservation problem rather than a dam signal (default 5)")
    a = p.parse_args()

    C, cy, cc = load(a.control)
    E, ey, ec = load(a.experiment)
    bad_cells = cell_disagreements(cc, ec)
    if bad_cells and not a.allow_cell_mismatch:
        print("FAIL: the same gauge was read from different grid cells, so any "
              "difference reported for it would be between two PLACES, not "
              "between the two experiments:", file=sys.stderr)
        for g, v in bad_cells.items():
            print(f"  {g}: cells {v}", file=sys.stderr)
        print("Re-extract every year against one fixed --snap-from reference, "
              "or pass --allow-cell-mismatch to drop these gauges and continue.",
              file=sys.stderr)
        return 2
    if bad_cells:
        print(f"WARNING: dropping {len(bad_cells)} gauge(s) read from "
              f"inconsistent cells: {', '.join(sorted(bad_cells))}\n")
        for g in bad_cells:
            C.pop(g, None); E.pop(g, None)
    if cy != ey:
        print(f"WARNING: year sets differ -- control {cy[0]}-{cy[-1]} "
              f"({len(cy)}), experiment {ey[0]}-{ey[-1]} ({len(ey)})")
    years = sorted(set(cy) & set(ey))
    if not years:
        print("FAIL: no overlapping years", file=sys.stderr)
        return 2
    obs = obs_table(a.gauges)
    print(f"{len(years)} common years: {years[0]}-{years[-1]}\n")

    hdr = (f"{'river':14s} {'ctl mean':>10s} {'exp mean':>10s} {'dmean%':>7s} "
           f"{'dpeak%':>7s} {'dQ10%':>7s} {'dmin%':>7s}  {'ctl/obs':>7s}")
    print(hdr); print("-" * len(hdr))
    flagged, rows = [], []
    for name in sorted(set(C) & set(E)):
        c, e = stats(C[name], years), stats(E[name], years)
        if not c or not e:
            continue
        dm = pct(e["mean"], c["mean"])
        o = obs.get(name, (float("nan"), ""))[0]
        rows.append((name, c, e, dm, o))
        print(f"{name:14s} {c['mean']:10,.0f} {e['mean']:10,.0f} {dm:7.2f} "
              f"{pct(e['peak'], c['peak']):7.2f} {pct(e['q10'], c['q10']):7.2f} "
              f"{pct(e['low'], c['low']):7.2f}  "
              f"{(100*c['mean']/o if o else float('nan')):6.0f}%")
        if abs(dm) > a.mean_tol:
            flagged.append((name, dm))

    if not rows:
        print("FAIL: no gauge present in both experiments", file=sys.stderr)
        return 2

    att = [pct(e["peak"], c["peak"]) for _, c, e, _, _ in rows]
    aug = [pct(e["q10"], c["q10"]) for _, c, e, _, _ in rows]
    dmn = [pct(e["mean"], c["mean"]) for _, c, e, _, _ in rows]
    print(f"\nacross {len(rows)} gauges, median change:")
    print(f"  annual peak : {np.median(att):+6.2f}%   (reservoirs should attenuate)")
    print(f"  Q10         : {np.median(aug):+6.2f}%   (reservoirs should augment)")
    print(f"  annual mean : {np.median(dmn):+6.2f}%   (should be ~0)")

    # Where the crude obs numbers do carry signal: heavily regulated rivers.
    reg = [r for r in rows if r[0] in
           ("Nile", "Volga", "Columbia", "Yangtze", "Parana", "Mississippi")]
    if reg:
        print("\nheavily-regulated rivers -- does the dams run move toward obs?")
        for name, c, e, _, o in reg:
            if not o:
                continue
            bc, be = abs(c["mean"] - o), abs(e["mean"] - o)
            verdict = "closer" if be < bc else ("further" if be > bc else "same")
            print(f"  {name:14s} obs {o:8,.0f}  ctl {c['mean']:8,.0f} -> "
                  f"exp {e['mean']:8,.0f}   {verdict}")

    if flagged:
        print(f"\nINVESTIGATE: annual mean moved more than {a.mean_tol}% at "
              f"{len(flagged)} gauge(s). A reservoir redistributes water rather "
              f"than creating it, so each of these needs an explanation -- but "
              f"this is NOT by itself a conservation failure (see the module "
              f"docstring: the dam path also swaps in kinematic-wave routing "
              f"upstream of dams, and bifurcation splits flow between "
              f"channels).")
        for n, d in flagged:
            print(f"  {n}: {d:+.2f}%")
        print("\nTo test conservation properly, integrate over river mouths "
              "AND include pthflw -- totout excludes it.")
        return 1
    print(f"\nPASS: annual means preserved within {a.mean_tol}% at every gauge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
