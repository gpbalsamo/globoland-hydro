#!/usr/bin/env python
"""JRC LISVAP (lisflood-lisvap 1.4.2) for one year of GLOBAL meteo (glofas/prepare_meteo.py output).

Generalises <exp>-glofas/glofas/run_lisvap.py; the method is that script's, which is in turn
liaise-glofas's. Mode "EFAS": Tavg/Tmax/Tmin [degC], actual vapour pressure [hPa], 10 m wind
[m/s] (LISVAP scales to 2 m itself), downward shortwave [J m-2 day-1]. Everything is converted
here so the LISVAP <lfconversions> block stays empty and no conversion value is ambiguous.

Differences from the regional version, both forced by going global:

  * The static maps are the operational global ones, used in place -- and the global MaskMap's
    variable is named `template`, not `Band1`, so the variable is found rather than hard-coded.
    (The regional repos cut their own mask, where it is Band1; that hard-coded name would raise
    a KeyError here.)
  * convert_inputs and the FAO-56 cross-check stream a day at a time. Reading a year of global
    0.05 deg f8 is 63 GB per variable; the regional version's whole-year arrays do not fit.

Also computes an INDEPENDENT FAO-56 Penman-Monteith ET0 from the same daily inputs as a sanity
check on LISVAP (different net-longwave and aerodynamic formulations, so they should agree to a
few percent, not exactly). liaise-glofas measured LISVAP ET0 ~22-24% BELOW FAO-56 every year;
that bias is inherited, documented, and is a reason to print both, not to silently trust one.

Usage:  <lisflood-env>/bin/python glofas/run_lisvap.py 1988 [--days 1]
"""
import argparse
import os
import re
import subprocess
import sys

import numpy as np
from netCDF4 import Dataset

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import glofas  # noqa: E402

_paths = glofas.load_paths()
W = str(glofas.work(_paths))
E = _paths["lisflood_env"]
TPL = _paths["lisvap_tpl"]
PKG = _paths["lisvap_pkg"]
SM = _paths["glofas_staticmaps"]
MASK = glofas.mask_map(_paths)
DEM = f"{SM}/extra/elv_Global_03min.nc"
LAT = f"{SM}/extra/latitude_Global_03min.nc"

OPTIONS = {
    "TemperatureInKelvinFlag": 0, "repE0Maps": 1, "repES0Maps": 1, "repET0Maps": 1, "repTAvgMaps": 0,
    "output6hourly": 0, "splitInput": 0, "splitOutput": 0, "monthlyOutput": 0,
    "EFAS": 1, "CORDEX": 0, "GLOFAS": 0, "ignore_nan_validation": 0,
    "useTAvg": 1, "useTDewMaps": 0, "useWindUVMaps": 0, "useRelHumidityMaps": 0, "useHargreaves": 0,
}
# out name: (source var, per-day conversion, units)
SPEC = {"tx": ("tx", lambda a: a - 273.15, "degree_celsius"),
        "tn": ("tn", lambda a: a - 273.15, "degree_celsius"),
        "ta": ("ta", lambda a: a, "degree_celsius"),
        "pd": ("pd", lambda a: a, "hPa"),
        "ws": ("ws", lambda a: a, "m s-1"),
        "rg": ("rg", lambda a: a * 86400.0, "J/m2")}


def main_var(d):
    return [k for k in d.variables if k not in ("time", "lat", "lon", "crs", "laea", "wgs_1984")][0]


def convert_inputs(y, outdir, days=None):
    """meteo/glofas_<v>_<y>.nc -> one LISVAP input file per variable, streamed day by day."""
    os.makedirs(outdir, exist_ok=True)
    for out, (src, fn, units) in SPEC.items():
        with Dataset(f"{W}/meteo/glofas_{src}_{y}.nc") as s:
            nd = len(s["time"]) if days is None else min(days, len(s["time"]))
            tmp = f"{outdir}/{out}.nc.partial"
            with Dataset(tmp, "w") as o:
                o.createDimension("time", None)
                o.createDimension("lat", len(s["lat"])); o.createDimension("lon", len(s["lon"]))
                for k in ("time", "lat", "lon"):
                    v = o.createVariable(k, s[k].dtype, (k,))
                    v.setncatts({a: s[k].getncattr(a) for a in s[k].ncattrs()})
                    v[:] = s[k][:nd] if k == "time" else s[k][:]
                name = main_var(s)
                v = o.createVariable(out, "f4", ("time", "lat", "lon"), zlib=True, complevel=4,
                                     fill_value=np.float32(-9999.0),
                                     chunksizes=(1, len(s["lat"]), len(s["lon"])))
                v.units = units
                for i in range(nd):
                    v[i] = fn(np.asarray(s[name][i], "f8")).astype("f4")
            os.replace(tmp, f"{outdir}/{out}.nc")
    return nd


