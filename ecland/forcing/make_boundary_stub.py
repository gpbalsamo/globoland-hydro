#!/usr/bin/env python3
"""Create a one-record WFDE5 stub so the final year of the archive can be run
as a FULL calendar year.

Each segment integrates 00:00 1 Jan of Y to 00:00 1 Jan of Y+1, which needs a
forcing record AT 00:00 1 Jan of Y+1 (see run/run_ecland.sh). For the last
year in the archive that file does not exist, so the year is not runnable.

This writes a stub named like a real year file, holding exactly one record at
00:00 1 Jan of Y+1, copied from a chosen record of year Y. preprocess_wfde5.py
then picks it up through --next-input with no code change, and its 1-hour
contiguity check passes.

WHICH SOURCE RECORD MATTERS. The stub is the right-hand bracket for the
interpolation over the final hour only, so its influence is small -- but it is
not zero, and the two obvious choices are not equivalent. Measured on 2024
over 92889 land points:

    |Tair(00:00 1 Jan 2024) - Tair(23:00 31 Dec 2024)|  = 4.31 K mean
    |SWdown|                                            = 40.2 W m-2
    |Rainf|                                             = 1.43e-5 kg m-2 s-1
                                                          (larger than the
                                                           field's own mean)

--source last (the default) repeats 23:00 31 Dec, i.e. PERSISTENCE: the final
hour then has zero tendency, which is physically benign. --source first copies
00:00 1 Jan of the same year, which is the same calendar instant a year
earlier and injects the jump quantified above into the last hour of the run.
Persistence is recommended; first is offered because it is a reasonable thing
to want and the difference is confined to one hour in 8784.
"""
import argparse, sys
from pathlib import Path
import numpy as np
from netCDF4 import Dataset, num2date, date2num

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, type=Path, help="year-Y WFDE5 file")
    p.add_argument("--output", required=True, type=Path, help="stub for year Y+1")
    p.add_argument("--source", choices=["last", "first"], default="last",
                   help="record to copy: 'last' = 23:00 31 Dec (persistence, default), "
                        "'first' = 00:00 1 Jan of year Y")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()

    if a.output.exists() and not a.overwrite:
        sys.exit(f"{a.output} exists (use --overwrite)")

    with Dataset(a.input) as src:
        t = src["time"]
        tv = np.asarray(t[:], dtype="f8")
        units, cal = t.units, getattr(t, "calendar", "standard")
        idx = -1 if a.source == "last" else 0
        src_time = num2date(tv[idx], units=units, calendar=cal)
        last_time = num2date(tv[-1], units=units, calendar=cal)
        target = last_time + (last_time - num2date(tv[-2], units=units, calendar=cal))
        if abs((target - last_time).total_seconds() - 3600.0) > 1.0:
            sys.exit("ERROR: input is not hourly; refusing to guess the stub timestamp")
        print(f"  input      : {a.input.name}  ({len(tv)} records, ends {last_time})")
        print(f"  stub time  : {target}")
        print(f"  copied from: {src_time}  (--source {a.source})")

        a.output.parent.mkdir(parents=True, exist_ok=True)
        if a.output.exists():
            a.output.unlink()
        with Dataset(a.output, "w", format="NETCDF4_CLASSIC") as dst:
            dst.createDimension("time", None)
            for d in ("lat", "lon"):
                dst.createDimension(d, len(src.dimensions[d]))
                v = dst.createVariable(d, "f4", (d,))
                v[:] = src[d][:]
                for k in src[d].ncattrs():
                    v.setncattr(k, src[d].getncattr(k))
            tvar = dst.createVariable("time", "f8", ("time",))
            tvar[:] = [date2num(target, units=units, calendar=cal)]
            tvar.units, tvar.calendar = units, cal
            for name in src.variables:
                if name in ("time", "lat", "lon"):
                    continue
                sv = src[name]
                if "time" not in sv.dimensions:          # static field, copy whole
                    nv = dst.createVariable(name, "f4", sv.dimensions,
                                            fill_value=getattr(sv, "_FillValue", 1.0e20))
                    nv[:] = sv[:]
                else:
                    nv = dst.createVariable(name, "f4", ("time", "lat", "lon"),
                                            fill_value=getattr(sv, "_FillValue", 1.0e20),
                                            zlib=True, complevel=4, shuffle=True)
                    nv[0] = sv[idx]
                for k in sv.ncattrs():
                    if k != "_FillValue":
                        nv.setncattr(k, sv.getncattr(k))
            dst.Conventions = "CF-1.6"
            dst.source = f"one-record boundary stub copied from {a.input.name} @ {src_time}"
            dst.comment = ("Synthetic: exists only to bracket the final hour of the "
                           f"preceding year's run. --source {a.source}.")
    print(f"CREATED {a.output}")

if __name__ == "__main__":
    main()
