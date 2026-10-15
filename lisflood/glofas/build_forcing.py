#!/usr/bin/env python3
"""One year of LISFLOOD forcing: daily meteo -> LISVAP ET0/E0/ES0 -> linked under the GloFAS prefixes.

Driver for prepare_meteo.py + run_lisvap.py + link_forcing.sh, as in <exp>-glofas. Idempotent: a
year whose five links exist and are non-empty is skipped (--force rebuilds). Stops at the first
failing year rather than carrying on with a hole in the series.

Run it with the LISFLOOD Python -- LISVAP needs that environment:
    /usr/local/apps/lisflood/5.0.0/lisflood-env/bin/python glofas/build_forcing.py --years 1988 1988

Cost per global year, measured 2026-10-15 on one day and scaled: meteo ~2.5 h (25 s/day, peak RSS
1.2 GB), LISVAP ~6 h (58 s/day, peak RSS 5.0 GB), ~45 GB of meteo + ~25 GB of LISVAP output on
$SCRATCH. Years are INDEPENDENT here, so this step can run as a 37-way array; only LISFLOOD
itself is serial in time (the warm-start chain).
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import glofas  # noqa: E402

LINKS = ("tp", "ta", "e0", "eS0", "eT0")


def done(w: Path, y: int) -> bool:
    fs = [w / "forcing_lisflood" / f"glofas_{v}_{y}.nc" for v in LINKS]
    return all(f.exists() and f.stat().st_size > 0 for f in fs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs=2, required=True, metavar=("START", "END"))
    ap.add_argument("--days", type=int, default=None, help="first N days only (pilot runs)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    paths = glofas.load_paths(); w = glofas.work(paths); (w / "logs").mkdir(exist_ok=True)
    py = sys.executable
    for y in range(a.years[0], a.years[1] + 1):
        if done(w, y) and not a.force:
            print(f"{y}: skip (forcing linked)", flush=True); continue
        t0 = time.time()
        cmd = [py, str(HERE / "prepare_meteo.py"), "--years", str(y), str(y)]
        if a.days:
            cmd += ["--days", str(a.days)]
        if a.force:
            cmd += ["--force"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-800:], r.stderr[-1500:]); sys.exit(f"{y}: prepare_meteo FAILED")
        meteo = r.stdout.strip().splitlines()[-1]
        cmd = [py, str(HERE / "run_lisvap.py"), str(y)] + (["--days", str(a.days)] if a.days else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        log = w / "logs" / f"lisvap_{y}.log"
        log.write_text(r.stdout + r.stderr)
        if "exit code 0" not in r.stdout:
            print(log.read_text()[-2000:]); sys.exit(f"{y}: LISVAP FAILED (see {log})")
        et = [l for l in r.stdout.splitlines() if l.startswith(("et.nc", "FAO"))]
        subprocess.run([str(HERE / "link_forcing.sh"), str(w), str(y)], check=True)
        print(f"{y}: {time.time() - t0:5.0f}s | {meteo.split('|', 1)[1].strip() if '|' in meteo else meteo} | "
              + " | ".join(et), flush=True)
    missing = [y for y in range(a.years[0], a.years[1] + 1) if not done(w, y)]
    print("RESULT:", "PASS" if not missing else f"FAIL (missing {missing})")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
