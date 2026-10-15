#!/usr/bin/env bash
#SBATCH --job-name=wfde5_cmf
#SBATCH --nodes=1
#SBATCH --ntasks=2
# 8 threads measured as the sweet spot on the coupled global 0.5 deg
# configuration: 3.09x faster than 1 thread, where 16 threads buys only
# a further 12% for double the cores. Outputs are byte-identical across
# 1/4/8/16 threads, so this is free speed, not a trade.
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --qos=nf

# Batch wrapper for run/run_ecland.sh's RUN_CMF=true path -- see PLAN.md
# Milestone 4/5. Needed because 2 MPI ranks + CaMa-Flood coupling use
# ~4.3-4.5 GiB resident EACH (confirmed 2026-09-19/20), exceeding this
# project's interactive session's fixed 8 GiB memory cgroup almost
# immediately regardless of forcing duration or coupling frequency -- not a
# memory leak, just more memory than an interactive session is allotted.
# --mem=32G here gives real headroom over the ~8.6 GiB two ranks need.
#
# Requested only after explicit user approval (2026-09-20) -- see
# AGENTS.md's "any sbatch/SLURM submission" approval gate.
#
# Usage:
#   sbatch run/run_ecland_cmf.slurm
#   STA=GLOBALCMF_19880101-19880131 N_HOURS=744 sbatch run/run_ecland_cmf.slurm

set -euo pipefail

# NOT ${BASH_SOURCE[0]}-based resolution -- SLURM copies this script to a
# spool directory (/var/spool/slurmd/job<id>/slurm_script) before running
# it, so dirname($BASH_SOURCE) is NOT the repo (confirmed 2026-09-20: "No
# such file or directory" trying to exec a path under /var/spool/slurmd/).
# $SLURM_SUBMIT_DIR is the directory `sbatch` was invoked FROM.
REPO_ROOT=${SLURM_SUBMIT_DIR:?SLURM_SUBMIT_DIR not set -- run via sbatch, not directly}