def write_settings(y, indir, outdir, path, nd):
    t = open(TPL).read()
    import datetime as dt
    end = dt.datetime(y, 1, 2) + dt.timedelta(days=nd - 1)
    tv = {
        "CalendarDayStart": f"02/01/{y} 00:00", "StepStart": f"02/01/{y} 00:00",
        "StepEnd": end.strftime("%d/%m/%Y 00:00"),
        "PathOut": outdir, "PathMeteoIn": indir, "PathBaseMapsIn": f"{SM}/extra",
        "TMaxMaps": f"{indir}/tx", "TMinMaps": f"{indir}/tn", "TAvgMaps": f"{indir}/ta",
        "EActMaps": f"{indir}/pd", "WindMaps": f"{indir}/ws", "RgdMaps": f"{indir}/rg",
        "MaskMap": MASK, "Dem": DEM, "Lat": LAT,
    }
    for k, v in tv.items():   # skip values that are exactly one "$(Name)" reference (lfbinding copies)
        t = re.sub(r'(<textvar name="%s" value=")(?!\$\([A-Za-z]+\)")[^"]*(")' % k, r"\g<1>%s\g<2>" % v, t)
    for k, v in OPTIONS.items():
        t = re.sub(r'(<setoption name="%s"\s+choice=")[^"]*(")' % k, r"\g<1>%d\g<2>" % v, t)
    t = re.sub(r'(<setconversion name="[A-Za-z]+" value=")[^"]*(")', r"\g<1>\g<2>", t)
    open(path, "w").write(t)


def fao56_mean(indir, nd, land, wlat):
    """Area-weighted land-mean FAO-56 ET0 [mm/day] per day, streamed (a year of global f8 is 63 GB)."""
    g = {k: Dataset(f"{indir}/{k}.nc") for k in ("tx", "tn", "ta", "pd", "ws", "rg")}
    dl = Dataset(LAT); dd = Dataset(DEM)
    lat = np.deg2rad(np.asarray(dl[main_var(dl)][:], "f8"))
    z = np.ma.filled(np.asarray(dd[main_var(dd)][:], "f8"), 0.0)
    out = np.empty(nd)
    wsum = float(wlat[land].sum())
    for i in range(nd):
        tx, tn, ta, pd, u10 = (np.asarray(g[k][k][i], "f8") for k in ("tx", "tn", "ta", "pd", "ws"))
        rs = np.asarray(g["rg"]["rg"][i], "f8") * 1e-6                  # J m-2 d-1 -> MJ m-2 d-1
        doy = i + 1
        dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
        dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
        ws_ = np.arccos(np.clip(-np.tan(lat) * np.tan(dec), -1, 1))
        ra = 24 * 60 / np.pi * 0.0820 * dr * (ws_ * np.sin(lat) * np.sin(dec)
                                              + np.cos(lat) * np.cos(dec) * np.sin(ws_))
        rso = (0.75 + 2e-5 * z) * ra
        ea = pd / 10.0
        rnl = (4.903e-9 * ((tx + 273.16) ** 4 + (tn + 273.16) ** 4) / 2
               * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0)))
               * (1.35 * np.clip(np.divide(rs, rso, out=np.zeros_like(rs), where=rso > 0), 0.3, 1.0) - 0.35))
        rn = 0.77 * rs - rnl
        es = 0.6108 * (np.exp(17.27 * tx / (tx + 237.3)) + np.exp(17.27 * tn / (tn + 237.3))) / 2
        delta = 4098 * 0.6108 * np.exp(17.27 * ta / (ta + 237.3)) / (ta + 237.3) ** 2
        p = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
        gam = 0.000665 * p
        u2 = u10 * 4.87 / np.log(67.8 * 10 - 5.42)
        et0 = (0.408 * delta * rn + gam * 900 / (ta + 273) * u2 * (es - ea)) / (delta + gam * (1 + 0.34 * u2))
        out[i] = float((et0 * wlat)[land].sum() / wsum)
    for d in list(g.values()) + [dl, dd]:
        d.close()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("year", type=int)
    ap.add_argument("--days", type=int, default=None, help="only the first N days (pilot runs)")
    a = ap.parse_args()
    y = a.year
    indir, outdir = f"{W}/lisvap_in/{y}", f"{W}/lisvap_out/{y}"
    os.makedirs(outdir, exist_ok=True)
    nd = convert_inputs(y, indir, a.days)
    settings = f"{W}/lisvap_in/settings_{y}.xml"
    write_settings(y, indir, outdir, settings, nd)
    env = dict(os.environ, PYTHONPATH=PKG, PYTHONWARNINGS="ignore")
    r = subprocess.run([f"{E}/bin/python", f"{PKG}/bin/lisvap", settings, "-q"], env=env,
                       capture_output=True, text=True)
    print(r.stdout[-1500:]); print(r.stderr[-2500:], file=sys.stderr)
    print("exit code", r.returncode, "| outputs:", sorted(os.listdir(outdir)))
    if r.returncode:
        return r.returncode

    dm = Dataset(MASK); land = ~np.ma.getmaskarray(dm[main_var(dm)][:])
    lat = np.asarray(dm["lat"][:], "f8")
    R = 6371000.0
    hd = np.deg2rad(glofas.RES_G) / 2
    belt = R * R * np.deg2rad(glofas.RES_G) * (np.sin(np.deg2rad(lat) + hd) - np.sin(np.deg2rad(lat) - hd))
    wlat = np.repeat(np.abs(belt)[:, None], land.shape[1], axis=1)
    wsum = float(wlat[land].sum())
    for f in sorted(os.listdir(outdir)):
        if not f.endswith(".nc"):
            continue
        d = Dataset(f"{outdir}/{f}"); name = main_var(d)
        per_day = np.array([float((np.ma.filled(np.asarray(d[name][i], "f8"), np.nan) * wlat)[land].sum() / wsum)
                            for i in range(len(d["time"]))])
        print(f"{f}: shape {d[name].shape} land-mean {np.nanmean(per_day):.3f} mm/d  "
              f"period total {np.nansum(per_day):.1f} mm  {getattr(d[name], 'units', '')}")
    ref = fao56_mean(indir, nd, land, wlat)
    print(f"FAO-56 reference ET0: land-mean {ref.mean():.3f} mm/d  period total {ref.sum():.1f} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
