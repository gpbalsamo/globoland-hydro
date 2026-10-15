"""Shared helpers for wfde5-glofas: paths, the global GloFAS grid, and the exact WFDE5 nesting.

This is the GLOBAL instance of the <exp>-glofas family, so most of that family's shared code --
the mask rule, contained_basins(), last_in_box(), the 0.05 deg window slicing -- has no analogue
here and is deliberately absent rather than carried along unused. A global run has no clip: the
operational MaskMap and static maps are used exactly as they are.

Grids
-----
GloFAS v5: 3000 lat x 7200 lon at 0.05 deg, latitude DESCENDING, centres at x.025/x.075,
spanning 90N..60S and 180W..180E.
WFDE5:     360 lat x 720 lon at 0.5 deg, latitude ASCENDING, centres at x.25/x.75, 90S..90N.

The two are edge-aligned 10:1, so the GloFAS domain is covered by WFDE5 rows 60..359 (lat
-59.75..89.75) and all 720 columns, and nearest-neighbour regridding is EXACT block replication
(np.repeat x10). That is conservative for precipitation, which is why tp is regridded that way and
not bilinearly. nesting() proves the alignment from the two coordinate vectors and refuses if it
does not hold, so a changed grid cannot pass silently.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np

RES_G = 0.05        # GloFAS
RES_W = 0.5         # WFDE5
RATIO = 10          # RES_W / RES_G
EPS = 1e-6

REPO = Path(__file__).resolve().parent.parent


def load_paths(f: Path | None = None) -> dict:
    """config/paths.yaml, with ${key} and ${repo_root} expanded. Deliberately a 12-line parser:
    the file is flat key: value, and a yaml dependency for that is not worth a required import."""
    f = f or REPO / "config" / "paths.yaml"
    if not f.exists():
        raise FileNotFoundError(f"{f} missing -- copy config/paths.example.yaml and edit it")
    d: dict[str, str] = {}
    for line in f.read_text().splitlines():
        line = line.split("#", 1)[0].strip() if not line.strip().startswith("#") else ""
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip().strip('"').strip("'")
        v = v.replace("${repo_root}", str(REPO))
        for prev, pv in d.items():
            v = v.replace("${%s}" % prev, pv)
        if "${" in v:
            raise ValueError(f"{f}: unresolved reference in {k}: {v}")
        d[k.strip()] = v
    return d


def work(paths: dict) -> Path:
    w = Path(paths["work_dir"])
    w.mkdir(parents=True, exist_ok=True)
    return w


def product(paths: dict) -> Path:
    p = Path(paths["product_dir"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def glofas_grid(paths: dict) -> tuple[np.ndarray, np.ndarray]:
    """lat (descending) and lon of the operational global MaskMap."""
    from netCDF4 import Dataset
    with Dataset(mask_map(paths)) as d:
        return np.asarray(d["lat"][:], "f8"), np.asarray(d["lon"][:], "f8")


def mask_map(paths: dict) -> str:
    """The operational global MaskMap, used as-is (it is what the reanalysis settings point at)."""
    return str(Path(paths["glofas_staticmaps"]) / "template_Global_03min.nc")


def nesting(latw: np.ndarray, lonw: np.ndarray, latg: np.ndarray, long_: np.ndarray):
    """Prove the 10:1 edge alignment and return the WFDE5 row slice covering the GloFAS domain.

    Returns (rows, flip) where rows is a slice into the WFDE5 latitude axis and flip is True when
    that slice must be reversed to run in the GloFAS (descending) direction. Raises if the GloFAS
    grid is not exactly RATIO x RES_G inside the WFDE5 cells, which is the assumption that makes
    np.repeat conservative.
    """
    for name, v, res in (("WFDE5 lat", latw, RES_W), ("WFDE5 lon", lonw, RES_W),
                         ("GloFAS lat", latg, RES_G), ("GloFAS lon", long_, RES_G)):
        step = np.diff(v)
        if not np.allclose(np.abs(step), res, atol=1e-9) or not (np.all(step > 0) or np.all(step < 0)):
            raise ValueError(f"{name}: not a monotonic {res} deg axis")
    if len(long_) != len(lonw) * RATIO:
        raise ValueError(f"lon: {len(long_)} GloFAS cells is not {RATIO}x{len(lonw)}")
    # every GloFAS lon centre must sit inside the WFDE5 cell it block-replicates from
    want = np.repeat(lonw, RATIO)
    if not np.allclose(np.abs(long_ - want), RES_G * np.tile(np.abs(np.arange(RATIO) - 4.5), len(lonw)), atol=1e-9):
        raise ValueError("lon: GloFAS centres are not the 10 sub-centres of the WFDE5 cells")
    # the GloFAS latitude span, as WFDE5 rows, in WFDE5 axis order
    south, north = latg.min() - RES_G / 2, latg.max() + RES_G / 2
    sel = np.where((latw > south - EPS) & (latw < north + EPS))[0]
    if len(sel) * RATIO != len(latg) or np.any(np.diff(sel) != 1):
        raise ValueError(f"lat: GloFAS span needs {len(latg) / RATIO} WFDE5 rows, found {len(sel)}")
    rows = slice(int(sel[0]), int(sel[-1]) + 1)
    flip = (latw[1] - latw[0]) * (latg[1] - latg[0]) < 0
    return rows, flip


def block_replicate(a: np.ndarray) -> np.ndarray:
    """0.5 deg -> 0.05 deg by exact 10x10 replication: conservative, the right choice for a rate."""
    return np.repeat(np.repeat(a, RATIO, axis=-2), RATIO, axis=-1)


def bilinear_weights(src: np.ndarray, dst: np.ndarray):
    """Indices and weight for 1-D linear interpolation of src onto dst, clamped at the ends.

    Separable bilinear (lat then lon) costs 3000x720 + 3000x7200 work instead of 21.6e6 scattered
    query points, which is what makes a global day cheap. Clamping reproduces the family's
    constant extrapolation over the outer half coarse cell.
    """
    src = np.asarray(src, "f8")
    asc = src[1] > src[0]
    s = src if asc else src[::-1]
    x = np.clip(np.asarray(dst, "f8"), s[0], s[-1])
    i1 = np.clip(np.searchsorted(s, x, side="left"), 1, len(s) - 1)
    i0 = i1 - 1
    w = (x - s[i0]) / (s[i1] - s[i0])
    if not asc:
        i0, i1 = len(src) - 1 - i0, len(src) - 1 - i1
    return i0, i1, w


def interp_2d(a: np.ndarray, latw, lonw, latg, long_) -> np.ndarray:
    """Separable bilinear 0.5 -> 0.05 deg for a single 2-D field."""
    i0, i1, wy = bilinear_weights(latw, latg)
    j0, j1, wx = bilinear_weights(lonw, long_)
    tmp = (1.0 - wy)[:, None] * a[i0, :] + wy[:, None] * a[i1, :]
    return ((1.0 - wx)[None, :] * tmp[:, j0] + wx[None, :] * tmp[:, j1]).astype("f4")
