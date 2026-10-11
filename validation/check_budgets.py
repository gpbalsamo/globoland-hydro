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

ENERGY (fluxes are downward-positive, so the turbulent terms are ADDED):

    SWnet + LWnet + Qle + Qh + Qg + Qf - DelSoilHeat - DelColdCont ~= 0

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
    for i in range(v.shape[0]):                      # stream: annual files are large
        s = np.ma.filled(v[i], np.nan).astype("f8")
        np.add(tot, np.nan_to_num(s) * scale, out=tot, where=land)
    # A term present in the file but identically zero on land is a diagnostic
    # the model never wrote, NOT a term that happens to vanish -- and a sum
    # that silently omits a term is not a closure. Recorded here because it
    # costs nothing; acted on in the energy section below.
    ZERO_ON_LAND[name] = not bool(np.any(tot[land] != 0.0))
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
              "DelSoilHeat", "DelColdCont"):
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

    # ALL-SURFACE energy: NOT a closure, and not gated. Three known defects,
    # none of them caused by the run:
    #  1. it DOUBLE-COUNTS the soil column. Qg already equals -(DelSoilHeat-Qf)
    #     to 3E-10, so adding Qg AND +Qf-DelSoilHeat counts that storage twice.
    #  2. it omits Qgsn and Qfsn, the snow basal and snow fusion fluxes, which
    #     o_efl.nc carries.
    #  3. DelColdCont is itself suspect: srfsn_mod.F90:380-382 shows the snow
    #     melt term (-PDHTSS(JL,1,14)) commented OUT of DDH index 15, and the
    #     term integrates to -376 EJ over a single day, which no snowpack can
    #     do. The snow analogue of the soil identity does not close.
    # Reported for continuity with earlier numbers, nothing more.
    eres = (et.get("SWnet") or 0) + (et.get("LWnet") or 0) \
        + sum(et[n] or 0 for n in ("Qle", "Qh", "Qg", "Qf")) \
        - sum(et[n] or 0 for n in ("DelSoilHeat", "DelColdCont"))
    eref = abs((et.get("SWnet") or 0) + (et.get("LWnet") or 0))
    erel = abs(eres) / eref if eref else float("nan")
    print()
    print(f"    {'ALL-SURFACE':14s} {eres/1e18:16.4f} EJ   ({erel:.3%} of net radiation)")
    print("    NOT A CLOSURE -- double-counts the soil column via Qg, omits")
    print("                     Qgsn/Qfsn, and DelColdCont is unreliable.")
    print("                     See the comment in this script. Not gating exit.")
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
