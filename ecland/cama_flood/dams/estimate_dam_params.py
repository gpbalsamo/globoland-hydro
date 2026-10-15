#!/usr/bin/env python3
"""Build CaMa-Flood dam_params.csv from a naturalised discharge archive.

Method follows CaMa-Flood's own pipeline (see CaMa-Flood-GPU
cmfgpu/params/estimate_dam_params.py):

  1. annual maximum and annual mean discharge at each dam's river cell
  2. Gumbel distribution fitted by L-moments -> 100-year return period Q100
  3. Qf = 0.3 * Q100   (flood-control release),  Qn = mean discharge
  4. FldVol / ConVol split from GRanD total capacity (37% flood control)

Index convention, verified against the archive rather than assumed: the CaMa
output grid is 1440x720 at 0.25 deg with lat running NORTH to SOUTH
(lat[0]=+89.875), so a dam's 1-based (ix,iy) maps to python [iy-1, ix-1].
Checked on GRanD ID 2 (Mayo, 63.771N 135.371W, ix=180 iy=105) -> cell centre
63.875N 135.125W, i.e. within half a cell.

Only dams allocated to the river network are used. The 3127 "small" dams from
allocate_dam carry area_CaMa = -888 (no drainage-area match) for every single
one, so upreal -- which the Hanazaki H22 rule divides by -- cannot be supplied
without inventing it. They are 3.3% of global capacity, median 30 MCM, and are
deliberately excluded; see cama_flood/dams/README for the decision.
"""
import argparse, glob, sys
import numpy as np
import netCDF4 as nc


def load_dams(path):
    with open(path) as f:
        hdr = f.readline().split()
        rows = [l.split() for l in f if len(l.split()) >= 11]
    col = {k: hdr.index(k) for k in
           ("ID", "lat", "lon", "area_CaMa", "ix", "iy", "cap_mcm", "year")}
    dams = []
    for r in rows:
        dams.append(dict(
            ID=int(r[col["ID"]]), lat=float(r[col["lat"]]), lon=float(r[col["lon"]]),
            area=float(r[col["area_CaMa"]]), ix=int(r[col["ix"]]), iy=int(r[col["iy"]]),
            cap=float(r[col["cap_mcm"]]), year=int(r[col["year"]]),
            name=r[col["year"] + 1] if len(r) > col["year"] + 1 else "dam%d" % int(r[col["ID"]]),
        ))
    return dams


def gumbel_l_moments(x):
    """Gumbel parameters by L-moments. Returns (loc, scale)."""
    x = np.sort(np.asarray(x, dtype="f8"))
    n = x.size
    if n < 2:
        return float(x[0]) if n else 0.0, 0.0
    # sample L-moments l1, l2 via probability-weighted moments
    j = np.arange(1, n + 1)
    b0 = x.mean()
    b1 = np.sum((j - 1) / (n - 1) * x) / n
    l1, l2 = b0, 2 * b1 - b0
    scale = l2 / np.log(2.0) if l2 > 0 else 0.0
    loc = l1 - 0.5772156649 * scale
    return loc, scale


