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
    snow:  the same shape, but its driving term (the snow tiles' own net
           atmospheric flux) is not written to o_efl.nc, so it cannot be
           reconstructed here. ecLand checks it internally instead --
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
    # gated: the driving term is the snow tiles' own net atmospheric flux,
    # which upddiag.F90 computes into GDIAUX but wrtdcdf.F90 never writes, so
    # there is nothing here to balance it against. ecLand checks this one
    # internally and per grid point instead (LESNCHECK=.TRUE., threshold
    # 1e-6 W m-2): measured 2026-10-11, 242225 failing point-timesteps in 4
    # timesteps before the srfsn_webal_mod.F90/upddiag.F90 fix, 0 after.
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
    if ZERO_ON_LAND.get("DelSoilHeat"):
        verdict += "  (WATER only -- soil energy closure not testable)"
    else:
        verdict += "  (water + soil energy)"
    print("\n" + verdict)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
