#!/usr/bin/env python3
"""Compare LISFLOOD runoff with ecLand runoff on the shared 0.5 deg grid, for the same days.

Inputs
  products/runoff_05deg_<year>.nc            glofas/aggregate_runoff.py (trun, trun_box, cover)
  <ecland_repo>/run/output/Y<year>_*/o_wat.nc    ecLand Qs, Qsb

WHAT IS BEING COMPARED, AND WHAT IS NOT. Both models are driven by the SAME WFDE5-CRU-GPCC
precipitation and temperature, so this isolates model response rather than forcing -- that is the
whole point. It is not a controlled experiment in every other respect, and three differences are
real and are reported rather than smoothed over:

  * Evaporative demand. LISFLOOD takes ET0/E0/ES0 from LISVAP; ecLand computes evaporation from
    its own surface energy balance. LISVAP's ET0 runs ~20-24% below an independent FAO-56 estimate
    (run_lisvap.py prints both), so a LISFLOOD wet bias is expected a priori.
  * Land masks. ecLand's land mask and GloFAS's catchment map disagree cell by cell; `cover` says
    how much of each 0.5 deg cell is GloFAS land, and --min-cover screens on it. This is the same
    trap wfde5-ecland/cama_flood/validate_remapping.py exists to expose: a global mean over
    partially covered coastal cells silently mixes the two conventions.
  * Domain. GloFAS stops at 60S, so Antarctica is in ecLand's total and not in LISFLOOD's. The
    comparison is restricted to cells both models have, and the excluded ecLand volume is printed
    so it cannot be mistaken for a model difference.

ecLand runoff is -(Qs+Qsb) -- a SUM, not a difference; see wfde5-ecland/docs/cama_interface.md.
LISFLOOD total runoff (trun) is surface + upper zone + lower zone, its like-for-like partner.

Usage:
  python3 glofas/compare_runoff.py --year 1988 [--days 1] [--min-cover 0.9] [--json out.json]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import glofas  # noqa: E402

R_EARTH = 6371000.0
KM3 = 1.0e12            # kg of water per km3
SEC_PER_DAY = 86400.0


def cell_area(lat, res=0.5):
    hd = np.deg2rad(res) / 2
    belt = R_EARTH * R_EARTH * np.deg2rad(res) * (np.sin(np.deg2rad(lat) + hd) - np.sin(np.deg2rad(lat) - hd))
    return np.abs(belt)


def find_ecland(paths, year):
    base = Path(paths["ecland_repo"]) / "run" / "output"
    hits = sorted(base.glob(f"Y{year}_*/o_wat.nc"))
    if not hits:
        sys.exit(f"no ecLand output for {year} under {base} (looked for Y{year}_*/o_wat.nc)")
    return hits[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--days", type=int, default=None, help="first N days only")
    ap.add_argument("--min-cover", type=float, default=0.9,
                    help="require this GloFAS land fraction per 0.5 deg cell (default 0.9)")
    ap.add_argument("--product", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    paths = glofas.load_paths()
    prod = a.product or glofas.product(paths) / f"runoff_05deg_{a.year}.nc"
    if not prod.exists():
        sys.exit(f"{prod} missing -- run glofas/aggregate_runoff.py first")
    ecl = find_ecland(paths, a.year)

    with Dataset(prod) as g, Dataset(ecl) as e:
        lat = np.asarray(g["lat"][:], "f8")
        cover = np.ma.filled(g["cover"][:], 0.0)
        nt = min(len(g["time"]), len(e["time"]))
        nt = min(nt, a.days) if a.days else nt
        area = np.repeat(cell_area(lat)[:, None], len(g["lon"]), axis=1)

        gl_sum = np.zeros((len(lat), len(g["lon"])))
        ec_sum = np.zeros_like(gl_sum)
        for i in range(nt):
            gl = np.ma.filled(g["trun"][i], np.nan).astype("f8")           # mm/day per m2 of GloFAS land
            qs = np.nan_to_num(np.ma.filled(e["Qs"][i], np.nan).astype("f8"))
            qsb = np.nan_to_num(np.ma.filled(e["Qsb"][i], np.nan).astype("f8"))
            ec = -(qs + qsb) * SEC_PER_DAY                                 # kg m-2 day-1 == mm/day
            gl_sum += np.nan_to_num(gl)
            ec_sum += ec
            if i == 0:
                have_g = np.isfinite(gl)
        both = have_g & (cover >= a.min_cover) & (ec_sum != 0)
        res = {"year": a.year, "days": nt, "min_cover": a.min_cover,
               "cells_compared": int(both.sum()),
               "ecland_file": str(ecl), "product": str(prod)}

        print(f"{a.year}: {nt} days, comparing {int(both.sum())} cells "
              f"(GloFAS land fraction >= {a.min_cover})")
        print()
        vg = float((gl_sum[both] * area[both]).sum()) / KM3               # mm -> kg -> km3
        ve = float((ec_sum[both] * area[both]).sum()) / KM3
        print(f"  {'LISFLOOD total runoff':<34} {vg:10.1f} km3 over the period")
        print(f"  {'ecLand -(Qs+Qsb)':<34} {ve:10.1f} km3")
        print(f"  {'difference':<34} {vg - ve:10.1f} km3 = {100 * (vg - ve) / ve:+.2f}% of ecLand")
        res.update(lisflood_km3=vg, ecland_km3=ve, rel_diff=(vg - ve) / ve if ve else None)

        # what the restriction costs, so it cannot be mistaken for a model difference
        all_ec = float((ec_sum * area).sum()) / KM3
        south = (lat < -60.0)[:, None] & np.ones(gl_sum.shape, bool)
        print(f"  {'ecLand total, all cells':<34} {all_ec:10.1f} km3 "
              f"(excluded by the screen: {all_ec - ve:.1f}, of which {float((ec_sum[south] * area[south]).sum()) / KM3:.1f} south of 60S)")

        x, y = ec_sum[both], gl_sum[both]
        if x.size > 2:
            c = float(np.corrcoef(x, y)[0, 1])
            sl = float(np.polyfit(x, y, 1)[0])
            print()
            print(f"  {'per-cell correlation':<34} {c:10.4f}")
            print(f"  {'per-cell slope (LISFLOOD/ecLand)':<34} {sl:10.4f}")
            print(f"  {'mean |difference|':<34} {float(np.abs(y - x).mean()):10.4f} mm of "
                  f"{float(np.abs(x).mean()):.4f}")
            res.update(corr=c, slope=sl, mad=float(np.abs(y - x).mean()))

        print()
        print("  by latitude band (km3 over the period, cells passing the screen):")
        for lo, hi, nm in ((-60, -23, "S mid"), (-23, 23, "tropics"), (23, 60, "N mid"), (60, 90, "Arctic")):
            sel = both & ((lat >= lo) & (lat < hi))[:, None]
            if not sel.any():
                continue
            a_g = float((gl_sum[sel] * area[sel]).sum()) / KM3
            a_e = float((ec_sum[sel] * area[sel]).sum()) / KM3
            print(f"    {nm:<10} LISFLOOD {a_g:9.1f}   ecLand {a_e:9.1f}   "
                  f"{100 * (a_g - a_e) / a_e if a_e else float('nan'):+7.2f}%")
    if a.json:
        a.json.write_text(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
