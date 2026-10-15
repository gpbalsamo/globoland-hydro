#!/usr/bin/env python3
"""Pull daily discharge time series at the river gauges out of one o_totout.nc.

Exists so a multi-year comparison does not need the full archive on disk at
once: each CaMa discharge file is ~1.5 GB/year, so 37 years x 2 experiments is
~111 GB, while the extracted series are a few kB. Retrieve one year, extract,
delete, repeat.

Snapping: the gauge coordinates in river_gauges.csv are downstream sites, and
the nearest cell of a 15-min network is often not the river -- it can be a
neighbouring tributary or a coastal cell. So this takes the LARGEST-discharge
cell within --snap-deg and reports how far it moved and what the nearest-cell
value would have been. A snap that jumps the full search radius, or multiplies
the discharge several-fold, means the coordinate is wrong and the number is
measuring a different river. That is printed, not hidden.

IMPORTANT: pass --snap-from for the experiment comparison. Both experiments
must read the SAME cell, or a peak-attenuation signal is confounded with the
two runs snapping to different cells. Snap once on the control, write the
resulting indices to a file, and reuse them for every other run.
"""
import argparse, csv, json, sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def read_gauges(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rows.append(line)
    for r in csv.DictReader(rows):
        yield r


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--discharge", required=True, help="o_totout.nc for one year")
    p.add_argument("--gauges", required=True, help="river_gauges.csv")
    p.add_argument("--out", required=True, help="output .json of daily series")
    p.add_argument("--label", required=True, help="experiment label, e.g. dams or v4")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--snap-deg", type=float, default=1.5,
                   help="search radius for the river cell (default 1.5)")
    p.add_argument("--snap-from", default=None,
                   help="reuse cell indices from this earlier --out file "
                        "(REQUIRED for comparing experiments)")
    a = p.parse_args()

    ds = Dataset(a.discharge)
    name = next(k for k in ds.variables if k not in ds.dimensions)
    # 1e20 is CaMa's fill value. np.asarray() here would strip the mask and
    # average fill into the series -- that mistake has been made in this repo.
    q = np.ma.masked_greater(ds[name][:], 1e19)
    lat = np.asarray(ds["lat"][:]) if "lat" in ds.variables else None
    lon = np.asarray(ds["lon"][:]) if "lon" in ds.variables else None
    if lat is None or lon is None:
        print("FAIL: discharge file has no lat/lon; cannot locate gauges",
              file=sys.stderr)
        return 2

    fixed = {}
    if a.snap_from:
        fixed = {k: tuple(v) for k, v in
                 json.loads(Path(a.snap_from).read_text())["cells"].items()}

    qmean = q.mean(axis=0)
    out = {"label": a.label, "year": a.year, "variable": name,
           "file": str(a.discharge), "cells": {}, "series": {}}

    print(f"{a.label} {a.year}: variable {name}, {q.shape[0]} steps, "
          f"grid {q.shape[-2]}x{q.shape[-1]}")
    for g in read_gauges(a.gauges):
        glon, glat = float(g["lon"]), float(g["lat"])
        if g["name"] in fixed:
            iy, ix = fixed[g["name"]]
            moved = None
        else:
            jy = np.argsort(np.abs(lat - glat))
            jx = np.argsort(np.abs(lon - glon))
            wy = jy[:max(1, int(a.snap_deg / abs(lat[1] - lat[0])) + 1)]
            wx = jx[:max(1, int(a.snap_deg / abs(lon[1] - lon[0])) + 1)]
            sub = qmean[np.ix_(wy, wx)]
            if sub.count() == 0:
                print(f"  {g['name']:14s} NO VALID CELL within {a.snap_deg} deg")
                continue
            k = np.unravel_index(np.ma.argmax(sub), sub.shape)
            iy, ix = int(wy[k[0]]), int(wx[k[1]])
            near = qmean[jy[0], jx[0]]
            moved = (float(np.hypot(lat[iy] - glat, lon[ix] - glon)),
                     float(near) if near is not np.ma.masked else float("nan"))
        s = q[:, iy, ix]
        if s.count() == 0:
            print(f"  {g['name']:14s} SNAPPED CELL IS MASKED")
            continue
        out["cells"][g["name"]] = (iy, ix)
        out["series"][g["name"]] = [float(v) for v in s.filled(np.nan)]
        msg = f"  {g['name']:14s} mean {float(s.mean()):10,.0f} m3/s"
        if moved is not None:
            msg += f"   snapped {moved[0]:.2f} deg"
            if np.isfinite(moved[1]) and moved[1] > 0:
                msg += f" (nearest cell would be {moved[1]:,.0f}, "
                msg += f"x{float(s.mean())/moved[1]:.1f})"
            if moved[0] > 0.9 * a.snap_deg:
                msg += "  <-- HIT SEARCH LIMIT, coordinate suspect"
        print(msg)
    ds.close()
    Path(a.out).write_text(json.dumps(out))
    print(f"  wrote {a.out} ({len(out['series'])} gauges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
