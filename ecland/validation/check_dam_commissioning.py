#!/usr/bin/env python3
"""Prove CaMa-Flood's year-by-year dam commissioning (LDAMYBY) actually engaged.

Three obvious tests DO NOT WORK, and each one looks convincing:

1. "damsto > 0 at a dam cell means the dam is active."
   False. CMF_DAMOUT_WATBAL (cmf_ctrl_damout_mod.F90) advances P2DAMSTO for
   EVERY in-domain dam, DamStat==-1 included, integrating inflow minus the
   *natural* outflow; and DAMOUT_INIT seeds an un-built dam's storage to
   rivsto+fldsto. An un-built dam therefore shows nonzero, growing storage by
   design. Counting "active cells" this way returns ~every dam in every year
   whether commissioning works or not.

2. "allocated dams << number of dams means dams were dropped."
   False under MPI. CaMa logs per region (log_CaMa.txt-<rank>) and NDAMX is
   that rank's share. Sum across ranks before concluding anything -- for this
   configuration the 16 regions sum to exactly 3697, a clean partition.

3. "the dams run differs from the control at a dam cell, so that dam regulates."
   False. Dams sit on a river network; a cell downstream of a commissioned dam
   differs without being regulated itself. In the 1988 segment this flags 78%
   of the not-yet-built dams.

What DOES work is the asymmetry, and then a before/after on it.
CMF_CALC_DAMOUT cycles on DamStat<=0, so an un-built dam leaves D2RIVOUT at its
natural value. Against the naturalised control (identical forcing and ecLand --
dams the only difference) you cannot get bit-identical annual-mean discharge at
a cell whose dam is actively regulating it. So:

  - cells with DamYear <= early  must ALL differ from the control  (regulated)
  - cells with DamYear >  early  include some bit-identical ones   (inert)
  - those same bit-identical cells must ALL differ by `late`, once their
    DamYear has passed.

The last line is the decisive one: it is the only test here that a broken
LDAMYBY cannot pass. Measured for 1988 -> 2020: 148 cells bit-identical in
1988, 0 of them still identical in 2020, DamYear range 1989-2017.

Caveats this check deliberately surfaces rather than hides:
  - DamYear <= 0 (GRanD missing, 107 cells here) falls through DAMOUT_INIT's
    `DamYear > 0` guard to DamStat=2, i.e. present for the whole record. Those
    cells are excluded from both groups and reported separately.
  - ISYYYY is the SIMULATION START year, read once in DAMOUT_INIT. Commissioning
    is therefore only correct because the campaign is chained one calendar year
    per segment; a single multi-year segment would freeze every dam at its
    start-year status.
"""
import argparse, csv, sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

# A bit-identical annual mean is the signal, so the tolerance is roundoff, not
# a physical threshold. Anything larger would start absorbing real regulation.
EPS = 1e-10


def annual_mean(path):
    ds = Dataset(path)
    name = next(k for k in ds.variables if k not in ds.dimensions)
    # 1e20 is CaMa's fill; np.asarray would strip the mask and average it in.
    a = np.ma.masked_greater(ds[name][:], 1e19).mean(axis=0)
    ds.close()
    return name, a


def read_dams(path):
    # dam_params.csv is CaMa's own format: a bare count line, then a header.
    lines = Path(path).read_text().splitlines()
    return list(csv.DictReader(lines[1:]))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dams", required=True, help="dam_params.csv used by the run")
    p.add_argument("--early-dams", required=True, help="o_totout.nc, dams run, early year")
    p.add_argument("--early-ctl", required=True, help="o_totout.nc, control, same early year")
    p.add_argument("--late-dams", required=True, help="o_totout.nc, dams run, late year")
    p.add_argument("--late-ctl", required=True, help="o_totout.nc, control, same late year")
    p.add_argument("--early-year", type=int, required=True)
    p.add_argument("--late-year", type=int, required=True)
    a = p.parse_args()

    if a.late_year <= a.early_year:
        p.error("--late-year must be after --early-year")

    name, E = annual_mean(a.early_dams)
    _, Ec = annual_mean(a.early_ctl)
    _, L = annual_mean(a.late_dams)
    _, Lc = annual_mean(a.late_ctl)
    if not (E.shape == Ec.shape == L.shape == Lc.shape):
        print("FAIL: discharge grids differ between runs/years", file=sys.stderr)
        return 2
    ny, nx = E.shape
    print(f"variable {name}, grid {ny}x{nx}")

    built, notyet, nodate, offgrid, masked = [], [], 0, 0, 0
    for r in read_dams(a.dams):
        ix, iy = int(float(r["DamIX"])) - 1, int(float(r["DamIY"])) - 1
        dy = int(float(r["DamYear"]))
        if dy <= 0:
            nodate += 1
            continue
        if not (0 <= ix < nx and 0 <= iy < ny):
            offgrid += 1
            continue
        if any(v is np.ma.masked for v in (E[iy, ix], Ec[iy, ix], L[iy, ix], Lc[iy, ix])):
            masked += 1
            continue
        rec = (dy,
               abs(float(E[iy, ix]) - float(Ec[iy, ix])),
               abs(float(L[iy, ix]) - float(Lc[iy, ix])),
               r["DamName"])
        (built if dy <= a.early_year else notyet).append(rec)

    print(f"  DamYear <= 0 (always-on by default) : {nodate}")
    print(f"  dam cells off the routing grid      : {offgrid}")
    print(f"  dam cells masked in the output      : {masked}")

    for label, grp in ((f"DamYear <= {a.early_year}", built),
                       (f"DamYear >  {a.early_year}", notyet)):
        if not grp:
            print(f"\n{label}: no cells")
            continue
        d_e = np.array([g[1] for g in grp])
        d_l = np.array([g[2] for g in grp])
        print(f"\n{label}:  {len(grp)} cells")
        print(f"  identical to control in {a.early_year} : {int((d_e <= EPS).sum())}")
        print(f"  identical to control in {a.late_year} : {int((d_l <= EPS).sum())}")

    inert = [g for g in notyet if g[1] <= EPS]
    still = [g for g in inert if g[2] <= EPS]
    print(f"\n=== decisive set: not built in {a.early_year} AND bit-identical then ===")
    print(f"  cells                      : {len(inert)}")
    print(f"  still identical in {a.late_year}    : {len(still)}   <-- must be 0")
    if inert:
        print(f"  DamYear range              : "
              f"{min(g[0] for g in inert)}-{max(g[0] for g in inert)}")
        print(f"  mean |dQ| in {a.late_year}          : "
              f"{np.array([g[2] for g in inert]).mean():.4g} m3/s")

    fails = []
    if not inert:
        # Either commissioning is broken, or every un-built dam happens to sit
        # downstream of a commissioned one. Both need a human look.
        fails.append(f"no provably-inert dam cell in {a.early_year}; "
                     "cannot distinguish staged commissioning from all-on")
    if still:
        fails.append(f"{len(still)} dam(s) never switched on by {a.late_year}: "
                     + ", ".join(g[3] for g in still[:5]))
    if built and int((np.array([g[1] for g in built]) <= EPS).sum()):
        n = int((np.array([g[1] for g in built]) <= EPS).sum())
        fails.append(f"{n} dam(s) built by {a.early_year} left discharge untouched")

    if fails:
        print("\nFAIL")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"\nPASS: dams commission in their DamYear and not before "
          f"({len(inert)} cells inert in {a.early_year}, all active by {a.late_year})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
