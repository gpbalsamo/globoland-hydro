#!/usr/bin/env python3
"""Flip a NetCDF file's latitude axis (and every variable that has one) to
ascending (south-to-north) order, in place.

Why this exists: ecland_create_forcing.py's 2D pipeline (extract_create_
inicond_2D.bash -> interp_ll.py) writes surfclim/soilinit in native MARS/GRIB
order, which is north-to-south (descending). WFDE5 (forcing/download_wfde5.py)
is south-to-north (ascending) -- confirmed against real downloaded data, see
docs/forcing_variables.md. The project's own grid invariant
(docs/grid_strategy.md, CLAUDE.md "Grid invariants") requires surfclim,
soilinit and the forcing to describe exactly the same grid, ascending vs.
descending latitude included -- this is not optional and not automatically
handled by the newer tool the way the older, now-unusable init_clim.py
(grib2nc_LL's flip_lat=True) used to.

Usage:
    python3 init_clim/flip_latitude_to_ascending.py surfclim_GLOBAL_1988-2024.nc
    python3 init_clim/flip_latitude_to_ascending.py --dry-run surfinit_GLOBAL_1988-2024.nc
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def needs_flip(lat: np.ndarray) -> bool:
    if lat.size < 2:
        return False
    return bool(lat[0] > lat[-1])


def flip_in_place(path: Path) -> bool:
    """Return True if a flip was applied, False if the file was already ascending."""
    with Dataset(path, "r") as ds:
        if "lat" not in ds.variables:
            raise ValueError(f"{path}: no 'lat' variable found")
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)

    if not needs_flip(lat):
        print(f"{path}: lat already ascending, nothing to do")
        return False

    lat_dim_names = set()
    with Dataset(path, "r") as ds:
        for name, var in ds.variables.items():
            if "lat" in var.dimensions:
                lat_dim_names.add(name)

    tmp_path = path.with_suffix(path.suffix + ".flipping")
    shutil.copy2(path, tmp_path)

    with Dataset(tmp_path, "r+") as ds:
        lat_axis_name = None
        for dim in ds.dimensions:
            if dim == "lat" or dim.lower() == "latitude":
                lat_axis_name = dim
                break
        if lat_axis_name is None:
            raise ValueError(f"{path}: no latitude dimension found among {list(ds.dimensions)}")

        for name, var in ds.variables.items():
            if lat_axis_name not in var.dimensions:
                continue
            axis = var.dimensions.index(lat_axis_name)
            data = var[:]
            flipped = np.flip(data, axis=axis)
            var[:] = flipped

        ds.history = getattr(ds, "history", "") + " | latitude flipped to ascending by flip_latitude_to_ascending.py"

    tmp_path.replace(path)
    print(f"{path}: flipped {len(lat_dim_names)} variable(s) with a lat dimension to ascending order")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Report whether a flip is needed, do not modify anything.")
    args = parser.parse_args(argv)

    for path in args.files:
        with Dataset(path, "r") as ds:
            lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        if args.dry_run:
            status = "NEEDS FLIP" if needs_flip(lat) else "already ascending"
            print(f"{path}: {status} (lat[0]={lat[0]:.3f}, lat[-1]={lat[-1]:.3f})")
            continue
        flip_in_place(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
