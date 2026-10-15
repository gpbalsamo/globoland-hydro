#!/usr/bin/env python3
"""LISFLOOD settings for a GLOBAL run, from the GloFAS reanalysis's OWN operational settings.xml.

Source: <exp>-glofas/glofas/make_settings.py. Every option, parameter, routing, lake/reservoir and
water-use choice stays the operational GloFAS v5 configuration. What changes:

  PathOut, PathInit, PathMeteo, StepStart, StepEnd            -- this run, not the operational one
  repDischargeMaps = 1                                        -- as in the family: read any station later
  repTotalRunoffMaps, repSurfaceRunoffMaps = 1                -- THE POINT OF THIS REPOSITORY

PathRoot and MaskMap are NOT touched, unlike the regional repos: the operational values already
point at the global static maps (data/maps -> assets/5.0/staticMaps) and the global MaskMap
(template_Global_03min.nc, 6,221,926 land cells). A global run has no clip, so there is nothing
to override and no cut maps to point at.

ON THE RUNOFF OPTIONS, EXPLICITLY. The six <exp>-glofas repositories forbid changing operational
options "beyond paths/mask/dates/discharge maps" (their AGENTS.md), and this adds two more. That
is deliberate and is the reason this repository exists rather than being a seventh sibling: the
whole purpose is to retain LISFLOOD's runoff for comparison with ecLand and for aiLand training.
rep*Maps options are output-only and must not change the simulation -- which is a claim, so
--no-runoff-maps builds the same settings without them and tests/test_runoff_option_is_output_only
compares the resulting discharge. If discharge ever moves, the premise is wrong and the run is
not comparable with the operational configuration; that check is the gate, not a comment.

LISFLOOD's own reference settings define the three:
  repSurfaceRunoffMaps   surface runoff                 (ecLand Qs)
  repFastRunoffMaps      surface + upper zone
  repTotalRunoffMaps     surface + upper zone + lower   (ecLand -(Qs+Qsb))

Usage:
  python3 glofas/make_settings.py --tag pilot1d --start "02/01/1988 00:00" --end "02/01/1988 00:00"
  python3 glofas/make_settings.py --tag y1988 --year 1988
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import glofas  # noqa: E402

RUNOFF_OPTIONS = ("repTotalRunoffMaps", "repSurfaceRunoffMaps")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--year", type=int, default=None,
                    help="whole year: start 02/01/<y> 00:00, end 01/01/<y+1> 00:00 (overrides --start/--end)")
    ap.add_argument("--start", default="02/01/1988 00:00", help="first step (day 1 Jan is stamped 02/01 00:00)")
    ap.add_argument("--end", default="01/01/1989 00:00", help="last step (day 31 Dec is stamped 01/01 next)")
    ap.add_argument("--init", default=None,
                    help="state directory; default the operational 1987_1988 states valid 01/01/1988")
    ap.add_argument("--meteo", default=None, help="PathMeteo; default <work>/forcing_lisflood")
    ap.add_argument("--no-runoff-maps", action="store_true",
                    help="omit the runoff options (control for the output-only check)")
    a = ap.parse_args(argv)

    paths = glofas.load_paths(); w = glofas.work(paths)
    src = Path(paths["glofas_reanalysis"]) / "results" / "run" / "1988_1989" / "settings.xml"
    if not src.exists():
        sys.exit(f"operational settings not found: {src}")
    start, end = (a.start, a.end)
    if a.year:
        start, end = f"02/01/{a.year} 00:00", f"01/01/{a.year + 1} 00:00"
    run = w / "runs" / a.tag; out = run / "out"; out.mkdir(parents=True, exist_ok=True)
    init = a.init or str(Path(paths["glofas_reanalysis"]) / "results" / "run" / "1987_1988")

    t = src.read_text()
    tv = {"PathOut": out, "PathInit": init,
          "PathMeteo": a.meteo or (w / "forcing_lisflood"),
          "StepStart": start, "StepEnd": end}
    for k, v in tv.items():
        t, n = re.subn(r'(<textvar name="%s" value=")(?!\$\([A-Za-z]+\)")[^"]*(")' % k,
                       r"\g<1>%s\g<2>" % v, t)
        if n < 1:
            sys.exit(f"{k} not found in {src}")
        print(f"{k:10s} -> {v}  ({n} replaced)")

    opts = ["repDischargeMaps"] + ([] if a.no_runoff_maps else list(RUNOFF_OPTIONS))
    for opt in opts:
        t, n = re.subn(r'(<setoption choice=")0(" name="%s"/>)' % opt, r"\g<1>1\g<2>", t)
        if n != 1:
            sys.exit(f"{opt} not found exactly once in {src} (found {n})")
        print(f"{opt:22s} -> 1")
    if a.no_runoff_maps:
        print("runoff maps OMITTED (control run)")
    (run / "settings.xml").write_text(t)
    print("wrote", run / "settings.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