# Settings come from a file passed as $1, NOT from the submitting shell's
# environment. ECMWF's sbatch wrapper injects its own
# `--export=EC_user_time_limit=...`, which REPLACES the default
# `--export=ALL`, so exported variables do NOT reach the job -- the script
# silently falls back to every default instead. Confirmed 2026-09-20: a run
# submitted with N_HOURS=8784 in the environment logged "Preparing WFDE5
# forcing slice (744h ...)" and began re-running January. Script arguments
# are unaffected by --export, so a sourced config file is the reliable
# channel.
#
#   sbatch run/run_ecland_cmf.slurm run/configs/year_1988.env
#
if [[ $# -ge 1 ]]; then
    CONFIG_FILE="$1"
    [[ -r "$CONFIG_FILE" ]] || { echo "ERROR: config file not readable: $CONFIG_FILE" >&2; exit 1; }
    echo "== Sourcing config: ${CONFIG_FILE} =="
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

module load prgenv/intel intel/2021.4 hpcx-openmpi/2.9.0

export RUN_CMF=true
export NPES=${SLURM_NTASKS:-2}
export STA=${STA:-GLOBALCMF_19880101-19880131}
export START_DATE=${START_DATE:-1988-01-01T00:00:00}
export N_HOURS=${N_HOURS:-744}

# Passed through so a longer run can bound ecLand's resident forcing array
# instead of scaling it with N_HOURS -- GFOR is NPOI*NDFORC*12*8 bytes, so a
# leap year at 0.5 deg would need ~74 GB without this. 0 = off (default).
# See run_ecland.sh's own comment for the ecLand-side requirements.
export NFORCWINDOW=${NFORCWINDOW:-0}
# Which assembled WFDE5 file to slice the run's forcing out of. The default
# in run_ecland.sh is the single-month January 1988 file; a year run must
# point at the full-year file.
[[ -n "${FORCING_SOURCE:-}" ]] && export FORCING_SOURCE
# Which CaMa-Flood weights directory to use. The only rank-dependent file
# in it is mpireg.nc (diminfo.txt carries grid info only), so a different
# MPI width means a directory whose mpireg.nc has that many regions.
# Ready-made mpireg-<N>.nc for N=1..10,16,30 ship with the static network
# data; they must match --ntasks exactly.
[[ -n "${CMF_WEIGHTS_DIR:-}" ]] && export CMF_WEIGHTS_DIR
export OUTPUT_FREQ_HOURS=${OUTPUT_FREQ_HOURS:-0}
export ECLAND_NPROMA=${ECLAND_NPROMA:-0}
# Multi-year chaining + archive; see run_ecland.sh for why RESTART_FROM is
# staged AS soilinit and why the result is verified rather than trusted.
[[ -n "${RESTART_FROM:-}" ]] && export RESTART_FROM
# CaMa's restart is a SEPARATE file from ecLand's and must be exported here
# too. Missing this is the same class of omission as ECLAND_EXE /
# NAMELIST_CMF_TEMPLATE below: the config sets it, `source` makes it a shell
# variable, and without an explicit export it never reaches run_ecland.sh --
# which would then cold-start CaMa while reporting success, i.e. exactly the
# bug CMF_RESTART_FROM exists to fix.
[[ -n "${CMF_RESTART_FROM:-}" ]] && export CMF_RESTART_FROM
[[ -n "${ECFS_DIR:-}" ]] && export ECFS_DIR
export VERIFY_RESTART=${VERIFY_RESTART:-true}
export VERIFY_CMF_RESTART=${VERIFY_CMF_RESTART:-true}
export WRITE_EFL=${WRITE_EFL:-true}
# Let a config select a different executable (e.g. a -O0 -g -init=snan build
# for debugging). NOT exporting this silently sent a snan diagnostic run
# through the optimised binary on 2026-09-26 and wasted the cycle -- the
# symptom was a 31 min runtime where -O0 takes hours, and "Line Unknown" in a
# -g build. run_ecland.sh echoes "Executable built:", which is the thing to
# check before trusting any debug run.
[[ -n "${ECLAND_EXE:-}" ]] && export ECLAND_EXE
# Let a config select different namelist templates, e.g. an A/B pair that
# differs in one physics switch. Same class of omission as ECLAND_EXE above:
# run_ecland.sh honours these, but a value that never reaches the job is
# silently replaced by the default template, so the "B" run would be a second
# copy of "A" and the diff would come out zero -- a false negative that looks
# like a clean result.
[[ -n "${NAMELIST_TEMPLATE:-}" ]] && export NAMELIST_TEMPLATE
[[ -n "${NAMELIST_CMF_TEMPLATE:-}" ]] && export NAMELIST_CMF_TEMPLATE

# OpenMP threads per MPI rank. ECMWF's shell profile sets OMP_NUM_THREADS=1,
# so without this every rank runs single-threaded no matter how many cores
# the allocation holds -- confirmed inside job 39010675, which ran 2 ranks at
# 1 thread each on a 256-core node. Must be paired with a matching
# --cpus-per-task on the sbatch line; SLURM_CPUS_PER_TASK is the allocation's
# own answer, so default to it rather than to 1.
#
# NOT a guaranteed win: this repo measured CaMa-Flood threading 1.6x SLOWER
# at ~1,400 active river cells (glb_15min, our configuration) and only
# faster at 34,000+ (glb_03min). Both ranks run the same executable, so this
# applies to ecLand and CaMa alike. Measure before trusting a value.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-${SLURM_CPUS_PER_TASK:-1}}
export OMP_PLACES=${OMP_PLACES:-cores}
export OMP_PROC_BIND=${OMP_PROC_BIND:-close}
echo "== OMP_NUM_THREADS=${OMP_NUM_THREADS}  NPES=${NPES}  (cpus/task=${SLURM_CPUS_PER_TASK:-unset}) =="

# sbatch CLI options override the #SBATCH directives above, so a long run is
#   sbatch --time=18:00:00 --mem=48G ... run/run_ecland_cmf.slurm
# rather than a second copy of this script.

"${REPO_ROOT}/run/run_ecland.sh"
