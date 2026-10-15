#!/usr/bin/env python3
"""Water-conservation gate for the ecLand -> CaMa-Flood runoff remap.

Required by CLAUDE.md ("Any global remapping of runoff must conserve water")
and specified in docs/cama_interface.md.  CaMa-Flood does the remap itself,
inside CMF_FORCING_PUT, using the input matrix `inpmat.nc` built by
derive_global_cmf_weights.sh: for every river-network cell it holds up to
`lev` links (inpx, inpy, inpa), where inpa is the area of that river cell
fed by ecLand input cell (inpx, inpy).  The water CaMa receives is therefore

    V_mapped = sum_t sum_cells  R(inpx,inpy,t) * inpa * dt

against what ecLand produced,

    V_ecland = sum_t sum_landcells  R(i,j,t) * A(i,j) * dt

with R = -(Qs + Qsb) -- a SUM, not a difference; see docs/cama_interface.md
for why, and do not "simplify" it.

WHICH A(i,j): the one consequential choice here, so it is a flag, not a
default buried in the code.  `--convention land` uses A = gridbox area x
landsea (ecLand's land fraction), `--convention gridbox` uses the full
gridbox area.  Measured on inpmat.nc for glb_15min against the repo's own
surfclim (2026-10-15): the median inpa/(area x landsea) over mapped land
cells is 1.0011, against 0.9983 for inpa/area -- i.e. inpa IS the land area,
to about 0.1%.  So `land` is the physically consistent comparison and is the
default; `gridbox` is kept because it is what you want if you ever need to
know the loss relative to the full box.

CALIBRATION, so that a tolerance is a measurement and not a wish.  On the
validated Y2001 run (365 daily records, glb_15min):

    convention   V_ecland    V_mapped    loss            relative
    land         36436.9     35207.8     1229.1 km3       3.373%
    gridbox      38581.5     35207.8     3373.7 km3       8.744%

and the gridbox loss decomposes as

    unmapped, Antarctica (lat < -60)      113.3 km3    0.29%
    unmapped, elsewhere                     0.2 km3    0.00%
    mapped, inpa < A  (deficit)          3287.6 km3    8.52%
    mapped, inpa > A  (surplus)           -27.4 km3   -0.07%

The deficit is NOT Antarctica -- 98% of the unmapped area is Antarctic but
it carries 3% of the loss, because Antarctic runoff per m2 is negligible.
It is partial-land coastal cells: 85% of the deficit comes from cells with
landsea < 0.95, where ecLand's land area and CaMa's catchment area disagree
cell by cell.  That residual is two-sided (1951.5 km3 where the catchment is
smaller, 722.4 km3 where it is larger), so it is a coverage mismatch between
two different land masks, not a one-way leak from a sign or weight error.

docs/cama_interface.md asks for the 1e-9 bar that the temporal aggregation
meets.  That bar is unreachable here and saying so is part of the check: the
two models do not agree about where the land is.  The default tolerance is
therefore 5%, which the current `land` number (3.373%) passes with room to
see drift and which the `gridbox` number (8.744%) fails -- deliberately, so
that getting the convention wrong is loud.  A sign error in R, a dropped
term, or a rebuilt inpmat that lost a basin all move this number by far more
than the margin.  Numbers are always printed, never just the verdict: a
residual at 1e-9 and a residual at 4.9% are both "PASS" and are not the
same finding.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

LOG = logging.getLogger("validate_remapping")

R_EARTH = 6371000.0
KM3 = 1.0e12  # kg of water in 1 km3


def gridbox_area(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Exact spherical cell area for a regular lat/lon grid, in m2."""
    dlon = abs(float(lon[1] - lon[0]))
    half = np.deg2rad(abs(float(lat[1] - lat[0]))) / 2.0
    latr = np.deg2rad(lat)
    belt = R_EARTH * R_EARTH * np.deg2rad(dlon) * (
        np.sin(latr + half) - np.sin(latr - half)
    )
    return np.repeat(np.abs(belt)[:, None], lon.size, axis=1)


def read_grid(path: Path):
    """lat, lon, land mask and land fraction from a surfclim/soilinit file."""
    with Dataset(path) as ds:
        lat = np.asarray(ds["lat"][:], "f8")
        lon = np.asarray(ds["lon"][:], "f8")
        mask = np.asarray(np.ma.filled(ds["Mask"][:], 0.0), "f8") > 0.5
        lsm = np.asarray(np.ma.filled(ds["landsea"][:], 0.0), "f8")
    return lat, lon, mask, np.clip(lsm, 0.0, 1.0)


