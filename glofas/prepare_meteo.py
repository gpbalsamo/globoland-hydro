#!/usr/bin/env python3
"""Daily LISFLOOD meteo on the GLOBAL GloFAS 0.05 deg grid, from the same WFDE5-CRU-GPCC ecLand uses.

Generalises <exp>-glofas/glofas/prepare_meteo.py to the whole globe. The conventions are that
script's, kept deliberately verbatim because each one silently changes the answer:

* Day D = the 24 hourly records stamped D 01:00 .. D+1 00:00 (WFDE5 fluxes are means stamped at
  the END of their hour), and LISFLOOD finds day D at the step stamped D+1 00:00.
* tp [mm/day] = sum (Rainf+Snowf)*3600; ta [degC] mean Tair; tx/tn [K] max/min Tair;
  pd [hPa] mean actual vapour pressure e = q p / (0.622 + 0.378 q); ws [m/s] mean Wind;
  rg [W m-2] mean SWdown.
* Sea (masked) cells are filled from the nearest land cell BEFORE regridding, because the
  deltas sit on coasts.
* 0.5 -> 0.05 deg: the grids are edge-aligned 10:1, so nearest == block replication == exact and
  conservative for precipitation; everything else is bilinear.
* No lapse-rate/elevation correction (WFDE5 is already elevation-corrected to its own orography).

WHAT IS DIFFERENT HERE, and why it had to be:

  The regional script holds a whole year of hourly fields in memory and regrids a year at a time.
  On a 72x144 window that is nothing; globally it is 8784 x 360 x 720 x 8 B = 18.2 GB PER VARIABLE
  (127 GB for the seven) and a 365 x 3000 x 7200 f4 output array is another 31.5 GB per variable.
  So this version streams: it reads 24 records, forms that day's seven fields, regrids them and
  appends the day to seven yearly files. Peak memory is a few hundred MB regardless of year length.

  There is no window and no mask: the operational global MaskMap and static maps are used as they
  are, so prepare_meteo has no mask_global.nc to read its target grid from and takes it from the
  operational MaskMap itself (common/glofas.mask_map).

Usage:
  python3 glofas/prepare_meteo.py --years 1988 1988              # one whole year
  python3 glofas/prepare_meteo.py --years 1988 1988 --days 1     # pilot: first day only
"""
import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, date2num
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import glofas  # noqa: E402

# name -> (units, regrid method). tp MUST stay "block": it is a rate and block replication is the
# only one of the two that conserves it.
VARS = {"tp": ("mm/day", "block"), "ta": ("degC", "bilinear"), "tx": ("K", "bilinear"),
        "tn": ("K", "bilinear"), "pd": ("hPa", "bilinear"), "ws": ("m/s", "bilinear"),
        "rg": ("W m-2", "bilinear")}
SRC = ("Tair", "Rainf", "Snowf", "Qair", "PSurf", "Wind", "SWdown")


def src_file(paths, y):
    return Path(paths["wfde5_global_dir"]) / paths["wfde5_global_pattern"].format(year=y)


def sea_fill_index(valid):
    """Index map carrying each cell the nearest valid (land) cell, computed once per year."""
    idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return idx[0], idx[1]


def day_fields(h):
    """h: dict of (24, nlat, nlon) hourly arrays -> the seven daily LISFLOOD fields."""
    e = h["Qair"] * h["PSurf"] / (0.622 + 0.378 * h["Qair"])
    return {"tp": (h["Rainf"] + h["Snowf"]).sum(0) * 3600.0,
            "ta": h["Tair"].mean(0) - 273.15,
            "tx": h["Tair"].max(0), "tn": h["Tair"].min(0),
            "pd": e.mean(0) / 100.0,
            "ws": h["Wind"].mean(0), "rg": h["SWdown"].mean(0)}


