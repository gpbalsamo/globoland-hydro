#!/usr/bin/env python3
"""
Download and assemble WFDE5-CRU-GPCC 0.5-degree forcing from the Copernicus
Climate Data Store (CDS) -- global, not regionally cropped.

GENERALISATION NOTE (wfde5-ecland, see docs/migration_from_liaise.md,
Category B): ported from gpbalsamo/liaise-ecland's
forcing/get_liaise_forcing_05_cds.py (commit ab8a0ab). The CDS request
machinery (dataset name, the mandatory cru/cru_and_gpcc split, retry-free
single-shot retrieval, variable/unit tables) is verified and carried over
unchanged; the LIAISE bounding-box crop that ran after every download is
REMOVED -- this repo's target is the full global 0.5 deg field, not a
regional clip (see CLAUDE.md's "Grid invariants" and
docs/grid_strategy.md). The resulting per-file grid is recorded and checked
for internal consistency (same shape/values across every variable and every
month) but NOT asserted against any presumed global coordinate convention:
longitude range (-180..180 vs 0..360) and latitude ordering are explicitly
open questions (docs/forcing_variables.md) that forcing/validate_wfde5.py
must answer against real downloaded data, not this script.

NOT YET EXECUTED against a real CDS request in this repository -- see
PLAN.md Milestone 1. The recommended first use is a single month
(--start-year Y --end-year Y --months 01), not a full year or a multi-year
range: an uncropped global 0.5 deg field is dramatically larger than the
LIAISE crop this script's logic was validated against. One month of one
dynamic variable is already ~360 x 720 x 744 x 4 bytes =~ 770 MB in memory;
assembling a full year of all 7 dynamic variables at once is on the order of
tens of GB resident at peak (see the memory estimate this script prints
before assembly) -- verify a small request actually works end-to-end before
committing to a large one.

Requires:
  pip install cdsapi
  a configured ~/.cdsapirc (https://cds.climate.copernicus.eu/how-to-api)

Example
-------
# Cheap first real test -- one month, one year (see PLAN.md's immediate
# next step):
python3 forcing/download_wfde5.py \
    --start-year 1988 --end-year 1988 --months 01 \
    --output-dir forcing/WFDE5_CRU_GPCC

# See what would be requested/written without calling CDS or touching disk:
python3 forcing/download_wfde5.py --start-year 1988 --end-year 1988 --months 01 --dry-run

Notes (inherited from liaise-ecland, confirmed against the live CDS API on
2026-08-14 -- re-check if the dataset schema ever changes)
---------------------------------------------------------
- The dataset's process schema only accepts six request keys: product,
  variable, reference_dataset, year, month, version. There is no "area"
  key -- CDS always returns the full global 0.5-degree field; there was
  never a server-side way to crop, even in the LIAISE-regional predecessor.
- "product": "wfde5" is required (omitting it produces a 400 "invalid
  request").
- Per the dataset's declared constraints, reference_dataset="cru_and_gpcc"
  is only a valid combination with variable in {rainfall_flux,
  snowfall_flux}; every other variable (including grid_point_altitude)
  requires reference_dataset="cru". Requesting all 9 variables under one
  reference_dataset in a single call always fails with a 400 "invalid
  combination of values". This script therefore issues two requests per
  year: one reference_dataset="cru" request for the 6 dynamic
  non-precipitation variables plus grid_point_altitude, and one
  reference_dataset="cru_and_gpcc" request for rainfall_flux/
  snowfall_flux -- see build_requests().
- version="3_0" must be passed explicitly; omitting it (relying on the
  schema's advertised default) also produces a 400.
- Downloaded archives are zips containing one NetCDF file per
  variable-month, and the in-file variable name is already the short
  WFDE5 name (e.g. "Tair", "Rainf"). identify_variable() still matches
  both short and long CDS names defensively.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, date2num, num2date

DATASET = "derived-near-surface-meteorological-variables"

# Fixed WFDE5 reference heights (not distributed as CDS variables).
HEIGHT_LEV1 = 2.0  # m, near-surface scalar variables (Tair, Qair)
HEIGHT_LEVUV = 10.0  # m, near-surface wind

ALL_MONTHS = [f"{m:02d}" for m in range(1, 13)]

# CDS variable name -> short WFDE5 name -- see docs/forcing_variables.md,
# the verified source for this table. Split by the reference_dataset value
# the CDS constraints require for each (see module docstring):
# "cru_and_gpcc" is only valid for the two precipitation variables;
# everything else, including the static grid_point_altitude, requires "cru".
CDS_VARIABLES_CRU = {
    "grid_point_altitude": "ASurf",
    "near_surface_air_temperature": "Tair",
    "near_surface_specific_humidity": "Qair",
    "near_surface_wind_speed": "Wind",
    "surface_air_pressure": "PSurf",
    "surface_downwelling_longwave_radiation": "LWdown",
    "surface_downwelling_shortwave_radiation": "SWdown",
}
CDS_VARIABLES_CRU_GPCC = {
    "rainfall_flux": "Rainf",
    "snowfall_flux": "Snowf",
}
CDS_VARIABLES = {**CDS_VARIABLES_CRU, **CDS_VARIABLES_CRU_GPCC}
STATIC_VARIABLES = {"ASurf"}
SHORT_NAMES = set(CDS_VARIABLES.values())

# Some CDS deliveries use the short WFDE5 name directly as the in-file
# variable name; others may use the long CDS name. Recognise both.
NAME_LOOKUP = {short: short for short in SHORT_NAMES}
NAME_LOOKUP.update(CDS_VARIABLES)

# Output attributes -- units/long_name are asserted explicitly rather than
# trusted verbatim from whatever CDS attaches to the delivered file.
VARIABLE_ATTRS = {
    "Rainf": ("kg m-2 s-1", "Rainfall Flux"),
    "Snowf": ("kg m-2 s-1", "Snowfall Flux"),
    "Tair": ("K", "Near-Surface Air Temperature"),
    "Qair": ("kg kg-1", "Near-Surface Specific Humidity"),
    "PSurf": ("Pa", "Surface Air Pressure"),
    "SWdown": ("W m-2", "Surface Downwelling Shortwave Radiation"),
    "LWdown": ("W m-2", "Surface Downwelling Longwave Radiation"),
    "Wind": ("m s-1", "Near-Surface Wind Speed"),
    "ASurf": ("m", "Surface Altitude"),
}

OUTPUT_TIME_UNITS = "hours since 1900-01-01 00:00:00"
OUTPUT_CALENDAR = "proleptic_gregorian"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download global WFDE5-CRU-GPCC forcing from CDS and assemble "
            "one merged NetCDF file per requested year (or year+month subset)."
        )
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--months",
        nargs="+",
        default=ALL_MONTHS,
        metavar="MM",
        help=(
            "Zero-padded months to request per year (default: all 12). "
            "Use a single month (e.g. --months 01) for a cheap first real "
            "test -- see PLAN.md's immediate next step."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("forcing/WFDE5_CRU_GPCC"),
        help="Where to write the assembled NetCDF file(s) (default: %(default)s)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("forcing/WFDE5_CRU_GPCC_cds_raw"),
        help="Scratch dir for downloads/extraction (default: %(default)s)",
    )
    parser.add_argument(
        "--version",
        default="3_0",
        help=(
            "CDS 'version' request key (default: %(default)s). Must be "
            "given explicitly -- omitting it causes CDS to reject the "
            "request despite the schema advertising a default."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep downloaded/extracted files in --raw-dir after assembly.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help=(
            "Assume --raw-dir/{year}/ is already populated with extracted "
            "NetCDF files and skip calling CDS (useful when iterating on "
            "the assembly step, or with synthetic fixtures in tests)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the CDS requests and output paths that would be used, "
            "then exit -- no CDS call, no disk write."
        ),
    )
    return parser.parse_args(argv)


def build_requests(year: int, months: list[str], version: str) -> list[dict]:
    # Two calls: CDS rejects a single request mixing reference_dataset
    # values, and "cru_and_gpcc" is only a valid combination with the two
    # precipitation variables (see module docstring). No "area" key -- CDS
    # has no server-side crop; the delivered field is always global.
    return [
        {
            "product": "wfde5",
            "variable": sorted(CDS_VARIABLES_CRU.keys()),
            "reference_dataset": "cru",
            "version": version,
            "year": [str(year)],
            "month": months,
        },
        {
            "product": "wfde5",
            "variable": sorted(CDS_VARIABLES_CRU_GPCC.keys()),
            "reference_dataset": "cru_and_gpcc",
            "version": version,
            "year": [str(year)],
            "month": months,
        },
    ]


def output_path_for(output_dir: Path, year: int, months: list[str]) -> Path:
    if months == ALL_MONTHS:
        return output_dir / f"WFDE5_CRU_GPCC_{year}.nc"
    return output_dir / f"WFDE5_CRU_GPCC_{year}_{months[0]}-{months[-1]}.nc"


def download_request(client, year: int, index: int, raw_dir: Path, request: dict) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"cds_{year}_{index}.download"
    print(f"[{year}] CDS request {index}: {request}")
    result = client.retrieve(DATASET, request)
    downloaded = result.download(str(target))
    return Path(downloaded)


def extract_archive(downloaded_path: Path, extract_dir: Path) -> list[Path]:
    if zipfile.is_zipfile(downloaded_path):
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(downloaded_path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".nc")]
            zf.extractall(extract_dir)
        # Return only the files this archive contains -- extract_dir is
        # shared across the multiple requests issued per year, so rglob'ing
        # the whole directory here would also pick up files extracted by
        # earlier requests into the same directory.
        return sorted(extract_dir / name for name in names)

    extract_dir.mkdir(parents=True, exist_ok=True)
    single_path = extract_dir / downloaded_path.with_suffix(".nc").name
    shutil.copy2(downloaded_path, single_path)
    return [single_path]


def identify_variable(nc_path: Path) -> str:
    with Dataset(nc_path) as ds:
        coord_names = {"time", "lat", "lon", "latitude", "longitude", "bnds"}
        data_vars = [v for v in ds.variables if v not in coord_names]
    for candidate in data_vars:
        if candidate in NAME_LOOKUP:
            return NAME_LOOKUP[candidate]
    raise ValueError(
        f"{nc_path}: could not identify a known forcing variable "
        f"among {data_vars}"
    )


def rebase_time(values: np.ndarray, units: str, calendar: str) -> np.ndarray:
    dates = num2date(values, units=units, calendar=calendar, only_use_cftime_datetimes=True)
    return np.asarray(
        date2num(dates, units=OUTPUT_TIME_UNITS, calendar=OUTPUT_CALENDAR),
        dtype=np.float64,
    )


def scan_timevarying(paths: list[Path], short_name: str) -> dict:
    """Read only the coordinates of each file -- never the bulk data.

    A year of one variable at 0.5 deg is 8784*360*720*4 = 9.1 GB, and
    assembling a year used to hold every dynamic variable at once (~73 GB),
    which the ECMWF session memory watchdog kills. The caller instead writes
    each file's data straight into the output in a second pass, so only one
    file's worth is ever resident. This returns everything needed to plan
    that pass: the ordered files and the global time axis they form.
    """
    entries = []
    for path in sorted(paths):
        with Dataset(path) as ds:
            time_var = ds.variables["time"]
            time_values = rebase_time(
                np.asarray(time_var[:], dtype=np.float64),
                time_var.units,
                getattr(time_var, "calendar", OUTPUT_CALENDAR),
            )
            lat = np.asarray(ds.variables["lat"][:])
            lon = np.asarray(ds.variables["lon"][:])
        if time_values.size > 1 and not np.all(np.diff(time_values) > 0):
            # The previous implementation globally argsort'ed the concatenated
            # axis, which would silently paper over this. Refuse instead: a
            # non-monotonic time axis inside one delivered file means the file
            # is not what we think it is.
            raise ValueError(f"{short_name}: {path.name} has a non-monotonic time axis")
        entries.append({"path": path, "time": time_values, "lat": lat, "lon": lon})

    entries.sort(key=lambda e: e["time"][0])

    ref_lat, ref_lon = entries[0]["lat"], entries[0]["lon"]
    for entry in entries:
        if entry["lat"].shape != ref_lat.shape or not np.allclose(entry["lat"], ref_lat):
            raise ValueError(f"{short_name}: inconsistent latitude grid across files")
        if entry["lon"].shape != ref_lon.shape or not np.allclose(entry["lon"], ref_lon):
            raise ValueError(f"{short_name}: inconsistent longitude grid across files")

    time_values = np.concatenate([e["time"] for e in entries])

    increments = np.diff(time_values)
    if not np.allclose(increments, 1.0, atol=1.0e-6, rtol=0.0):
        raise ValueError(
            f"{short_name}: concatenated time axis is not strictly hourly; "
            f"increments={np.unique(np.round(increments, 6))[:20]}"
        )

    return {
        "time": time_values,
        "lat": ref_lat,
        "lon": ref_lon,
        "entries": entries,
    }


def load_static(paths: list[Path], short_name: str) -> dict:
    with Dataset(sorted(paths)[0]) as ds:
        lat = np.asarray(ds.variables["lat"][:])
        lon = np.asarray(ds.variables["lon"][:])
        var = ds.variables[short_name]
        if "time" in var.dimensions:
            time_axis = var.dimensions.index("time")
            data = np.take(var[:], 0, axis=time_axis)
        else:
            data = var[:]
    return {"lat": lat, "lon": lon, "data": np.asarray(data).astype(np.float32)}


def _print_memory_estimate(
    n_dynamic_vars: int, n_time: int, n_lat: int, n_lon: int, max_block_steps: int
) -> None:
    whole_gb = (n_dynamic_vars * n_time * n_lat * n_lon * 4) / (1024**3)
    block_gb = (max_block_steps * n_lat * n_lon * 4) / (1024**3)
    print(
        f"  memory: streaming one input file at a time -- peak ~{block_gb:.2f} GiB "
        f"({max_block_steps} steps x {n_lat}x{n_lon} x 4 bytes). Holding all "
        f"{n_dynamic_vars} dynamic var(s) x {n_time} steps at once would have "
        f"needed ~{whole_gb:.1f} GiB."
    )


def assemble_period(year: int, months: list[str], nc_paths: list[Path], output_path: Path) -> None:
    files_by_var: dict[str, list[Path]] = {}
    for nc_path in nc_paths:
        short_name = identify_variable(nc_path)
        files_by_var.setdefault(short_name, []).append(nc_path)

    missing = SHORT_NAMES - files_by_var.keys()
    if missing:
        raise RuntimeError(f"[{year}] missing variables in download: {sorted(missing)}")

    dynamic = {}
    for short_name in sorted(SHORT_NAMES - STATIC_VARIABLES):
        print(f"[{year}] scanning {short_name} ({len(files_by_var[short_name])} file(s))")
        dynamic[short_name] = scan_timevarying(files_by_var[short_name], short_name)

    static = {}
    for short_name in sorted(STATIC_VARIABLES):
        print(f"[{year}] loading {short_name} (static)")
        static[short_name] = load_static(files_by_var[short_name], short_name)

    ref = next(iter(dynamic.values()))
    ref_time = ref["time"]
    ref_lat = ref["lat"]
    ref_lon = ref["lon"]

    _max_block_steps = max(
        e["time"].size for info in dynamic.values() for e in info["entries"]
    )
    _print_memory_estimate(
        len(dynamic), ref_time.size, ref_lat.size, ref_lon.size, _max_block_steps
    )

    for short_name, payload in dynamic.items():
        if payload["time"].shape != ref_time.shape or not np.allclose(
            payload["time"], ref_time
        ):
            raise ValueError(f"[{year}] {short_name}: time axis does not match other variables")
        if payload["lat"].shape != ref_lat.shape or not np.allclose(payload["lat"], ref_lat):
            raise ValueError(f"[{year}] {short_name}: latitude grid does not match other variables")
        if payload["lon"].shape != ref_lon.shape or not np.allclose(payload["lon"], ref_lon):
            raise ValueError(f"[{year}] {short_name}: longitude grid does not match other variables")

    # No assertion against a presumed global grid here -- longitude
    # convention and latitude ordering are open questions this repo has not
    # yet verified against real data (docs/forcing_variables.md). Report
    # what was actually delivered; forcing/validate_wfde5.py is where that
    # convention gets checked and trusted, not here.
    print(
        f"[{year}] delivered grid: {ref_lat.size} lat x {ref_lon.size} lon, "
        f"lat range [{ref_lat.min():.2f}, {ref_lat.max():.2f}], "
        f"lon range [{ref_lon.min():.2f}, {ref_lon.max():.2f}]"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    try:
        with Dataset(output_path, "w", format="NETCDF4_CLASSIC") as out_ds:
            out_ds.createDimension("time", None)
            out_ds.createDimension("lat", ref_lat.size)
            out_ds.createDimension("lon", ref_lon.size)

            lat_var = out_ds.createVariable("lat", "f4", ("lat",))
            lat_var[:] = ref_lat
            lat_var.units = "degrees_north"

            lon_var = out_ds.createVariable("lon", "f4", ("lon",))
            lon_var[:] = ref_lon
            lon_var.units = "degrees_east"

            time_var = out_ds.createVariable("time", "f8", ("time",))
            time_var[:] = ref_time
            time_var.units = OUTPUT_TIME_UNITS
            time_var.calendar = OUTPUT_CALENDAR

            for short_name, payload in dynamic.items():
                units, long_name = VARIABLE_ATTRS[short_name]
                # zlib/shuffle/complevel=4: without it these time-varying
                # variables (the bulk of each file) are stored uncompressed,
                # roughly doubling file size for no benefit -- see
                # liaise-ecland's get_liaise_forcing_05_cds.py, where this
                # was confirmed against the IPSL-mirror reference files.
                var = out_ds.createVariable(
                    short_name, "f4", ("time", "lat", "lon"), fill_value=1.0e20,
                    zlib=True, complevel=4, shuffle=True,
                )
                var.units = units
                var.long_name = long_name
                # Stream each input file straight into its slice of the
                # output instead of materialising the whole year first.
                offset = 0
                for entry in payload["entries"]:
                    with Dataset(entry["path"]) as in_ds:
                        block = np.asarray(in_ds.variables[short_name][:]).astype(
                            np.float32
                        )
                    if block.shape[0] != entry["time"].size:
                        raise ValueError(
                            f"[{year}] {short_name}: {entry['path'].name} has "
                            f"{block.shape[0]} records but {entry['time'].size} "
                            "timestamps"
                        )
                    var[offset:offset + block.shape[0]] = block
                    offset += block.shape[0]
                    del block
                if offset != ref_time.size:
                    raise ValueError(
                        f"[{year}] {short_name}: wrote {offset} records, "
                        f"expected {ref_time.size}"
                    )
                print(f"[{year}]   wrote {short_name}: {offset} records")

            for short_name, payload in static.items():
                units, long_name = VARIABLE_ATTRS[short_name]
                var = out_ds.createVariable(short_name, "f4", ("lat", "lon"))
                var[:] = payload["data"]
                var.units = units
                var.long_name = long_name

            height1 = out_ds.createVariable("Height_Lev1", "f4")
            height1[...] = HEIGHT_LEV1
            height1.units = "m"
            height1.long_name = "Height_scalar_variables"

            heightuv = out_ds.createVariable("Height_Levuv", "f4")
            heightuv[...] = HEIGHT_LEVUV
            heightuv.units = "m"
            heightuv.long_name = "Height_wind"

            out_ds.Conventions = "CF-1.7"
            out_ds.source = "CDS derived-near-surface-meteorological-variables (WFDE5)"
            out_ds.comment = (
                "Downloaded via forcing/download_wfde5.py, global 0.5 degree, "
                "not cropped to any region."
            )

        print(
            f"CREATED {output_path}\n"
            f"  records: {ref_time.size}\n"
            f"  time: {ref_time[0]} .. {ref_time[-1]} [{OUTPUT_TIME_UNITS}]\n"
            f"  grid: {ref_lat.size} x {ref_lon.size}"
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.end_year < args.start_year:
        raise ValueError("--end-year must be >= --start-year")

    months = sorted(set(args.months))
    for m in months:
        if m not in ALL_MONTHS:
            raise ValueError(f"invalid --months value: {m!r} (expected zero-padded 01..12)")

    if args.dry_run:
        for year in range(args.start_year, args.end_year + 1):
            output_path = output_path_for(args.output_dir, year, months)
            print(f"[{year}] would write: {output_path}")
            for request in build_requests(year, months, args.version):
                print(f"[{year}] would request: {request}")
        return 0

    client = None
    if not args.skip_download:
        import cdsapi

        client = cdsapi.Client()

    for year in range(args.start_year, args.end_year + 1):
        output_path = output_path_for(args.output_dir, year, months)
        if output_path.exists() and not args.overwrite:
            print(f"SKIP existing: {output_path}")
            continue

        raw_year_dir = args.raw_dir / str(year)

        if args.skip_download:
            nc_paths = sorted(raw_year_dir.rglob("*.nc"))
            if not nc_paths:
                raise FileNotFoundError(
                    f"--skip-download given but no .nc files found under {raw_year_dir}"
                )
        else:
            nc_paths = []
            for index, request in enumerate(build_requests(year, months, args.version)):
                downloaded = download_request(client, year, index, args.raw_dir, request)
                nc_paths.extend(extract_archive(downloaded, raw_year_dir))

        assemble_period(year, months, nc_paths, output_path)

        if not args.keep_raw:
            shutil.rmtree(raw_year_dir, ignore_errors=True)
            downloaded_glob = list(args.raw_dir.glob(f"cds_{year}_*.download*"))
            for path in downloaded_glob:
                path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
