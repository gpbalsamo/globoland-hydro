#!/usr/bin/env bash
# Keep a working copy of this repository on $SCRATCH (Lustre) and bring the
# keepers back. Ported from ifs-landbench/scripts/scratch_mirror.sh.
#
# WHY, AND HOW MUCH IT ACTUALLY BUYS -- measured here, not inherited:
#
#   single-stream write, 2 GB     NFS ($PERM)  460 MB/s
#                                 Lustre ($SCRATCH)  840 MB/s   -> 1.8x
#
# ifs-landbench measured 530 vs 4863 MB/s, a factor 9.2, but that is NFS
# COLLAPSING under 30 concurrent writers. This repo's campaign is sequential --
# one annual segment, 16 ranks, one node -- so the honest expectation for the
# campaign itself is ~2%: ~50 GB of I/O per segment, 109 s on NFS against 60 s
# on Lustre, inside a ~2880 s segment. Do NOT expect a speed-up by moving a
# sequential chain here.
#
# WHERE IT DOES PAY:
#   - concurrent experiments (dams run alongside the control, ensembles). That
#     is the regime landbench measured, where NFS degrades ~9x. Their job
#     36354918 lost 480 CPU-hours with output on Lustre but inputs and the
#     EXECUTABLE still on NFS -- which is why this script pushes the build too.
#   - bulk re-reads of the archive (validation sweep, Q100 extraction). Expect
#     modest gains: the sweep reads ~1.3 TB at ~34 MB/s effective, so it is
#     dominated by per-timestep Python and NFS latency rather than bandwidth.
#     Output is UNCOMPRESSED here (complevel 0), so this is not decompression.
#
# $SCRATCH IS PRUNED AUTOMATICALLY. The two trees are duals: bulk work there,
# anything you want to keep lives here. Raw ecLand/CaMa output is deliberately
# NOT pulled back -- it is ~30 GB per simulated year and is already archived to
# ECFS by run_ecland.sh.
#
#   push  : $PERM -> $SCRATCH   code, namelists, forcing, clim, CaMa weights,
#                               dam data, and the ecLand build (bin + lib)
#   pull  : $SCRATCH -> $PERM   analysis products only -- never raw output/
#   status: what exists on each side
#
# The mirror keeps this repository's layout, so scripts work there unchanged:
# run_ecland.sh derives paths from $SLURM_SUBMIT_DIR / its own location.
set -euo pipefail

PERM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MIRROR="${SCRATCH:?SCRATCH is not set}/wfde5-ecland"
ECLAND_BUILD="${ECLAND_ROOT:-/perm/${USER}/ecland}/build"
BUILD_SUBDIRS=(bin lib lib64)
MIRROR_BUILD_REL="ecland-build"
DRY_RUN=false
NO_FORCING=false