def q_return(loc, scale, T):
    """Gumbel quantile for return period T years."""
    return loc - scale * np.log(-np.log(1.0 - 1.0 / T))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cmf-glob", required=True,
                   help="glob for per-year CaMa output dirs, e.g. 'run/work/cmf_output_Y*'")
    p.add_argument("--dam-list", default="cama_flood/dams/dam_alloc_river.txt")
    p.add_argument("--out", default="cama_flood/dams/dam_params.csv")
    p.add_argument("--return-period", type=float, default=100.0)
    p.add_argument("--qf-factor", type=float, default=0.3,
                   help="Qf = qf_factor * Q(T); CaMa's own pipeline uses 0.3")
    p.add_argument("--fld-fraction", type=float, default=0.37,
                   help="flood-control share of total capacity when no GRSAD/ReGeom data")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    dirs = sorted(glob.glob(a.cmf_glob))
    if not dirs:
        sys.exit(f"no CaMa output directories matched {a.cmf_glob!r}")
    dams = load_dams(a.dam_list)
    print(f"dams on river network : {len(dams)}")
    print(f"discharge years found : {len(dirs)}  ({dirs[0].split('_')[-1]} .. {dirs[-1].split('_')[-1]})")

    ny = len(dirs)
    nd = len(dams)
    amax = np.full((ny, nd), np.nan)
    amean = np.full((ny, nd), np.nan)
    iy = np.array([d["iy"] - 1 for d in dams])
    ix = np.array([d["ix"] - 1 for d in dams])

    for k, dd in enumerate(dirs):
        f = nc.Dataset(f"{dd}/o_totout.nc")
        v = f.variables["totout"]
        nt = v.shape[0]
        mx = np.full(nd, -np.inf)
        sm = np.zeros(nd)
        CH = 30                      # timesteps per read; one-at-a-time is ~10x slower
        for t0 in range(0, nt, CH):
            blk = np.ma.filled(v[t0:t0 + CH], np.nan).astype("f8")
            blk = np.where(np.abs(blk) > 1e19, np.nan, blk)
            q = blk[:, iy, ix]       # (chunk, ndam)
            mx = np.fmax(mx, np.nanmax(q, axis=0))
            sm += np.nansum(q, axis=0)
        amax[k] = mx
        amean[k] = sm / nt
        f.close()
        print(f"  {dd.split('/')[-1]}: max {np.nanmax(mx):,.0f} m3/s", flush=True)

    rows = []
    for i, d in enumerate(dams):
        peaks = amax[:, i][np.isfinite(amax[:, i])]
        loc, scale = gumbel_l_moments(peaks) if peaks.size >= 5 else (np.nan, np.nan)
        qT = q_return(loc, scale, a.return_period) if np.isfinite(loc) else np.nan
        qn = float(np.nanmean(amean[:, i]))
        qf = a.qf_factor * qT if np.isfinite(qT) else np.nan
        # Qf must exceed Qn or the release rule is degenerate
        if np.isfinite(qf) and qf < qn:
            qf = qn * 1.5
        fld = d["cap"] * a.fld_fraction
        con = d["cap"] - fld
        rows.append((d, qn, qf, qT, fld, con))

    ok = [r for r in rows if np.isfinite(r[2]) and r[0]["cap"] > 0]
    print(f"\nusable dams           : {len(ok)} / {nd}")

    # CaMa represents ONE dam per river cell: I1DAM(ISEQ) is a single flag and
    # DAMOUT's outflow loop runs over dams writing to DamSeq(IDAM), so two dams
    # sharing a cell means the later one silently wins and the earlier one's
    # storage vanishes. GRanD has cascades inside a single 0.25 deg cell (five
    # dams in one cell in Japan, four in Spain, four in Romania), so merge them
    # instead of losing them: capacities add, and Qn/Qf are already identical
    # because they come from that same cell's discharge. DamYear is taken from
    # the LARGEST member, i.e. the year most of the cell's storage appeared --
    # year-by-year commissioning is per dam, so a merged cell can only have one
    # date and the dominant reservoir is the defensible choice.
    bycell = {}
    for d, qn, qf, qT, fld, con in ok:
        k = (d["ix"], d["iy"])
        bycell.setdefault(k, []).append((d, qn, qf, qT, fld, con))
    merged = []
    n_merged = 0
    for k, grp in bycell.items():
        if len(grp) == 1:
            merged.append(grp[0]); continue
        n_merged += len(grp) - 1
        grp.sort(key=lambda g: -g[0]["cap"])          # largest first
        lead = grp[0]
        d = dict(lead[0])
        d["cap"] = sum(g[0]["cap"] for g in grp)
        d["name"] = f'{lead[0]["name"][:20]}+{len(grp)-1}'
        merged.append((d, lead[1], lead[2], lead[3],
                       sum(g[4] for g in grp), sum(g[5] for g in grp)))
    if n_merged:
        print(f"  merged {n_merged} dam(s) sharing a cell -> {len(merged)} cells "
              f"(capacity preserved, not shadowed)")
    ok = merged
    if not ok:
        sys.exit("ERROR: no dam produced a usable Qf. A Gumbel fit needs at least 5 "
                 "annual maxima -- check that --cmf-glob matched enough years "
                 f"(it matched {ny}).")
    q100 = np.array([r[3] for r in ok])
    print(f"  Q100  median {np.median(q100):,.1f}  max {np.nanmax(q100):,.0f} m3/s")
    print(f"  Qn    median {np.median([r[1] for r in ok]):,.1f} m3/s")

    if a.dry_run:
        print("\n--dry-run: not writing"); return

    with open(a.out, "w") as f:
        f.write(f"{len(ok)}\n")
        f.write("ID,DamName,DamLat,DamLon,upreal,DamIX,DamIY,"
                "FldVol_mcm,ConVol_mcm,TotVol_mcm,Qn,Qf,DamYear\n")
        for d, qn, qf, qT, fld, con in ok:
            f.write(f"{d['ID']},{d['name']},{d['lat']:.4f},{d['lon']:.4f},"
                    f"{d['area']:.2f},{d['ix']},{d['iy']},"
                    f"{fld:.3f},{con:.3f},{d['cap']:.3f},{qn:.4f},{qf:.4f},{d['year']}\n")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
