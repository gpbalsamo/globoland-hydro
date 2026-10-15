#!/usr/bin/env python3
"""Global water- and energy-balance closure for an ecLand run.

Area-weighted, not a plain grid-cell mean: cell area varies with cos(lat), so
an unweighted average silently over-weights the poles. This is a hard
requirement in CLAUDE.md, not a refinement.

WATER (per this project's verified convention -- see docs/forcing_variables.md
and the runoff-sign finding carried from liaise-ecland):

    Rainf + Snowf + Evap + Qs + Qsb
        - DelSoilMoist - DelSWE - DelIntercept - DelAquifer  ~= 0

Qs and Qsb are ADDED, not subtracted. Subtracting them manufactures a
spurious 2x residual -- that error is exactly what the runoff sign convention
(total_runoff = -(Qs+Qsb)) exists to prevent.

ENERGY (fluxes are downward-positive, so the turbulent terms are ADDED).
Two per-reservoir identities, each a real closure the model satisfies:

    soil:  Qg   + (DelSoilHeat - Qf)    ~= 0      gated, closes to 3e-10
    snow:  Qgsn + (DelColdCont - Qfsn) = the snow tiles' net atmospheric
           flux -- which o_efl.nc does not carry, so it is not checked here.
           It CAN be reconstructed from o_til.nc (LWRTIL=.TRUE.): per-tile
           SWnet+LWnet+Qh+Qle on tiles 5 and 7, already fraction-weighted.
           That agrees to mean 1.5 W m-2, slope 0.979, corr 0.998 -- good
           enough to catch a broken term, not a closure, because ecLand's
           per-tile RADIATION diagnostics are approximations: summed over all
           ten tiles they miss the grid-box SWnet by 1.29 and LWnet by 2.44
           W m-2 on average, while per-tile Qh and Qle sum exactly (1e-7).
           For an exact test use ecLand's own per-grid-point check instead:
           LESNCHECK=.TRUE. in NAMPHYOFF, srfsn_driver_mod.F90.

The whole-surface sum is reported but NOT gated, because land heat storage
outside the soil and snow columns -- FLake, sea ice, interception, the skin
layer -- has no output diagnostic to put on the right-hand side:

    SWnet + LWnet + Qle + Qh - (DelSoilHeat - Qf) - (DelColdCont - Qfsn)

Fluxes in o_wat are RATES (kg m-2 s-1) and in o_efl (W m-2), despite
LACCUMW/LRESET suggesting accumulation -- they are multiplied by the output
interval here to give depths (kg m-2) and energies (J m-2). Getting this
wrong makes annual totals come out near zero.
"""
import argparse, sys
import numpy as np
from netCDF4 import Dataset

R_EARTH = 6371000.0

def cell_area(lat, lon):
    dlat = abs(float(lat[1] - lat[0])); dlon = abs(float(lon[1] - lon[0]))
    a = (np.deg2rad(dlat) * np.deg2rad(dlon) * R_EARTH**2
         * np.cos(np.deg2rad(lat))[:, None])
    return np.broadcast_to(a, (lat.size, lon.size))

def interval_seconds(ds):
    t = ds["time"]
    if len(t) < 2:
        return None
    dt = float(t[1] - t[0])
    u = getattr(t, "units", "").lower()
    return dt * (3600.0 if u.startswith("hour") else 86400.0 if u.startswith("day") else 1.0)

# name -> True when the term was present but summed to exactly zero over land
ZERO_ON_LAND = {}
# terms whose declared units predate the ecland label fix
STALE_UNITS = set()
# name -> max |value| seen, for the physical-bound test on the storage terms
MAXABS = {}
# a surface energy flux this large is not a flux. Used only to recognise output
# written before the ecland snow fix, where DelColdCont was C*dT in J m-2 read
# as W m-2 and reached 2.2e5; the largest honest term in o_efl.nc is SWdown at
# ~1.2e3. Nothing in between is plausible, so the bound needs no tuning.
FLUX_BOUND = 1.0e4

