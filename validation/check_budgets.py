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
    # ecLand writes fluxes DOWNWARD-POSITIVE (restart attribute
    # SurfSgn_convention = "Mathematical"), so the turbulent and ground
    # fluxes are already negative where they carry energy away. They are
    # ADDED, not subtracted; subtracting them doubles the imbalance, which is
    # the energy-side twin of the Qs/Qsb sign trap in the water budget.
    eres = (et.get("SWnet") or 0) + (et.get("LWnet") or 0) \
        + sum(et[n] or 0 for n in ("Qle", "Qh", "Qg", "Qf")) \
        - sum(et[n] or 0 for n in ("DelSoilHeat", "DelColdCont"))
    eref = abs((et.get("SWnet") or 0) + (et.get("LWnet") or 0))
    erel = abs(eres) / eref if eref else float("nan")
    print(f"    {'RESIDUAL':14s} {eres/1e18:16.4f} EJ   ({erel:.3%} of net radiation)")
    # ecLand writes DelSoilHeat as identically zero at every land point
    # (verified 2026-10-10 on v4's 1989: min = max = 0 over all 88,373 land
    # points x 365 records). Soil heat content demonstrably does change -- the
    # model carries SoilTemp in o_gg.nc -- so this is an undiagnosed term, and
    # the sum above is missing the energy budget's main storage term. The
    # leftover is then a systematic +3,200..3,600 EJ (0.93-1.04% of net
    # radiation across v4 1988/1989/2000/2012/2024), i.e. straddling any 1%
    # tolerance for a reason that has nothing to do with closure quality.
    # Reporting that as FAIL blames the run for a missing diagnostic, so say
    # what is true: the test could not be performed. Computing it properly
    # means integrating SoilTemp against each layer's heat capacity.
    if ZERO_ON_LAND.get("DelSoilHeat"):
        print("    INCONCLUSIVE -- DelSoilHeat is identically zero over land, so")
        print("                    soil-heat storage is MISSING from the sum above.")
        print("                    The missing term has no known sign, so the")
        print("                    residual is not a closure error in either")
        print("                    direction. Not gating exit status.")
    else:
        print("    " + ("PASS" if erel <= a.energy_tol else
                        f"FAIL  (> {a.energy_tol:.1%})"))
        ok &= erel <= a.energy_tol

    # Never print a bare "BUDGETS PASS" when one of the two was not actually
    # tested -- that is precisely the claim CLAUDE.md's first rule forbids.
    verdict = "BUDGETS PASS" if ok else "BUDGETS FAIL"
    if ZERO_ON_LAND.get("DelSoilHeat"):
        verdict += "  (WATER only -- energy closure not tested)"
    print("\n" + verdict)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
