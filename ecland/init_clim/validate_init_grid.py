#!/usr/bin/env python3
"""Compare the forcing grid, surfclim grid, and soilinit grid pairwise and
return PASS only when they agree exactly -- see docs/grid_strategy.md and
CLAUDE.md's "Grid invariants": surfclim, soilinit and the ecLand forcing
files must describe exactly the same grid, never assumed, always checked.

Hard requirements (exit 1 if violated): identical lat/lon shapes and values
(same ordering, same convention) across all three files.

Soft/informational (never fails the exit code, always printed): land-mask
agreement between surfclim's own land-sea field and the forcing's masked
coverage. These are independently-derived masks (WFDE5's own vs. ERA5's
operational LSM) and are not guaranteed to agree cell-for-cell even when both
are correct -- report the real percentage, do not assert equality.

Usage:
    python3 init_clim/validate_init_grid.py \
        --forcing forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_1988_01-01.nc \
        --surfclim init_clim/work/output/wfde5-ecland/surfclim_GLOBAL_1988-2024.nc \
        --soilinit init_clim/work/output/wfde5-ecland/surfinit_GLOBAL_1988-2024.nc
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset


def read_latlon(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with Dataset(path) as ds:
        lat = np.asarray(ds.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["lon"][:], dtype=np.float64)
    return lat, lon


def compare_grids(name_a: str, lat_a: np.ndarray, lon_a: np.ndarray,
                   name_b: str, lat_b: np.ndarray, lon_b: np.ndarray) -> list[str]:
    errors = []
    if lat_a.shape != lat_b.shape:
        errors.append(f"{name_a} vs {name_b}: lat shape {lat_a.shape} != {lat_b.shape}")
    elif not np.allclose(lat_a, lat_b, atol=1e-6):
        errors.append(
            f"{name_a} vs {name_b}: lat values differ "
            f"({name_a}[0]={lat_a[0]:.4f}..{lat_a[-1]:.4f}, "
            f"{name_b}[0]={lat_b[0]:.4f}..{lat_b[-1]:.4f}) -- check ascending/descending order"
        )
    if lon_a.shape != lon_b.shape:
        errors.append(f"{name_a} vs {name_b}: lon shape {lon_a.shape} != {lon_b.shape}")
    elif not np.allclose(lon_a, lon_b, atol=1e-6):
        errors.append(
            f"{name_a} vs {name_b}: lon values differ "
            f"({name_a}[0]={lon_a[0]:.4f}..{lon_a[-1]:.4f}, "
            f"{name_b}[0]={lon_b[0]:.4f}..{lon_b[-1]:.4f}) -- check -180..180 vs 0..360 convention"
        )
    return errors


def report_landmask_agreement(forcing_path: Path, surfclim_path: Path) -> None:
    """Informational only -- see module docstring. Never affects the exit code."""
    with Dataset(forcing_path) as ds:
        candidate = next((v for v in ("Tair", "Rainf", "Snowf") if v in ds.variables), None)
        if candidate is None:
            print("  (no known forcing variable found to derive a land mask from -- skipping)")
            return
        forcing_var = ds.variables[candidate][0]
        forcing_masked = np.ma.getmaskarray(forcing_var)

    with Dataset(surfclim_path) as ds:
        if "landsea" not in ds.variables:
            print("  (surfclim has no 'landsea' variable -- skipping)")
            return
        landsea = np.asarray(ds.variables["landsea"][:])
        surfclim_land = landsea >= 0.5

    if forcing_masked.shape != surfclim_land.shape:
        print(f"  land-mask comparison skipped: shapes differ {forcing_masked.shape} vs {surfclim_land.shape}")
        return

    forcing_land = ~forcing_masked
    agree = np.count_nonzero(forcing_land == surfclim_land)
    total = forcing_land.size
    pct = 100.0 * agree / total
    print(
        f"  land-mask agreement (forcing '{candidate}' coverage vs. surfclim 'landsea'): "
        f"{pct:.1f}% of {total} cells -- informational only, independently-derived masks "
        "are not required to match bit-for-bit (see module docstring)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forcing", required=True, type=Path)
    parser.add_argument("--surfclim", required=True, type=Path)
    parser.add_argument("--soilinit", required=True, type=Path)
    args = parser.parse_args(argv)

    forcing_lat, forcing_lon = read_latlon(args.forcing)
    surfclim_lat, surfclim_lon = read_latlon(args.surfclim)
    soilinit_lat, soilinit_lon = read_latlon(args.soilinit)

    errors = []
    errors += compare_grids("forcing", forcing_lat, forcing_lon, "surfclim", surfclim_lat, surfclim_lon)
    errors += compare_grids("forcing", forcing_lat, forcing_lon, "soilinit", soilinit_lat, soilinit_lon)
    errors += compare_grids("surfclim", surfclim_lat, surfclim_lon, "soilinit", soilinit_lat, soilinit_lon)

    print(f"forcing:  {forcing_lat.size} lat x {forcing_lon.size} lon "
          f"(lat {forcing_lat[0]:.2f}..{forcing_lat[-1]:.2f}, lon {forcing_lon[0]:.2f}..{forcing_lon[-1]:.2f})")
    print(f"surfclim: {surfclim_lat.size} lat x {surfclim_lon.size} lon "
          f"(lat {surfclim_lat[0]:.2f}..{surfclim_lat[-1]:.2f}, lon {surfclim_lon[0]:.2f}..{surfclim_lon[-1]:.2f})")
    print(f"soilinit: {soilinit_lat.size} lat x {soilinit_lon.size} lon "
          f"(lat {soilinit_lat[0]:.2f}..{soilinit_lat[-1]:.2f}, lon {soilinit_lon[0]:.2f}..{soilinit_lon[-1]:.2f})")

    print()
    report_landmask_agreement(args.forcing, args.surfclim)

    print()
    if errors:
        print("FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("PASS: forcing, surfclim, and soilinit describe exactly the same grid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