def acc(ds, name, area, dt, land):
    """Area-weighted global total, summed over time.

    Whether a term is a RATE or an already-integrated DIFFERENCE is decided
    from its units, not its name: o_wat carries fluxes as kg m-2 s-1 but the
    storage changes (DelSoilMoist, DelSWE, DelIntercept) as kg m-2, and o_efl
    carries W m-2 alongside J m-2. Multiplying a difference by the output
    interval inflates it by dt -- 86400x for daily output, which is exactly
    the error that made the first version of this script report a residual
    450000x the precipitation.
    """
    if name not in ds.variables:
        return None
    v = ds[name]
    u = getattr(v, "units", "").replace(" ", "").lower()
    is_rate = u.endswith("s-1") or u in ("wm-2",)
    # DelSoilHeat/DelColdCont were declared 'J m-2' but are written through the
    # SAME path as Qf/Qg -- accumulator bucket IA times ZWA, which under
    # LACCUMW is 1/(NFRPOS*TSTEP) -- so they are MEAN RATES in W m-2. Measured
    # 2026-10-11: regressing DelSoilHeat on the o_gg.nc soil temperature change
    # gives slope*3600 = 2.1935E6 = RRCSOIL exactly, corr 1.000000, and the
    # soil budget then closes to 3E-10. The label is fixed in ecland
    # (netcdf_utils.F90), but every file written before that carries the old
    # one, so treat these two as rates whatever they claim.
    if name in ("DelSoilHeat", "DelColdCont") and not is_rate:
        is_rate = True
        STALE_UNITS.add(name)
    scale = dt if is_rate else 1.0
    tot = np.zeros(area.shape)
    mx = 0.0
    for i in range(v.shape[0]):                      # stream: annual files are large
        s = np.ma.filled(v[i], np.nan).astype("f8")
        mx = max(mx, float(np.abs(np.nan_to_num(s)[land]).max()))
        np.add(tot, np.nan_to_num(s) * scale, out=tot, where=land)
    # A term present in the file but identically zero on land is a diagnostic
    # the model never wrote, NOT a term that happens to vanish -- and a sum
    # that silently omits a term is not a closure. Recorded here because it
    # costs nothing; acted on in the energy section below.
    ZERO_ON_LAND[name] = not bool(np.any(tot[land] != 0.0))
    MAXABS[name] = mx                                # per-record, before scaling
    return float((tot * area)[land].sum())

# The two snow tiles. 5 and 7 in ecLand's 1-based tile numbering, so 4 and 6
# here. netcdf_utils.F90:105 and srfsn_driver_mod.F90:298 disagree about which
# of the two is the exposed one and which is under forest; this check sums both
# and so does not depend on that.
SNOW_TILES = (4, 6)

