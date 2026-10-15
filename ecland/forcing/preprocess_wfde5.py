#!/usr/bin/env python3
"""Convert a forcing/download_wfde5.py output file into the exact NetCDF
format ecLand's own official tooling expects (ecland_create_namelist.py,
ecland_run_model.sh): `met_<FORCINGTYPE>HT_<STA>.nc`, variables named
Tair/Qair/PSurf/SWdown/LWdown/Rainf/Snowf/Wind_E/Wind_N.

Verified against the real reference file this repo's ecland build ships
(`tests/2D_EU-001_20220101-20220102`), see PLAN.md Milestone 3.

Two things this does that are NOT a trivial rename:

1. **Wind splitting.** WFDE5 provides a single scalar wind SPEED (`Wind`,
   m/s); ecLand's forcing reader wants vector components (`Wind_E`,
   `Wind_N`). ecLand's land-surface physics only uses wind SPEED (for
   turbulent transfer coefficients), never direction, so this assigns the
   full magnitude to Wind_E and sets Wind_N=0 -- `sqrt(Wind_E^2+Wind_N^2)`
   reproduces WFDE5's real wind speed exactly; the implied "all wind blows
   east" direction is a documented fiction, not a real assumption about wind
   direction (see docs/forcing_variables.md).
2. **Time slicing to a genuine midnight start.** ecLand's own
   `ecland_create_namelist.py` hardcodes NSSSSS=0 for 2D-type forcing (the
   run always starts at 00:00:00 of NINDAT) and reads NINDAT purely from the
   forcing file's `time:units` reference date, not from the data values
   -- so the first record in the output file MUST be a genuine midnight
   record, not just "whatever the input file happened to start with".
   --start-date must land on an actual midnight timestamp present in the
   input file, or this refuses to proceed (see docs/forcing_variables.md's
   note on a related, distinct gotcha in a sibling pipeline: never assume a
   file "starts at midnight" without checking the real timestamp).

`Ctpf` (convective precipitation fraction) is dropped: it isn't one of
NAMFORC's nine CFORC* groups and WFDE5 has no equivalent diagnostic.

Usage:
    python3 forcing/preprocess_wfde5.py \
        --input forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_1988_01-01.nc \
        --output run/work/met_2DHT_GLOBAL_19880101-19880102.nc \
        --start-date 1988-01-01T00:00:00 --n-hours 25
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, date2num, num2date

# WFDE5 short name -> (ecLand forcing name, units, long_name)
VARIABLE_MAP = {
    "Tair": ("Tair", "K", "Temperature"),
    "Qair": ("Qair", "kg/kg", "Specific humidity"),
    "PSurf": ("PSurf", "Pa", "Surface Pressure"),
    "SWdown": ("SWdown", "W/m2", "Downward shortwave radiation"),
    "LWdown": ("LWdown", "W/m2", "Downward longwave radiation"),
    "Rainf": ("Rainf", "kg/m2/s", "Rainfall"),
    "Snowf": ("Snowf", "kg/m2/s", "Snowfall"),
}
REQUIRED_SOURCE_VARS = tuple(VARIABLE_MAP.keys()) + ("Wind",)

# How many hourly records to hold in memory at once while converting. One
# variable-block costs TIME_BLOCK_HOURS*360*720*4 bytes at 0.5 deg, so 168
# (a week) is ~174 MB -- small enough for an 8 GiB session, large enough
# that NetCDF writes stay efficient. The whole-year alternative needed
# ~82 GB and could not run at all.
TIME_BLOCK_HOURS = 168

# WFDE5 is a LAND-ONLY product (masks ocean intentionally -- it's a
# bias-corrected reanalysis meant to force land-surface models over land,
# unlike ERA5 itself, which has no ocean gaps). ecLand's Fortran
# surfexcdriver_ctl is not tolerant of a literal 0.0 for Tair/PSurf/Qair at
# masked points -- confirmed 2026-09-19: filling masked cells with 0.0
# crashed with "floating point exception: invalid operation" on the very
# first timestep (0 K / 0 Pa feed a division/sqrt in the exchange-
# coefficient formulas). Ocean-cell *outputs* are meaningless regardless
# (surfclim's own land-sea mask is what determines scientific validity, not
# the forcing values) -- these are numerically-safe reference-atmosphere
# placeholders for masked cells only, never applied to real land data.
MASKED_FILL_VALUES = {
    "Tair": 288.0,      # K, standard reference temperature
    "Qair": 0.001,      # kg/kg, small positive
    "PSurf": 101325.0,  # Pa, standard sea-level pressure
    "SWdown": 0.0,      # W/m2, legitimately zero at night -- safe as-is
    "LWdown": 0.0,      # W/m2, only used as a downwelling flux -- safe as-is
    "Rainf": 0.0,       # kg/m2/s, legitimately zero -- safe as-is
    "Snowf": 0.0,       # kg/m2/s, legitimately zero -- safe as-is
    "Wind": 1.0,        # m/s, small positive -- avoid zero-wind edge cases
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--start-date", required=True,
        help="ISO datetime (e.g. 1988-01-01T00:00:00) -- must be an exact timestamp present in --input.",
    )
    parser.add_argument(
        "--n-hours", required=True, type=int,
        help="Number of consecutive hourly records to write, starting at --start-date.",
    )
    parser.add_argument("--next-input", type=Path, default=None,
                        help="following year's WFDE5 file; lets the slice run past the end "
                             "of --input so a segment can cover a FULL calendar year")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def find_start_index(time_values: np.ndarray, units: str, calendar: str, start_date: datetime) -> int:
    target = date2num(start_date, units=units, calendar=calendar)
    # rtol=0 is essential. np.isclose defaults to rtol=1e-5, and this axis is
    # "hours since 1900-01-01", so values are ~8e5 and the implied tolerance
    # is ~8 HOURS -- fifteen records match a single timestamp and matches[0]
    # silently returns one 7 h early. Runs that start at the file's first
    # record were unaffected (matches[0] is then correctly 0), which is why
    # this never showed up; any slice starting mid-file -- every segment of a
    # monthly-chunked campaign -- would have been offset.
    matches = np.where(np.isclose(time_values, target, rtol=0.0, atol=1e-6))[0]
    if matches.size == 0:
        dates = num2date(time_values[[0, -1]], units=units, calendar=calendar)
        raise ValueError(
            f"--start-date {start_date} not found in input time axis "
            f"(input spans {dates[0]} .. {dates[1]}). Refusing to guess an offset -- "
            "ecland_create_namelist.py hardcodes a midnight start for 2D forcing, "
            "so this must be an exact, real timestamp, not an approximation."
        )
    if matches.size > 1:
        raise ValueError(
            f"--start-date {start_date} matched {matches.size} records -- the time axis "
            "is not strictly increasing, or the tolerance is wrong")
    idx = int(matches[0])
    got = num2date(time_values[idx], units=units, calendar=calendar)
    if abs((got - start_date).total_seconds()) > 1.0:
        raise ValueError(f"--start-date {start_date} resolved to {got} (index {idx})")
    return idx


def convert(input_path: Path, output_path: Path, start_date: datetime, n_hours: int,
            overwrite: bool, next_input: Path = None) -> None:
    """Write n_hours of ecLand forcing starting at start_date.

    next_input lets the slice run past the end of input_path and take the
    remainder from the following year's file. That is what allows a segment to
    integrate a FULL calendar year: to reach 00:00 on 1 Jan of Y+1 the model
    needs a forcing record AT that instant, i.e. 8761 records for a 8760-hour
    year. Without it ecland_create_namelist.py's
    nstop = nforcing*(forcing_step/tstep) - 2 stops an hour short, the final
    daily write never happens, and 31 Dec is missing from every year.
    """
    with Dataset(input_path) as src:
        missing = [v for v in REQUIRED_SOURCE_VARS if v not in src.variables]
        if missing:
            raise ValueError(f"{input_path}: missing required variable(s): {missing}")

        time_var = src.variables["time"]
        time_values = np.asarray(time_var[:], dtype=np.float64)
        units = time_var.units
        calendar = getattr(time_var, "calendar", "standard")

        start_idx = find_start_index(time_values, units, calendar, start_date)
        end_idx = start_idx + n_hours
        spill = 0
        if end_idx > time_values.size:
            spill = end_idx - time_values.size
            if next_input is None:
                raise ValueError(
                    f"{input_path}: requested {n_hours} hours from index {start_idx}, "
                    f"but only {time_values.size - start_idx} are available "
                    f"(pass --next-input to continue into the following file)"
                )
            end_idx = time_values.size

        # Confirm every requested record really is hourly and contiguous --
        # a silent gap here would desync the model from real time.
        sliced_time = time_values[start_idx:end_idx]
        if sliced_time.size > 1:
            increments_hours = np.diff(
                num2date(sliced_time, units=units, calendar=calendar, only_use_cftime_datetimes=True)
            )
            # cftime datetime subtraction gives timedeltas; require exactly 1 hour apart.
            for inc in increments_hours:
                if abs(inc.total_seconds() - 3600.0) > 1e-6:
                    raise ValueError(f"{input_path}: non-hourly gap found within the requested slice ({inc})")

        lat = np.asarray(src.variables["lat"][:], dtype=np.float32)
        lon = np.asarray(src.variables["lon"][:], dtype=np.float32)

    if output_path.exists():
        if not overwrite:
            raise FileExistsError(f"{output_path} exists (use --overwrite)")
        output_path.unlink()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if spill:
        with Dataset(next_input) as nxt:
            nt = nxt.variables["time"]
            nxt_first = num2date(np.asarray(nt[:spill], dtype=np.float64), units=nt.units,
                                 calendar=getattr(nt, "calendar", "standard"),
                                 only_use_cftime_datetimes=True)
            last = num2date(time_values[end_idx - 1], units=units, calendar=calendar,
                            only_use_cftime_datetimes=True)
            gap = (nxt_first[0] - last).total_seconds()
            if abs(gap - 3600.0) > 1e-6:
                raise ValueError(
                    f"{next_input}: first record is {gap/3600:.3f} h after the last record of "
                    f"{input_path}, expected exactly 1 h -- the two files are not contiguous")
        print(f"  spanning into {Path(next_input).name} for {spill} record(s)")

    out_time_units = f"seconds since {start_date.strftime('%Y-%m-%d %H:%M:%S')}"
    out_time_values = np.arange(n_hours, dtype=np.float64) * 3600.0

    with Dataset(output_path, "w", format="NETCDF4") as dst:
        dst.createDimension("time", None)
        dst.createDimension("lat", lat.size)
        dst.createDimension("lon", lon.size)

        tvar = dst.createVariable("time", "f8", ("time",))
        tvar[:] = out_time_values
        tvar.standard_name = "time"
        tvar.long_name = "time"
        tvar.units = out_time_units
        tvar.calendar = "standard"
        tvar.axis = "T"

        latvar = dst.createVariable("lat", "f4", ("lat",))
        latvar[:] = lat
        latvar.standard_name = "latitude"
        latvar.long_name = "latitude"
        latvar.units = "degrees_north"
        latvar.axis = "Y"

        lonvar = dst.createVariable("lon", "f4", ("lon",))
        lonvar[:] = lon
        lonvar.standard_name = "longitude"
        lonvar.long_name = "longitude"
        lonvar.units = "degrees_east"
        lonvar.axis = "X"

        out_vars = {}
        for src_name, (out_name, units_str, long_name) in VARIABLE_MAP.items():
            var = dst.createVariable(out_name, "f4", ("time", "lat", "lon"))
            var.standard_name = long_name
            var.long_name = long_name
            var.units = units_str
            var._CoordinateAxisType = "Time Lat Lon"
            out_vars[src_name] = var

        # Wind speed -> arbitrary-direction vector components (see module
        # docstring): sqrt(Wind_E^2 + Wind_N^2) == WFDE5's real Wind exactly.
        wind_e = dst.createVariable("Wind_E", "f4", ("time", "lat", "lon"))
        wind_e.standard_name = "Wind speed U component"
        wind_e.long_name = "Wind speed U component"
        wind_e.units = "m/s"
        wind_e._CoordinateAxisType = "Time Lat Lon"

        wind_n = dst.createVariable("Wind_N", "f4", ("time", "lat", "lon"))
        wind_n.standard_name = "Wind speed V component co"
        wind_n.long_name = "Wind speed V component co"
        wind_n.units = "m/s"
        wind_n._CoordinateAxisType = "Time Lat Lon"

        # Copy in time blocks rather than whole variables. A single variable
        # at 0.5 deg is n_hours*360*720*4 bytes -- 223 MB for a day but 9.1 GB
        # for a leap year, and holding all eight source variables plus a
        # zeros_like for Wind_N needed ~82 GB, which no interactive session
        # (8 GiB cgroup here) survives. Blocking bounds peak memory at
        # TIME_BLOCK_HOURS regardless of how long the run is.
        # Iterate over what THIS file actually holds (end_idx-start_idx), not
        # n_hours: when the slice spills into the next year's file the last
        # block would otherwise ask for records the source does not have.
        n_main = end_idx - start_idx
        with Dataset(input_path) as src:
            for blk_start in range(0, n_main, TIME_BLOCK_HOURS):
                blk_end = min(blk_start + TIME_BLOCK_HOURS, n_main)
                s0, s1 = start_idx + blk_start, start_idx + blk_end
                for src_name, var in out_vars.items():
                    var[blk_start:blk_end] = np.ma.filled(
                        src.variables[src_name][s0:s1], MASKED_FILL_VALUES[src_name]
                    ).astype(np.float32)
                # "Wind" is deliberately NOT in VARIABLE_MAP (it has no
                # one-to-one output variable) -- it is appended to
                # REQUIRED_SOURCE_VARS separately and split into components
                # here, so it must be read outside the loop above.
                wind_block = np.ma.filled(
                    src.variables["Wind"][s0:s1], MASKED_FILL_VALUES["Wind"]
                ).astype(np.float32)
                wind_e[blk_start:blk_end] = wind_block
                wind_n[blk_start:blk_end] = np.zeros_like(wind_block)
                print(
                    f"  wrote hours {blk_start}-{blk_end} of {n_hours} "
                    f"({100.0 * blk_end / n_main:.0f}% of this file)"
                )

        if spill:
            base = end_idx - start_idx
            with Dataset(next_input) as nxt:
                for src_name, var in out_vars.items():
                    var[base:base + spill] = np.ma.filled(
                        nxt.variables[src_name][:spill], MASKED_FILL_VALUES[src_name]
                    ).astype(np.float32)
                wb = np.ma.filled(nxt.variables["Wind"][:spill],
                                  MASKED_FILL_VALUES["Wind"]).astype(np.float32)
            wind_e[base:base + spill] = wb
            wind_n[base:base + spill] = np.zeros_like(wb)
            print(f"  wrote {spill} spill record(s) from the next file")

        dst.Conventions = "CF-1.6"
        dst.source = str(input_path)
        dst.comment = (
            "Converted by forcing/preprocess_wfde5.py from WFDE5_CRU_GPCC "
            "for ecLand's met_2DHT forcing format. Wind_E carries WFDE5's "
            "full scalar wind speed; Wind_N is fictitious zero (see script "
            "docstring) -- ecLand's physics uses speed only, not direction."
        )

    print(f"CREATED {output_path}")
    print(f"  records: {n_hours}, start: {start_date}, time units: {out_time_units}")
    print(f"  grid: {lat.size} x {lon.size}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start_date = datetime.fromisoformat(args.start_date)
    convert(args.input, args.output, start_date, args.n_hours, args.overwrite, args.next_input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