def open_out(path, var, latg, long_, y, nd):
    """Create one yearly output file with an unlimited time axis, ready to be appended to."""
    tmp = Path(str(path) + ".partial")
    o = Dataset(tmp, "w")
    o.createDimension("time", None); o.createDimension("lat", len(latg)); o.createDimension("lon", len(long_))
    t = o.createVariable("time", "f8", ("time",))
    t.units = "days since 1970-01-01 00:00:00"; t.calendar = "proleptic_gregorian"
    la = o.createVariable("lat", "f8", ("lat",)); la.units = "degrees_north"; la[:] = latg
    lo = o.createVariable("lon", "f8", ("lon",)); lo.units = "degrees_east"; lo[:] = long_
    v = o.createVariable(var, "f4", ("time", "lat", "lon"), zlib=True, complevel=4,
                         fill_value=np.float32(-9999.0), chunksizes=(1, len(latg), len(long_)))
    v.units = VARS[var][0]
    o.source = ("WFDE5-CRU-GPCC global hourly (wfde5-ecland forcing/), daily, "
                "regridded to the global GloFAS 0.05 deg grid")
    o.regrid = f"{VARS[var][1]} (block = exact 10x10 replication, conservative)"
    o.day_convention = "step stamped D+1 00:00 holds the 24 h ending at that time (day D)"
    return o, tmp


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs=2, required=True, metavar=("START", "END"))
    ap.add_argument("--days", type=int, default=None, help="stop after N days (pilot runs)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    paths = glofas.load_paths(); w = glofas.work(paths)
    out_dir = w / "meteo"; out_dir.mkdir(parents=True, exist_ok=True)
    latg, long_ = glofas.glofas_grid(paths)

    for y in range(a.years[0], a.years[1] + 1):
        t0 = time.time()
        with Dataset(src_file(paths, y)) as s:
            latw = np.asarray(s["lat"][:], "f8"); lonw = np.asarray(s["lon"][:], "f8")
            rows, flip = glofas.nesting(latw, lonw, latg, long_)
            nt = len(s["time"])
            nd_full = nt // 24
            if nd_full * 24 != nt:
                sys.exit(f"{y}: {nt} hourly records is not a whole number of days")
            nd = min(nd_full, a.days) if a.days else nd_full
            # Day D needs records 24D+1 .. 24D+24 in a 1-based-from-01:00 sense: the file starts at
            # 00:00, so day 0 is records 1..24, and the last day borrows record 0 of y+1.
            valid = np.isfinite(np.ma.filled(s["Tair"][0], np.nan))
            fy, fx = sea_fill_index(valid)
            latw_sub = latw[rows][::-1] if flip else latw[rows]

            outs = {}
            for var in VARS:
                p = out_dir / f"glofas_{var}_{y}.nc"
                if p.exists() and not a.force:
                    with Dataset(p) as d:
                        if len(d["time"]) == nd:
                            print(f"{y}: {var} exists with {nd} days, skip", flush=True)
                            continue
                outs[var] = open_out(p, var, latg, long_, y, nd)
            if not outs:
                print(f"{y}: all variables present, skip", flush=True); continue

            first = dt.datetime(y, 1, 2)   # day 1 Jan is stamped 02/01 00:00
            nxt = None
            for d_i in range(nd):
                lo_, hi = 24 * d_i + 1, 24 * d_i + 25
                if hi <= nt:
                    h = {k: np.ma.filled(s[k][lo_:hi].astype("f8"), np.nan) for k in SRC}
                else:                      # last day of the year: closing record from y+1
                    if nxt is None:
                        nxt = Dataset(src_file(paths, y + 1))
                    h = {k: np.concatenate([np.ma.filled(s[k][lo_:nt].astype("f8"), np.nan),
                                            np.ma.filled(nxt[k][0:1].astype("f8"), np.nan)], 0)
                         for k in SRC}
                h = {k: v[:, fy, fx] for k, v in h.items()}          # sea fill before regridding
                f = day_fields(h)
                if not all(np.isfinite(v).all() for v in f.values()):
                    sys.exit(f"{y} day {d_i}: NaN left after the sea fill")
                stamp = date2num([first + dt.timedelta(days=d_i)],
                                 "days since 1970-01-01 00:00:00", "proleptic_gregorian")[0]
                for var, (o, _) in outs.items():
                    a2 = f[var][rows][::-1] if flip else f[var][rows]
                    if VARS[var][1] == "block":
                        g = glofas.block_replicate(a2).astype("f4")
                    else:
                        g = glofas.interp_2d(a2, latw_sub, lonw, latg, long_)
                    o["time"][d_i] = stamp
                    o[var][d_i] = g
                if d_i == 0 or (d_i + 1) % 30 == 0 or d_i == nd - 1:
                    print(f"  {y} day {d_i + 1}/{nd}  {time.time() - t0:6.0f}s", flush=True)
            if nxt is not None:
                nxt.close()

        msg = []
        for var, (o, tmp) in outs.items():
            c = np.asarray(o[var][:])
            msg.append(f"{var}: mean {c.mean():.3f}" + (f" ({c.mean(axis=(1, 2)).sum():.1f} mm total)" if var == "tp" else ""))
            o.close()
            os.replace(tmp, out_dir / f"glofas_{var}_{y}.nc")
        print(f"{y}: {nd} days, {int(valid.sum())} land 0.5deg cells, {time.time() - t0:.0f}s | "
              + " | ".join(msg), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