def snow_tile_closure(d, efl, land, frsn_min=1e-3):
    """Snow-column energy closure, reconstructed from o_til.nc. None if absent.

    The snow column's driving term is ZHFLUX (srfsn_driver_mod.F90:298), the
    snow tiles' net atmospheric flux, and o_efl.nc does not carry it: of DDH
    slots 7-12 upddiag.F90 reads only 7-10 and wrtdcdf.F90 writes none of them.
    With LWRTIL=.TRUE. (template namelist_ecland_50R1_ctl_sntile) o_til.nc
    carries per-tile SWnet, LWnet, Qh and Qle, ALREADY fraction-weighted
    (surfexcdriver_ctl_mod.F90:1166, surfpp_ctl_mod.F90:462), so summing tiles
    5 and 7 rebuilds it and the identity to test is

        SWnet+LWnet+Qh+Qle over tiles 5,7  ==  Qgsn + (DelColdCont - Qfsn)

    Judged by regression, NOT by the integral: the two sides are a few EJ each
    with heavy cancellation, so a relative error on the global integral is
    ~37% even when the fields agree pointwise at corr 0.998. Slope and
    correlation are what carry the information here.

    It cannot be exact, and the floor is not the model's fault: ecLand's
    per-tile RADIATION diagnostics are approximations, while its per-tile
    turbulent fluxes are exact. Summed over all ten tiles, o_til.nc's Qh and
    Qle reproduce o_efl.nc's grid-box values to 1e-7 W m-2, but SWnet is out by
    1.29 and LWnet by 2.44 W m-2 on average (max 40 and 31), because
    PDHTLS(:,JTILE,6) is PFRTI*PSLRFL/PEMIS -- the grid-box net LW
    redistributed by tile fraction, not the per-tile PSLRFLTI the solver uses
    (surfexcdriver_ctl_mod.F90:1171). So the residual floor is ~1.5 W m-2 per
    sample, bigger by day than at night. Do not tighten the tolerances below
    that expecting it to mean anything.

    The default tolerances are calibrated, not guessed. Measured 2026-10-11 on
    a 3 h global run, 171585 snow samples, perturbing one term at a time:

        perturbation                slope      corr   mean|res|   verdict
        none (correct run)        0.97898   0.99841      1.4913   PASS
        DelColdCont x 1.05        0.94996   0.99829      1.6172   PASS
        DelColdCont x 1.10        0.92188   0.99779      1.8695   PASS
        DelColdCont x 1.20        0.86871   0.99587      2.6036   FAIL
        DelColdCont x 1.50        0.73275   0.98600      5.2904   FAIL
        DelColdCont x 0.50        1.28093   0.95345      4.8837   FAIL
        Qfsn sign flipped         0.68038   0.67774      4.1359   FAIL
        Qgsn sign flipped         0.68112   0.61709     12.6122   FAIL
        DelColdCont sign flipped -0.26891  -0.24098     19.2085   FAIL
        DelColdCont dropped       1.13792   0.67562      9.6004   FAIL
        Qfsn dropped              0.99092   0.91596      2.7710   FAIL

    So it catches every sign error, any term silently dropped, and a scale
    error from about 15% up. A scale error SMALLER than that passes -- which is
    the honest limit of a check whose floor is 1.5 W m-2, and is why the
    FLUX_BOUND magnitude test above exists as the coarse first line of defence.
    Verified end to end both ways: PASS on the real run, FAIL on a copy of it
    with DelColdCont multiplied by 1.5.
    """
    try:
        til = Dataset(f"{d}/o_til.nc")
    except OSError:
        return None
    need = ("tifr", "SWnet", "LWnet", "Qh", "Qle")
    if any(n not in til.variables for n in need) or "Qgsn" not in efl.variables:
        return None
    nt = min(len(til["time"]), len(efl["time"]))
    n = sx = sy = sxx = syy = sxy = sad = say = 0.0
    g = lambda ds, v, i: np.nan_to_num(
        np.ma.filled(ds[v][i], np.nan).astype("f8"))
    for i in range(nt):                              # stream, as acc() does
        fr = g(til, "tifr", i)
        frsn = fr[SNOW_TILES[0]] + fr[SNOW_TILES[1]]
        hf = np.zeros(frsn.shape)
        for v in ("SWnet", "LWnet", "Qh", "Qle"):
            a = g(til, v, i)
            hf += a[SNOW_TILES[0]] + a[SNOW_TILES[1]]
        rhs = g(efl, "Qgsn", i) + (g(efl, "DelColdCont", i)
                                   - g(efl, "Qfsn", i))
        m = land & (frsn > frsn_min)
        x = rhs[m]; y = hf[m]
        n += x.size
        sx += x.sum(); sy += y.sum()
        sxx += (x * x).sum(); syy += (y * y).sum(); sxy += (x * y).sum()
        sad += np.abs(y - x).sum(); say += np.abs(y).sum()
    if n < 100:
        return None
    den = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / den if den else float("nan")
    cden = np.sqrt(max(den, 0.0) * max(n * syy - sy * sy, 0.0))
    corr = (n * sxy - sx * sy) / cden if cden else float("nan")
    return dict(n=int(n), slope=slope, corr=corr,
                mad=sad / n, scale=say / n)

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--water-tol", type=float, default=0.01,
                   help="max |residual| / |precip input| (default 1%%)")
    p.add_argument("--soil-tol", type=float, default=1e-6,
                   help="relative tolerance on the soil-column energy closure "
                        "Qg + (DelSoilHeat - Qf); it closes to ~3e-10 when the "
                        "ecland DDH index-15 fix is present")
    p.add_argument("--energy-tol", type=float, default=0.01,
                   help="max |residual| / |SWnet+LWnet| (default 1%%)")
    p.add_argument("--snow-corr", type=float, default=0.95,
                   help="minimum correlation for the o_til.nc snow-column "
                        "check, when o_til.nc is present (default 0.95; "
                        "measured 0.998 on a correct run)")
    p.add_argument("--snow-slope-tol", type=float, default=0.10,
                   help="max |slope-1| for the same check (default 0.10; "
                        "measured 0.979, and the floor is ~0.02 because "
                        "ecLand's per-tile radiation is approximate)")
    p.add_argument("--no-snow-check", action="store_true",
                   help="report the o_til.nc snow-column check but do not let "
                        "it gate the exit status")
    a = p.parse_args()
    d = a.output_dir.rstrip("/")

    wat = Dataset(f"{d}/o_wat.nc")
    lat = np.ma.filled(wat["lat"][:], np.nan).astype("f8")
    lon = np.ma.filled(wat["lon"][:], np.nan).astype("f8")
    area = cell_area(lat, lon)
    dt = interval_seconds(wat)
    if dt is None:
        sys.exit("ERROR: need >=2 time records to infer the output interval")
    land = np.isfinite(np.ma.filled(wat["Rainf"][0], np.nan))
    print(f"grid {lat.size}x{lon.size}, {land.sum()} land points, "
          f"{len(wat['time'])} records, interval {dt/3600:.0f} h")
    print(f"land area {(area[land].sum())/1e12:.3f} x 10^12 m^2\n")

    ok = True

    # ---- water -----------------------------------------------------------
    print("WATER BALANCE (kg = 10^-12 Gt, global land totals)")
    terms = {}
    for n in ("Rainf", "Snowf", "Evap", "Qs", "Qsb",
              "DelSoilMoist", "DelSWE", "DelIntercept", "DelAquifer"):
        terms[n] = acc(wat, n, area, dt, land)
        if terms[n] is not None:
            print(f"    {n:14s} {terms[n]/1e12:16.4f} Gt")
    res = sum(terms[n] for n in ("Rainf", "Snowf", "Evap", "Qs", "Qsb")
              if terms[n] is not None) \
        - sum(terms[n] for n in ("DelSoilMoist", "DelSWE", "DelIntercept", "DelAquifer")
              if terms[n] is not None)
    ref = abs((terms.get("Rainf") or 0) + (terms.get("Snowf") or 0))
    rel = abs(res) / ref if ref else float("nan")
    print(f"    {'RESIDUAL':14s} {res/1e12:16.4f} Gt   ({rel:.3%} of precipitation)")
    print("    " + ("PASS" if rel <= a.water_tol else
                    f"FAIL  (> {a.water_tol:.1%})"))
    ok &= rel <= a.water_tol

    # ---- energy ----------------------------------------------------------
    try:
        efl = Dataset(f"{d}/o_efl.nc")
    except OSError:
        print("\nENERGY BALANCE: o_efl.nc absent -- SKIPPED (run with WRITE_EFL=true)")
        sys.exit(0 if ok else 1)
    print("\nENERGY BALANCE (J, global land totals)")
    dte = interval_seconds(efl) or dt
    et = {}
    for n in ("SWnet", "LWnet", "Qle", "Qh", "Qg", "Qf",
              "DelSoilHeat", "DelColdCont", "Qgsn", "Qfsn"):
        et[n] = acc(efl, n, area, dte, land)
        if et[n] is not None:
            print(f"    {n:14s} {et[n]/1e18:16.4f} EJ")
    # SOIL COLUMN CLOSURE -- the one energy identity that actually closes.
    # From the model's own definitions (srft_mod.F90:409,411):
    #     DelSoilHeat =  RRCSOIL*RDAT*dT/dt                 (DDH index 15)
    #     Qf          = -(PCTSA-RRCSOIL)*RDAT*dT/dt         (DDH index 12)
    # so DelSoilHeat - Qf = PCTSA*RDAT*dT/dt, the FULL soil heat content
    # change, and it must balance the ground heat flux Qg. Measured on a
    # 1994-01-01 day: Qg = 35.428263 EJ, DelSoilHeat - Qf = -35.428263 EJ,
    # sum 2.9E-10 relative. With DelSoilHeat left at zero the same identity is
    # out by 37.9%, which is how the missing term was found.
    soil_stor = (et.get("DelSoilHeat") or 0) - (et.get("Qf") or 0)
    sres = (et.get("Qg") or 0) + soil_stor
    sref = max(abs(et.get("Qg") or 0), abs(soil_stor))
    srel = abs(sres) / sref if sref else float("nan")
    print()
    print(f"    {'Qg':14s} {(et.get('Qg') or 0)/1e18:16.4f} EJ")
    print(f"    {'DelSoilHeat-Qf':14s} {soil_stor/1e18:16.4f} EJ   (full soil storage change)")
    print(f"    {'SOIL RESIDUAL':14s} {sres/1e18:16.4f} EJ   ({srel:.3e} relative)")
    if ZERO_ON_LAND.get("DelSoilHeat"):
        print("    INCONCLUSIVE -- DelSoilHeat is identically zero over land, so")
        print("                    this run predates the ecland fix that wires up")
        print("                    DDH index 15 (upddiag.F90). Not gating exit.")
    else:
        print("    " + ("PASS" if srel <= a.soil_tol else
                        f"FAIL  (> {a.soil_tol:.1e})"))
        ok &= srel <= a.soil_tol

    # SNOW COLUMN. The same two-part storage as the soil -- DelColdCont is the
    # sensible part (DDH index 15) and Qfsn the phase-change part (index 14),
    # so DelColdCont - Qfsn is the whole pack's storage change. Reported, not
    # gated: the driving term is the snow tiles' own net atmospheric flux, and
    # o_efl.nc does not carry it -- of DDH slots 7-12 (snow SW/LW down and up,
    # sensible, latent) upddiag.F90 reads only 7-10, into D1STNSRD/SRU/TRD/TRU,
    # and wrtdcdf.F90 writes none of them; slots 11 and 12 are never even read.
    # Per-tile output (LWRTIL=.TRUE. -> o_til.nc) is the way round it, to
    # ~1.5 W m-2 -- see the module docstring. The exact test is ecLand's own
    # per-grid-point check (LESNCHECK=.TRUE., threshold 1e-6 W m-2): measured
    # 2026-10-11, 242225 failing point-timesteps in 4 timesteps before the
    # srfsn_webal_mod.F90/upddiag.F90 fix, 0 after.
    snow_stor = (et.get("DelColdCont") or 0) - (et.get("Qfsn") or 0)
    stale_snow = MAXABS.get("DelColdCont", 0.0) > FLUX_BOUND
    print()
    print(f"    {'Qgsn':14s} {(et.get('Qgsn') or 0)/1e18:16.4f} EJ")
    print(f"    {'DelColdCont-Qfsn':14s} {snow_stor/1e18:14.4f} EJ   (full snow storage change)")
    if stale_snow:
        print(f"    PRE-FIX OUTPUT -- DelColdCont peaks at {MAXABS['DelColdCont']:.3g} W m-2, which is not")
        print("                      a flux. This run predates the ecland snow fix, where")
        print("                      DDH index 15 was C*dT in J m-2 and only snow layer 1")
        print("                      was read. Both snow terms below are meaningless.")

    # Optional: with o_til.nc present, the snow column becomes a real check.
    sn = snow_tile_closure(d, efl, land)
    if sn is None:
        print("    SNOW CLOSURE not tested -- needs o_til.nc, i.e. LWRTIL=.TRUE.")
        print("                     (namelist/templates/namelist_ecland_50R1_ctl_sntile)")
    else:
        print()
        print(f"    SNOW CLOSURE from o_til.nc, tiles 5+7, {sn['n']} snow samples")
        print(f"      SWnet+LWnet+Qh+Qle  vs  Qgsn + (DelColdCont - Qfsn)")
        print(f"      slope {sn['slope']:.6f}   corr {sn['corr']:.6f}   "
              f"mean |residual| {sn['mad']:.4f} W m-2 of {sn['scale']:.4f}")
        good = (sn["corr"] >= a.snow_corr
                and abs(sn["slope"] - 1.0) <= a.snow_slope_tol)
        if stale_snow:
            print("      INCONCLUSIVE -- pre-fix output, see above. Not gating exit.")
        elif a.no_snow_check:
            print("      " + ("PASS" if good else "FAIL")
                  + "  (--no-snow-check: not gating exit)")
        else:
            print("      " + ("PASS" if good else
                              f"FAIL  (need corr >= {a.snow_corr}, "
                              f"|slope-1| <= {a.snow_slope_tol})"))
            ok &= good

    # WHOLE SURFACE: reported, never gated, and this is not a defect in the
    # run. The left-hand side is the net flux into the land surface and the
    # right-hand side is the storage of the only two reservoirs with storage
    # diagnostics; FLake, sea ice, interception and the skin layer have none,
    # so a residual is expected and its size is the size of those reservoirs'
    # storage change, not an error.
    # Earlier versions of this script wrote the equation as
    #   SWnet+LWnet+Qle+Qh+Qg+Qf-DelSoilHeat-DelColdCont
    # which double-counted the soil column (Qg = -(DelSoilHeat-Qf) to 3e-10)
    # and omitted Qfsn. On a 1994-01-01 day that form gives 3.556% of net
    # radiation and the form below gives 1.262%, so the old "0.5-0.96% band"
    # was defects partly cancelling, not a closure.
    atm = sum(et[n] or 0 for n in ("SWnet", "LWnet", "Qle", "Qh"))
    eres = atm - soil_stor - snow_stor
    eref = abs((et.get("SWnet") or 0) + (et.get("LWnet") or 0))
    erel = abs(eres) / eref if eref else float("nan")
    print()
    print(f"    {'SWnet+LWnet+Qle+Qh':18s} {atm/1e18:12.4f} EJ   (net flux into the surface)")
    print(f"    {'soil+snow storage':18s} {(soil_stor+snow_stor)/1e18:12.4f} EJ")
    print(f"    {'UNACCOUNTED':18s} {eres/1e18:12.4f} EJ   ({erel:.3%} of net radiation)")
    print("    NOT A CLOSURE -- FLake, sea ice, interception and the skin layer")
    print("                     have no storage diagnostic in o_efl.nc. Not gating.")
    if STALE_UNITS:
        print()
        print("    NOTE: " + "/".join(sorted(STALE_UNITS)) + " declared 'J m-2' in this file but")
        print("          treated as W m-2 -- see the comment in acc(). Rerun with an")
        print("          ecland built after the netcdf_utils.F90 label fix to remove this.")

    # Never print a bare "BUDGETS PASS" when one of the two was not actually
    # tested -- that is precisely the claim CLAUDE.md's first rule forbids.
    verdict = "BUDGETS PASS" if ok else "BUDGETS FAIL"
    tested = ["water"]
    if not ZERO_ON_LAND.get("DelSoilHeat"):
        tested.append("soil energy")
    if sn is not None and not stale_snow and not a.no_snow_check:
        tested.append("snow energy")
    verdict += "  (" + " + ".join(tested) + ")"
    if "soil energy" not in tested:
        verdict += "  -- soil energy closure not testable"
    if "snow energy" not in tested:
        verdict += "  -- snow energy closure not tested"
    print("\n" + verdict)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