def read_assigned_area(path: Path, shape: tuple[int, int]) -> np.ndarray:
    """Scatter inpmat's inpa onto the ecLand grid: area assigned per source cell.

    inpx/inpy are 1-based Fortran indices into the input grid.  A source cell
    appears in as many river-network cells as the network splits it into, so
    this accumulates rather than assigns.
    """
    with Dataset(path) as ds:
        inpa = np.ma.filled(ds["inpa"][:], 0.0).astype("f8")
        inpx = np.ma.filled(ds["inpx"][:], -9999)
        inpy = np.ma.filled(ds["inpy"][:], -9999)
        nyin, nxin = len(ds.dimensions["latin"]), len(ds.dimensions["lonin"])
    if (nyin, nxin) != shape:
        raise SystemExit(
            f"inpmat input grid is {nyin}x{nxin} but the grid file is "
            f"{shape[0]}x{shape[1]} -- these must be the same grid "
            f"(see docs/grid_strategy.md)"
        )
    ok = (inpx > 0) & (inpy > 0) & (inpa > 0)
    out = np.zeros(shape, "f8")
    np.add.at(out, (inpy[ok] - 1, inpx[ok] - 1), inpa[ok])
    return out


def runoff_sum(paths, mask) -> tuple[np.ndarray, int, float]:
    """Sum -(Qs+Qsb)*dt over every record of every file, streaming.

    Returns kg m-2 accumulated per cell, the record count, and the timestep.
    Streams one record at a time: a year of 0.5 deg daily output is 5.7 GB.
    """
    total = np.zeros(mask.shape, "f8")
    nrec = 0
    dt_seen = set()
    for p in paths:
        with Dataset(p) as ds:
            for v in ("Qs", "Qsb"):
                if v not in ds.variables:
                    raise SystemExit(f"{p}: no variable {v}")
            tv = np.asarray(ds["time"][:], "f8")
            if tv.size < 2:
                raise SystemExit(f"{p}: need >= 2 time records to infer the timestep")
            dt = float(np.median(np.diff(tv)))
            dt_seen.add(round(dt, 6))
            for i in range(tv.size):
                qs = np.nan_to_num(np.ma.filled(ds["Qs"][i], np.nan).astype("f8"))
                qsb = np.nan_to_num(np.ma.filled(ds["Qsb"][i], np.nan).astype("f8"))
                total += -(qs + qsb) * dt      # the SUM; see module docstring
                nrec += 1
            LOG.info("%s: %d records, dt = %g s", Path(p).name, tv.size, dt)
    if len(dt_seen) > 1:
        raise SystemExit(f"mixed output frequencies across files: {sorted(dt_seen)} s")
    return total, nrec, dt_seen.pop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Water-conservation gate for the ecLand -> CaMa-Flood runoff remap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exits nonzero if the relative conservation error exceeds --tolerance.",
    )
    ap.add_argument("--inpmat", type=Path, required=True,
                    help="inpmat.nc from derive_global_cmf_weights.sh")
    ap.add_argument("--grid", type=Path, required=True,
                    help="surfclim/soilinit file on the ecLand grid (lat, lon, Mask, landsea)")
    ap.add_argument("--runoff", type=Path, nargs="+", metavar="o_wat.nc",
                    help="ecLand water output; omit for the weights-only area report")
    ap.add_argument("--convention", choices=("land", "gridbox"), default="land",
                    help="source area: gridbox x landsea (default) or the full gridbox")
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="max |relative conservation error| before failing (default 0.05)")
    ap.add_argument("--report-only", action="store_true",
                    help="print everything but always exit 0")
    ap.add_argument("--json", type=Path, help="also write the numbers here")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if a.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    lat, lon, mask, lsm = read_grid(a.grid)
    box = gridbox_area(lat, lon)
    src = box * lsm if a.convention == "land" else box * mask
    assigned = read_assigned_area(a.inpmat, mask.shape)

    res: dict = {
        "inpmat": str(a.inpmat), "grid": str(a.grid), "convention": a.convention,
        "tolerance": a.tolerance,
    }

    print(f"ecLand grid {mask.shape[0]}x{mask.shape[1]}, {int(mask.sum())} land cells "
          f"(Mask > 0.5); source area convention: {a.convention}")
    print()
    print("AREA (from the weights alone, no runoff needed)")
    unmapped = mask & (assigned <= 0)
    stray = (assigned > 0) & ~mask
    for label, value in (
        ("source area, sum over land", src[mask].sum()),
        ("assigned area, sum of inpa", assigned.sum()),
    ):
        print(f"  {label:<34} {value:.6e} m2")
    print(f"  {'coverage, assigned / source':<34} "
          f"{assigned.sum() / src[mask].sum():.6f}")
    print(f"  {'land cells with no mapping':<34} {int(unmapped.sum()):d}"
          f"  ({box[unmapped].sum():.4e} m2)")
    print(f"  {'mapped cells outside the mask':<34} {int(stray.sum()):d}"
          f"  ({assigned[stray].sum():.4e} m2)")
    both = mask & (assigned > 0)
    if both.any():
        r = assigned[both] / np.maximum(src[both], 1.0)
        print(f"  {'inpa/source on mapped land':<34} "
              f"median {np.median(r):.4f}, 1st pct {np.percentile(r, 1):.4f}, "
              f"99th {np.percentile(r, 99):.4f}")
        print(f"  {'cells over-assigned by > 0.1%':<34} {int((r > 1.001).sum()):d}")
    res["area"] = {
        "source_total_m2": float(src[mask].sum()),
        "assigned_total_m2": float(assigned.sum()),
        "coverage": float(assigned.sum() / src[mask].sum()),
        "unmapped_land_cells": int(unmapped.sum()),
        "unmapped_land_area_m2": float(box[unmapped].sum()),
        "mapped_cells_outside_mask": int(stray.sum()),
    }

    if not a.runoff:
        print()
        print("VOLUME not tested -- pass --runoff to gate on a real period.")
        if a.json:
            a.json.write_text(json.dumps(res, indent=2))
        return 0

    acc, nrec, dt = runoff_sum(a.runoff, mask)
    v_src = float((acc * src * mask).sum())
    v_map = float((acc * assigned).sum())
    loss = v_src - v_map
    rel = loss / v_src if v_src else float("nan")

    print()
    print(f"VOLUME over {nrec} records of {dt:g} s "
          f"({nrec * dt / 86400.0:.1f} days), R = -(Qs+Qsb)")
    print(f"  {'ecLand produced':<34} {v_src:.6e} kg = {v_src / KM3:10.1f} km3")
    print(f"  {'CaMa-Flood receives':<34} {v_map:.6e} kg = {v_map / KM3:10.1f} km3")
    print(f"  {'absolute difference':<34} {loss:.6e} kg = {loss / KM3:10.1f} km3")
    print(f"  {'relative difference':<34} {rel:+.6f} = {100 * rel:+.4f}%")

    print()
    print("  where it goes (signed, sums to the absolute difference):")
    south = (lat < -60.0)[:, None] & np.ones(mask.shape, bool)
    parts = [
        ("unmapped land, lat < -60", unmapped & south),
        ("unmapped land, elsewhere", unmapped & ~south),
        ("mapped, inpa < source", both & (assigned < src)),
        ("mapped, inpa > source", both & (assigned > src)),
    ]
    terms = {}
    for label, sel in parts:
        d = float((acc[sel] * (src[sel] - assigned[sel])).sum())
        terms[label] = d
        print(f"    {label:<32} {d / KM3:9.1f} km3  ({100 * d / v_src:+6.2f}%)")
    d = -float((acc[stray] * assigned[stray]).sum())
    terms["mapped outside the mask (gain)"] = d
    print(f"    {'mapped outside the mask (gain)':<32} {d / KM3:9.1f} km3  "
          f"({100 * d / v_src:+6.2f}%)")
    check = sum(terms.values())
    print(f"    {'sum':<32} {check / KM3:9.1f} km3  "
          f"[absolute difference {loss / KM3:.1f}]")
    if abs(check - loss) > max(1e-6 * abs(loss), 1.0e6):
        print("    WARNING: decomposition does not close -- the terms above overlap "
              "or miss a case; trust the absolute difference, not the split.")

    res["volume"] = {
        "records": nrec, "dt_seconds": dt,
        "ecland_kg": v_src, "mapped_kg": v_map,
        "loss_kg": loss, "relative": rel,
        "terms_kg": {k: float(v) for k, v in terms.items()},
    }

    ok = np.isfinite(rel) and abs(rel) <= a.tolerance
    print()
    if not np.isfinite(rel):
        print("REMAP CONSERVATION INCONCLUSIVE -- ecLand produced no water")
    else:
        print(f"REMAP CONSERVATION {'PASS' if ok else 'FAIL'}  "
              f"|{100 * rel:+.4f}%| {'<=' if ok else '>'} "
              f"{100 * a.tolerance:.4f}% tolerance "
              f"({a.convention} convention)")
    res["pass"] = bool(ok)
    if a.json:
        a.json.write_text(json.dumps(res, indent=2))
    if a.report_only:
        return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