# Everything a run needs, nothing it produces. NOTE these are deliberately
# PRECISE: pushing bare "run" drags in run/work/data/forcing (3.6 TB of
# met_2DHT slices) and run/output (832 GB), and rsync --exclude patterns are
# matched relative to the TRANSFER ROOT, so "--exclude run/output" does not fire
# when the source is run/ itself. Name what goes, rather than excluding what
# must not.
PUSH_PATHS=(run/configs validation namelist cama_flood/dams init_clim config docs tests)
PUSH_GLOBS=(run/*.sh run/*.py run/*.slurm run/README*)
# Big inputs, skippable with -f when only the code changed. The met_2DHT slices
# under run/work/data/forcing are NOT pushed: they are regenerable from the
# annual WFDE5 files below, and run_ecland.sh's validated forcing cache will
# rebuild them on the mirror at ~10 min/year rather than copying 3.6 TB.
FORCING_PATHS=(forcing/WFDE5_CRU_GPCC run/work/data/clim cama_flood/work_global_weights)
# Results worth keeping. Anything not listed is lost at the next prune -- intended.
PULL_PATHS=(cama_flood/dams experiments validation/results)

usage() {
  cat <<USAGE
Usage: $(basename "$0") {push|pull|status} [-f] [-n] [-M MIRROR]

  push        Copy code and inputs to the mirror
  pull        Copy analysis products back (${PULL_PATHS[*]}) -- never raw output
  status      Show both sides without copying

  -f          Skip the bulk inputs (${FORCING_PATHS[*]}); code only
  -n          Dry run: print what rsync would transfer
  -M MIRROR   Mirror location (default: ${MIRROR})
  -h          Show this help

Deletions are never propagated: rsync runs without --delete in both directions,
so a stale file in the mirror is possible but losing a result is not.
Raw output/ is deliberately never pulled -- it is on ECFS.
USAGE
}

ACTION="${1:-}"
[[ -n "${ACTION}" ]] && shift || true
case "${ACTION}" in
  push|pull|status) ;;
  -h|--help|help) usage; exit 0 ;;
  *) echo "ERROR: expected push, pull or status" >&2; usage >&2; exit 2 ;;
esac

while getopts ":hnfM:" opt; do
  case "${opt}" in
    n) DRY_RUN=true ;;
    f) NO_FORCING=true ;;
    M) MIRROR="${OPTARG}" ;;
    h) usage; exit 0 ;;
    \?) echo "ERROR: invalid option -${OPTARG}" >&2; usage >&2; exit 2 ;;
    :) echo "ERROR: option -${OPTARG} requires an argument" >&2; usage >&2; exit 2 ;;
  esac
done

"${NO_FORCING}" || PUSH_PATHS+=("${FORCING_PATHS[@]}")

RSYNC=(rsync -a --human-readable --info=stats1
       --exclude '.git' --exclude '__pycache__' --exclude '*.pyc'
       --exclude 'run/output' --exclude 'run/work/run' --exclude 'slurm-*.out'
       --exclude 'ecsbatch.log.*')
"${DRY_RUN}" && RSYNC+=(--dry-run --itemize-changes)

show_side() {
  local label=$1 root=$2 p
  echo "${label}: ${root}"
  [[ -d "${root}" ]] || { echo "  (does not exist)"; return; }
  for p in run validation namelist cama_flood forcing/WFDE5_CRU_GPCC \
           run/work/data/clim cama_flood/work_global_weights cama_flood/dams \
           run/output ecland-build; do
    if [[ -d "${root}/${p}" ]]; then
      printf '  %-34s %8s  %5s entries\n' "${p}" \
        "$(du -sh --apparent-size "${root}/${p}" 2>/dev/null | cut -f1)" \
        "$(find "${root}/${p}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
    fi
  done
}

case "${ACTION}" in
  status)
    show_side "PERM   " "${PERM_ROOT}"
    echo
    show_side "SCRATCH" "${MIRROR}"
    ;;

  push)
    echo "push: ${PERM_ROOT} -> ${MIRROR}"
    mkdir -p "${MIRROR}"
    for p in "${PUSH_PATHS[@]}"; do
      if [[ ! -e "${PERM_ROOT}/${p}" ]]; then
        echo "  skip ${p} (absent here)"; continue
      fi
      echo "  ${p}"
      mkdir -p "${MIRROR}/${p}"
      "${RSYNC[@]}" "${PERM_ROOT}/${p}/" "${MIRROR}/${p}/"
    done
    # Loose scripts at the top of run/ -- copied by name so that run/work and
    # run/output cannot come along for the ride.
    mkdir -p "${MIRROR}/run"
    for g in "${PUSH_GLOBS[@]}"; do
      for f in ${PERM_ROOT}/${g}; do
        [[ -f "${f}" ]] || continue
        "${RSYNC[@]}" "${f}" "${MIRROR}/run/"
      done
    done
    echo "  run/ scripts"
    # The executable must move too. Leaving it on NFS while output goes to
    # Lustre is exactly what cost ifs-landbench 480 CPU-hours.
    if [[ -d "${ECLAND_BUILD}" ]]; then
      echo "  ${MIRROR_BUILD_REL} (from ${ECLAND_BUILD})"
      for sub in "${BUILD_SUBDIRS[@]}"; do
        [[ -d "${ECLAND_BUILD}/${sub}" ]] || continue
        mkdir -p "${MIRROR}/${MIRROR_BUILD_REL}/${sub}"
        "${RSYNC[@]}" "${ECLAND_BUILD}/${sub}/" "${MIRROR}/${MIRROR_BUILD_REL}/${sub}/"
      done
      echo "  -> run there with ECLAND_EXE=${MIRROR}/${MIRROR_BUILD_REL}/bin/ecland-master-dp"
    else
      echo "  skip ${MIRROR_BUILD_REL} (no build at ${ECLAND_BUILD}; set ECLAND_ROOT)"
    fi
    ;;

  pull)
    echo "pull: ${MIRROR} -> ${PERM_ROOT} (analysis products only)"
    [[ -d "${MIRROR}" ]] || { echo "ERROR: no mirror at ${MIRROR}" >&2; exit 1; }
    for p in "${PULL_PATHS[@]}"; do
      if [[ ! -e "${MIRROR}/${p}" ]]; then
        echo "  skip ${p} (absent there)"; continue
      fi
      echo "  ${p}"
      mkdir -p "${PERM_ROOT}/${p}"
      "${RSYNC[@]}" "${MIRROR}/${p}/" "${PERM_ROOT}/${p}/"
    done
    echo "  (raw output/ not pulled by design -- it is archived to ECFS)"
    ;;
esac
