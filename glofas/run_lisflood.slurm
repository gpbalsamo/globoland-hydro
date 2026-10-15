#!/usr/bin/env bash
#SBATCH --job-name=wglofas_run
#SBATCH --qos=nf
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --time=24:00:00
# One continuous GLOBAL LISFLOOD 5.0.0 run (settings from glofas/make_settings.py --tag <tag>).
# Submit from the repository root; approval required (AGENTS.md):
#     sbatch glofas/run_lisflood.slurm <tag>
#
# Slurm runs a spool COPY of this script, so the repo comes from SLURM_SUBMIT_DIR and never from
# dirname $0 (the liaise-glofas spool-path bug). The tag is a positional argument, not an exported
# variable, because the site sbatch wrapper drops exported env vars.
#
# --mem=120G is the nf QoS ceiling (128G); it is a measurement, not a guess, once the one-day pilot has reported MaxRSS: a global
# window is 21.6e6 cells against amazex's 417,600, so memory -- not wall time -- was the open
# feasibility question. /usr/bin/time -v below records it on every run so the figure stays honest.
#
# Wall time: amazex (305,343 land cells) took 106,894 s for 1988-2024 on 8 cores and the cost is
# linear in land cells (calife, 24,926 cells: 9,021 s -> 12.25x cells, 11.85x time). Global is
# 6,221,926 cells = 20.4x amazex, so ~16 h per year. ONE YEAR PER JOB, chained through PathInit.
set -euo pipefail
REPO=${SLURM_SUBMIT_DIR:?submit with sbatch from the repository root}
TAG=${1:?usage: sbatch glofas/run_lisflood.slurm <tag>}
module load lisflood/5.0.0
# The operational settings ask for numCPUs_parallelNumba=32, capped at NUMBA_NUM_THREADS.
export NUMBA_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1} OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-1}
W=$(cd "$REPO" && python3 -c "import sys; sys.path.insert(0,'common'); import glofas; print(glofas.work(glofas.load_paths()))")
cd "$W/runs/$TAG"
echo "== LISFLOOD $TAG in $PWD, start $(date -u +%FT%TZ), ${SLURM_CPUS_PER_TASK:-1} threads"
t0=$SECONDS
/usr/bin/time -v lisflood settings.xml > lisflood.log 2> lisflood.time && rc=0 || rc=$?
echo "== exit $rc after $((SECONDS - t0)) s ($(date -u +%FT%TZ))"
grep -E "Maximum resident set size|Elapsed \(wall" lisflood.time || true
tail -5 lisflood.log
exit $rc
