#!/usr/bin/env python3
"""Aggregate LISFLOOD total/surface runoff from GloFAS 0.05 deg onto ecLand's 0.5 deg grid.

This is the product the comparison with ecLand and the aiLand cross-training actually consume,
and the only thing from a global run that is small enough to keep permanently: 720x360 daily for
37 years is ~14 GB, against ~1.2 TB of native 0.05 deg output.

DIRECTION OF THE AGGREGATION IS NOT A DETAIL. The GloFAS grid nests exactly 10x10 inside the
ecLand/WFDE5 0.5 deg grid, so going UP is a plain area-weighted mean and is exact. Going the
other way -- interpolating ecLand down to 0.05 deg -- would manufacture detail that is not in the
0.5 deg runoff and is forbidden by wfde5-ecland/docs/grid_strategy.md as a scientific-validity
invariant, not a style preference. Aggregate LISFLOOD up; never interpolate ecLand down.

TWO AREA CONVENTIONS, BOTH WRITTEN, because picking one silently is exactly how the ecLand->CaMa
remap hid a 3,400 km3/yr term until wfde5-ecland/cama_flood/validate_remapping.py separated them:

  trun      mean over the GloFAS LAND sub-cells only  -> mm/day per m2 of GloFAS land
  trun_box  mean over all 100 sub-cells, missing = 0  -> mm/day per m2 of the 0.5 deg box
  cover     how many of the 100 sub-cells are GloFAS land, as a fraction

trun is the like-for-like partner of ecLand's -(Qs+Qsb) (a flux per m2 of land); trun_box is what
you want if you need a box-mean. Where cover is small the two differ by the reciprocal of cover,
so compare_runoff.py screens on it rather than averaging the difference away.

Rows south of 60S carry no GloFAS catchments at all (the grid stops at 60S), so they are written
as missing on the full 360x720 ecLand grid rather than silently dropped.

Usage:
  python3 glofas/aggregate_runoff.py --tag y1988 --year 1988 [--vars trun srun]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import glofas  # noqa: E402

R_EARTH = 6371000.0
NLAT_E, NLON_E = 360, 720            # ecLand / WFDE5 global 0.5 deg
LONG_NAME = {"trun": "LISFLOOD total runoff (surface + upper zone + lower zone)",
             "srun": "LISFLOOD surface runoff"}


def ecland_grid():
    """The ecLand/WFDE5 0.5 deg global grid: latitude ASCENDING, centres at x.25/x.75."""
    lat = -89.75 + 0.5 * np.arange(NLAT_E)
    lon = -179.75 + 0.5 * np.arange(NLON_E)
    return lat, lon


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="run tag (work/runs/<tag>/out)")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--vars", nargs="+", default=["trun", "srun"])
    ap.add_argument("--out", type=Path, default=None, help="default <product_dir>/runoff_05deg_<year>.nc")
    a = ap.parse_args(argv)

    paths = glofas.load_paths(); w = glofas.work(paths)
    out_dir = glofas.product(paths)
    src_dir = w / "runs" / a.tag / "out"
    latg, long_ = glofas.glofas_grid(paths)
    late, lone = ecland_grid()

    # which ecLand rows the GloFAS grid covers, and in which direction
    rows, flip = glofas.nesting(late, lone, latg, long_)
    nr = rows.stop - rows.start
    if nr * glofas.RATIO != len(latg):
        sys.exit("grid nesting changed; refusing to aggregate")

    # GloFAS land mask -> per-0.5deg count of land sub-cells
    from netCDF4 import Dataset as DS
    with DS(glofas.mask_map(paths)) as dm:
        name = [k for k in dm.variables if k not in ("lat", "lon", "crs", "laea")][0]
        land = ~np.ma.getmaskarray(dm[name][:])
    cov = land.reshape(nr, glofas.RATIO, len(lone), glofas.RATIO).sum(axis=(1, 3)).astype("f8")
    if flip:
        cov = cov[::-1]
    cover_full = np.zeros((NLAT_E, NLON_E)); cover_full[rows] = cov / (glofas.RATIO ** 2)

    out = a.out or out_dir / f"runoff_05deg_{a.year}.nc"
    tmp = Path(str(out) + ".partial")
    t0 = time.time()
    srcs = {}
    for v in a.vars:
        f = src_dir / f"{v}.nc"
        if not f.exists():
            sys.exit(f"{f} missing -- was make_settings.py run without the runoff options?")
        srcs[v] = Dataset(f)
    nt = min(len(d["time"]) for d in srcs.values())

    with Dataset(tmp, "w") as o:
        o.createDimension("time", None); o.createDimension("lat", NLAT_E); o.createDimension("lon", NLON_E)
        t = o.createVariable("time", "f8", ("time",))
        first = next(iter(srcs.values()))["time"]
        t.units = first.units; t.calendar = getattr(first, "calendar", "proleptic_gregorian")
        la = o.createVariable("lat", "f8", ("lat",)); la.units = "degrees_north"; la[:] = late
        lo = o.createVariable("lon", "f8", ("lon",)); lo.units = "degrees_east"; lo[:] = lone
        c = o.createVariable("cover", "f4", ("lat", "lon"), zlib=True, complevel=4)
        c.units = "1"; c.long_name = "fraction of the 0.5 deg cell that is GloFAS land (n/100)"
        c[:] = cover_full
        vars_out = {}
        for v in a.vars:
            for suffix, desc in ((v, "per m2 of GloFAS land"), (f"{v}_box", "per m2 of the 0.5 deg box")):
                x = o.createVariable(suffix, "f4", ("time", "lat", "lon"), zlib=True, complevel=4,
                                     fill_value=np.float32(-9999.0), chunksizes=(1, NLAT_E, NLON_E))
                x.units = "mm/day"; x.long_name = f"{LONG_NAME.get(v, v)}, {desc}"
                vars_out[suffix] = x
        o.source = f"LISFLOOD 5.0.0 GloFAS v5 global, WFDE5 forcing, run tag {a.tag}"
        o.aggregation = ("exact 10x10 area-weighted mean from GloFAS 0.05 deg to the ecLand 0.5 deg grid; "
                         "latitudes south of 60S carry no GloFAS catchments and are missing")
        o.day_convention = "step stamped D+1 00:00 holds the 24 h ending at that time (day D)"

        R = R_EARTH
        for i in range(nt):
            t[i] = srcs[a.vars[0]]["time"][i]
            for v in a.vars:
                d = srcs[v]
                nm = [k for k in d.variables if k not in ("time", "lat", "lon", "crs", "laea")][0]
                arr = np.ma.filled(np.asarray(d[nm][i], "f8"), np.nan)
                # area weight within a 0.5 deg cell varies only with latitude, and within one
                # 0.5 deg row the 10 GloFAS rows have slightly different areas: weight them.
                hd = np.deg2rad(glofas.RES_G) / 2
                belt = (R * R * np.deg2rad(glofas.RES_G)
                        * (np.sin(np.deg2rad(latg) + hd) - np.sin(np.deg2rad(latg) - hd)))
                wgt = np.abs(belt)[:, None] * np.ones((1, len(long_)))
                wgt = np.where(land, wgt, 0.0)
                num = np.nan_to_num(arr * wgt).reshape(nr, glofas.RATIO, len(lone), glofas.RATIO).sum(axis=(1, 3))
                den_land = wgt.reshape(nr, glofas.RATIO, len(lone), glofas.RATIO).sum(axis=(1, 3))
                den_box = (np.abs(belt)[:, None] * np.ones((1, len(long_)))).reshape(
                    nr, glofas.RATIO, len(lone), glofas.RATIO).sum(axis=(1, 3))
                if flip:
                    num, den_land, den_box = num[::-1], den_land[::-1], den_box[::-1]
                full_land = np.full((NLAT_E, NLON_E), np.nan)
                full_box = np.full((NLAT_E, NLON_E), np.nan)
                with np.errstate(invalid="ignore", divide="ignore"):
                    full_land[rows] = np.where(den_land > 0, num / np.where(den_land > 0, den_land, 1), np.nan)
                    full_box[rows] = np.where(den_box > 0, num / den_box, np.nan)
                vars_out[v][i] = np.where(np.isfinite(full_land), full_land, -9999.0)
                vars_out[f"{v}_box"][i] = np.where(np.isfinite(full_box), full_box, -9999.0)
            if i == 0 or (i + 1) % 30 == 0 or i == nt - 1:
                print(f"  day {i + 1}/{nt}  {time.time() - t0:5.0f}s", flush=True)
    for d in srcs.values():
        d.close()
    tmp.replace(out)
    with Dataset(out) as o:
        for v in a.vars:
            x = np.ma.filled(o[v][:], np.nan)
            print(f"{v}: land-cell mean {np.nanmean(x):.4f} mm/day, "
                  f"cells with data {int(np.isfinite(x[0]).sum())}")
    print(f"{a.year}: {nt} days -> {out}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
