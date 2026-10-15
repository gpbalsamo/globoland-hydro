#!/usr/bin/env bash
set -euo pipefail

# Run ecLand for a global window using ecland's own OFFICIAL run tooling
# (share/ecland/scripts/ecland_create_namelist.py + ecland_run_model.sh),
# not a hand-rolled driver -- see PLAN.md Milestone 3/4/5. Direct execution,
# no sbatch/srun: matches benchmark.yaml's `smoke` profile
# (require_confirmation: false) even with RUN_CMF=true, since real MPI here
# means `mpirun -np N` on this same interactive node, not a SLURM job.
#
# Stages surfclim/soilinit (from init_clim/build_global_surfclim_soilinit.sh)
# and a WFDE5-derived forcing slice (via forcing/preprocess_wfde5.py) into
# the exact directory layout + filenames ecland_create_namelist.py expects
# (${datadir}/clim/${group}/surfclim_${site}.nc,
#  ${datadir}/forcing/${group}/met_2DHT_${site}.nc), then lets the official
# scripts render the namelist and run the model.
#
# Set RUN_CMF=true to couple to CaMa-Flood with real multi-rank MPI (see
# PLAN.md Milestone 4/5): uses namelist/templates/namelist_ecland_50R1_cmf
# (LECMF1WAY=.TRUE.) and namelist_cmf_global.tmpl, and CMF_WEIGHTS_DIR
# (cama_flood/build_global_cmf_fixdir.sh + derive_global_cmf_weights.sh's
# output -- inpmat.nc/rivpar.nc/rivclim.nc/bifprm.txt/mpireg.nc/diminfo.txt,
# all at the SAME NPES as NPES here, since mpireg.nc bakes in the rank
# count). Runs `ecland-master-cmflood-dp` via `mpirun -np ${NPES}`.
#
# Usage:
#   run/run_ecland.sh
#   START_DATE=1988-01-01T00:00:00 N_HOURS=25 run/run_ecland.sh
#   RUN_CMF=true NPES=2 START_DATE=1988-01-01T00:00:00 N_HOURS=744 \
#     STA=GLOBAL_CMF_198801 run/run_ecland.sh

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

export ECLAND_ROOT=${ECLAND_ROOT:-/perm/pad/ecland}
RUN_CMF=${RUN_CMF:-false}
GROUP=${GROUP:-wfde5-ecland}
STA=${STA:-GLOBAL_19880101-19880102}
START_DATE=${START_DATE:-1988-01-01T00:00:00}
N_HOURS=${N_HOURS:-25}
NPES=${NPES:-2}

# Number of forcing records ecLand keeps resident at once. 0 (the default)
# is the original behaviour: the whole NDFORC-length series is loaded into
# GFOR(NPOI,NDFORC,12) at startup, which costs NPOI*NDFORC*12*8 bytes --
# ~5.8 GB for a month at 0.5 deg, ~74 GB for a leap year, i.e. a year does
# not fit. >0 caps that at NFORCWINDOW records and refills on demand.
# Requires the NFORCWINDOW support in ecLand's offline driver (gpbalsamo/
# ecland develop, commits 16549ed + 4b995b3); must be 0 or >= 8, and is
# rejected at startup together with LOADIAB or LPREINT.
NFORCWINDOW=${NFORCWINDOW:-0}

# ecLand output interval in HOURS. ecland_create_namelist.py hardcodes
# nfreq_post = max(1, 3600/tstep), i.e. hourly output of o_gg/o_efl/o_wat --
# ~670 GB and 8784 records per simulated year at 0.5 deg. CaMa-Flood's own
# output is already daily (IFRQ_OUT=24), so hourly ecLand output is finer
# than the coupled chain's own routing output. 0 = leave the rendered value
# alone (default, unchanged behaviour); >0 sets NFRPOS accordingly.
OUTPUT_FREQ_HOURS=${OUTPUT_FREQ_HOURS:-0}

# Write the surface-energy-balance stream (o_efl.nc, 4.6 GB/simulated year)?
# It is NOT needed for the water cycle or for the CaMa dam comparison -- with
# one-way coupling (LECMF1WAY) the dams change CaMa's river state only, and
# water-cycle closure needs o_wat (fluxes) and o_gg (storage), not o_efl.
# Dropping it saves ~166 GB over 1989-2024 on both PERM and ECFS.
# NOTE: this also removes the ability to check ENERGY-balance closure for
# those years (PLAN.md Milestone 3, still NOT STARTED). 1988's o_efl is
# already archived, so that capability is retained for one year.
WRITE_EFL=${WRITE_EFL:-true}

# ===========================================================================
#  SEGMENT LENGTH vs OUTPUT FREQUENCY -- a hard, measured constraint
# ===========================================================================
#  Output file size scales with the number of RECORDS written to it, i.e.
#  N_HOURS / OUTPUT_FREQ_HOURS. Measured on this system, global 0.5 deg:
#
#     segment   output    records   o_gg.nc    outcome
#     -------   ------    -------   -------    -----------------------------
#     1 year    daily         366     18 GB    completes  (0.70 h)
#     1 month   hourly        744     36 GB    completes
#     1 year    hourly       8784    424 GB    SIGBUS on the final write
#
#  So:  ANNUAL chunks -> DAILY output.   HOURLY output -> MONTHLY chunks.
#
#  The 424 GB failure is a large-file WRITE fault, not disk or quota: those
#  files are sparse, actual usage was 171 GB against 4.2 T free. The limit is
#  bracketed but not characterised, so this refuses anything beyond the
#  largest size actually proven to work here rather than guessing where it
#  really breaks. Set ALLOW_LARGE_OUTPUT=true to override deliberately (e.g.
#  to characterise the limit) -- it is not a knob for production runs.
# ===========================================================================
MAX_OUTPUT_RECORDS=${MAX_OUTPUT_RECORDS:-750}
ALLOW_LARGE_OUTPUT=${ALLOW_LARGE_OUTPUT:-false}
_ofreq=${OUTPUT_FREQ_HOURS:-0}; [[ "$_ofreq" -gt 0 ]] || _ofreq=1   # 0 = template default = hourly
_records=$(( N_HOURS / _ofreq ))
if [[ "$_records" -gt "$MAX_OUTPUT_RECORDS" && "$ALLOW_LARGE_OUTPUT" != "true" ]]; then
    cat >&2 <<MSG
ERROR: this run would write ${_records} records per output file
       (N_HOURS=${N_HOURS} / OUTPUT_FREQ_HOURS=${_ofreq}), above the
       ${MAX_OUTPUT_RECORDS}-record ceiling proven safe on this system.

       Largest configuration known to complete here: 744 records (one month
       of hourly output, o_gg.nc 36 GB). A full year of hourly output (8784
       records, 424 GB) dies with SIGBUS on the final write.

       Use one of:
         annual  chunk + daily  output : N_HOURS=8784 OUTPUT_FREQ_HOURS=24
         monthly chunk + hourly output : N_HOURS=744  OUTPUT_FREQ_HOURS=1

       run/submit_campaign.py --mode {annual,monthly} sets this correctly.
       ALLOW_LARGE_OUTPUT=true overrides, for characterising the limit only.
MSG
    exit 1
fi
echo "== output: ${_records} records/file (ceiling ${MAX_OUTPUT_RECORDS}) =="

# OpenMP/vector block length. Default 40 (sudim1s.F90). Exposed only to
# test whether results depend on blocking -- they must not.
ECLAND_NPROMA=${ECLAND_NPROMA:-0}

if [[ "$RUN_CMF" == "true" ]]; then
    # NOT ecland-master-cmflood-dp -- confirmed via src/surf/cmflood.cmake
    # that binary is built from offline/cmfld1s.F90, a STANDALONE
    # CaMa-Flood-only driver (reads pre-computed runoff from plain binary
    # files, ./runoff/Roff____YYYYMMDD.one) -- unrelated to online 1-way
    # coupling. The real online-coupled executable is plain
    # ecland-master-dp itself: master1s.F90 links libecland_cmflood_dp.so
    # and its own driver chain (cnt01s->cnt41s) calls CMF_FORCING_PUT +
    # CMF_DRV_ADVANCE directly, in-memory, every LECMF1WAY coupling step --
    # no file read at all. Found and fixed 2026-09-20 after a real crash
    # trying (and failing) to open that binary file with -cmflood-dp.
    ECLAND_EXE=${ECLAND_EXE:-${ECLAND_ROOT}/build/bin/ecland-master-dp}
    NAMELIST_TEMPLATE=${NAMELIST_TEMPLATE:-${REPO_ROOT}/namelist/templates/namelist_ecland_50R1_cmf}
    NAMELIST_CMF_TEMPLATE=${NAMELIST_CMF_TEMPLATE:-${REPO_ROOT}/namelist/templates/namelist_cmf_global.tmpl}
    CMF_WEIGHTS_DIR=${CMF_WEIGHTS_DIR:-${REPO_ROOT}/cama_flood/work_global_weights/glb_15min_out}
else
    ECLAND_EXE=${ECLAND_EXE:-${ECLAND_ROOT}/build/bin/ecland-master-dp}
    NAMELIST_TEMPLATE=${NAMELIST_TEMPLATE:-${REPO_ROOT}/namelist/templates/namelist_ecland_50R1_ctl}
fi

FORCING_SOURCE=${FORCING_SOURCE:-${REPO_ROOT}/forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_1988_01-01.nc}
SURFCLIM_SOURCE=${SURFCLIM_SOURCE:-${REPO_ROOT}/init_clim/work/output/wfde5-ecland/surfclim_GLOBAL_1988-2024.nc}
SOILINIT_SOURCE=${SOILINIT_SOURCE:-${REPO_ROOT}/init_clim/work/output/wfde5-ecland/surfinit_GLOBAL_1988-2024.nc}

# Multi-year restart chaining. Point RESTART_FROM at the PREVIOUS year's
# restartout.nc and it is staged AS soilinit -- that is the whole mechanism,
# and it is not obvious.
#
# The naive alternative (stage a restart separately and set LNF=.FALSE.) does
# NOTHING: the offline driver only calls RDRES when NSTART != 0, and the
# per-year namelist always has NSTART=0, so the run silently COLD-STARTS with
# no error and exit code 0. Confirmed in liaise-ecland, which is where this
# convention comes from: link the previous restartout.nc as soilinit, keep
# NSTART=0, and leave LNF at whatever the template says (.TRUE. -- do not
# patch it). Because the failure mode is silent, VERIFY_RESTART below checks
# the state was actually carried rather than trusting the exit code.
RESTART_FROM=${RESTART_FROM:-}
CLIM_SOILINIT="$SOILINIT_SOURCE"   # cold-start reference for the check below
if [[ -n "$RESTART_FROM" ]]; then
    [[ -f "$RESTART_FROM" ]] || { echo "ERROR: RESTART_FROM not found: $RESTART_FROM" >&2; exit 1; }
    SOILINIT_SOURCE="$RESTART_FROM"
    echo "== Restart chaining: soilinit <- ${RESTART_FROM} =="
fi
VERIFY_RESTART=${VERIFY_RESTART:-true}

# CaMa-Flood restart chaining -- a SEPARATE mechanism from ecLand's above, and
# it was MISSING entirely until 2026-10-10. The CaMa namelist templates hardcode
# LRESTART=false, and nothing here ever staged a CaMa restart, so EVERY segment
# of the 37-year campaign cold-started CaMa with an empty river network while
# ecLand itself chained correctly. The failure mode is silent -- exit 0, output
# present, budgets closed on the ecLand side -- and it cost two wrong diagnoses
# before it was found. Observable signature in the archived output: on 1 Jan the
# Amazon discharges -369 m3/s, the Congo 7 m3/s, the Mississippi exactly 0 for
# nine days, then the Amazon climbs to 50,617 by day 30 and 148,247 by day 90.
#
# Two consequences, both quantified in PLAN.md:
#   * the whole network is re-filled from runoff over ~2-3 months each year, and
#     the ~2,100 km3 of global river+flood storage standing at 31 Dec is simply
#     discarded -- that IS the control's apparent 1,894 km3/yr "lost water";
#   * with LDAMOUT, DAMOUT_INIT's `.not. LRESTART` branch additionally sets
#     P2RIVSTO = ConVol for every activated dam (cmf_ctrl_damout_mod.F90:266-269,
#     ungated by LiVnorm), CREATING 3,425-4,185 km3 of reservoir water every
#     1 January.
#
# CaMa reads its restart from CRESTSTO directly (cmf_ctrl_restart_mod.F90,
# READ_REST_CDF: CFILE=TRIM(CRESTSTO)), so pointing that at an absolute path is
# all that is needed -- deliberately NOT ecland_run_model.sh's -R/RESTARTCMF
# route, which also forces ecLand down the restartin.nc path that the
# RESTART_FROM mechanism above exists to avoid.
#
# Leave CMF_RESTART_FROM empty to cold-start CaMa. That is correct for the FIRST
# segment of a campaign only: with LDAMOUT it is also how reservoirs get their
# initial filling (LiVnorm), which is intended once and a water source every
# other time.
CMF_RESTART_FROM=${CMF_RESTART_FROM:-}
if [[ -n "$CMF_RESTART_FROM" ]]; then
    [[ -f "$CMF_RESTART_FROM" ]] || {
        echo "ERROR: CMF_RESTART_FROM not found: $CMF_RESTART_FROM" >&2; exit 1; }
    CMF_RESTART_FROM=$(cd "$(dirname "$CMF_RESTART_FROM")" && pwd)/$(basename "$CMF_RESTART_FROM")
fi
VERIFY_CMF_RESTART=${VERIFY_CMF_RESTART:-true}

# ECFS archive target, e.g. ec:/pad/wfde5-ecland. When set, the run's output
# is copied there after a successful run and verified with els before the
# local copy is considered expendable. PERM is quota-limited (10 T, 5.82 T
# already used), so a 37-year campaign has to move output off disk as it goes.
ECFS_DIR=${ECFS_DIR:-}

WORKDIR=${WORKDIR:-${REPO_ROOT}/run/work}
OUTPUT_DIR=${OUTPUT_DIR:-${REPO_ROOT}/run/output}

for f in "$ECLAND_EXE" "$FORCING_SOURCE" "$SURFCLIM_SOURCE" "$SOILINIT_SOURCE" "$NAMELIST_TEMPLATE"; do
    [[ -f "$f" ]] || { echo "ERROR: required input not found: $f" >&2; exit 1; }
done
if [[ "$RUN_CMF" == "true" ]]; then
    for f in "$NAMELIST_CMF_TEMPLATE" "${CMF_WEIGHTS_DIR}/inpmat.nc" "${CMF_WEIGHTS_DIR}/rivclim.nc" \
             "${CMF_WEIGHTS_DIR}/rivpar.nc" "${CMF_WEIGHTS_DIR}/bifprm.txt" \
             "${CMF_WEIGHTS_DIR}/mpireg.nc" "${CMF_WEIGHTS_DIR}/diminfo.txt"; do
        [[ -f "$f" ]] || { echo "ERROR: required CaMa-Flood input not found: $f" >&2; exit 1; }
    done
fi

DATADIR="${WORKDIR}/data"
CLIM_DIR="${DATADIR}/clim/${GROUP}"
FORCING_DIR="${DATADIR}/forcing/${GROUP}"
mkdir -p "$CLIM_DIR" "$FORCING_DIR" "$WORKDIR"

echo "== Staging surfclim/soilinit =="
cp -f "$SURFCLIM_SOURCE" "${CLIM_DIR}/surfclim_${STA}.nc"
cp -f "$SOILINIT_SOURCE" "${CLIM_DIR}/surfinit_${STA}.nc"

# N_HOURS is the INTEGRATION length. ecland_create_namelist.py sets
# nstop = nforcing*(forcing_step/tstep) - 2, i.e. it stops one forcing
# interval short of the last record, so integrating a full N_HOURS needs
# N_HOURS+1 forcing records. Without the extra record a "one year" segment
# covers 8759 h, the final daily write at 8760 h never happens, and 31 Dec is
# missing from every year (ecLand and CaMa alike). The extra record is the
# 00:00 1 Jan instant of the following year, taken from the next year's file.
_NREC=$(( N_HOURS + 1 ))
FORCING_SOURCE_NEXT=${FORCING_SOURCE_NEXT:-}
if [[ -z "$FORCING_SOURCE_NEXT" ]]; then
    _y=$(basename "$FORCING_SOURCE" | grep -oE "[0-9]{4}\.nc$" | cut -d. -f1)
    if [[ -n "$_y" ]]; then
        _cand="${FORCING_SOURCE%${_y}.nc}$((10#$_y + 1)).nc"
        [[ -s "$_cand" ]] && FORCING_SOURCE_NEXT="$_cand"
    fi
fi
echo "== Preparing WFDE5 forcing slice (${N_HOURS}h integration -> ${_NREC} records, from ${START_DATE}) =="
[[ -n "$FORCING_SOURCE_NEXT" ]] && echo "   continuing into $(basename "$FORCING_SOURCE_NEXT") for the final record"
_MET="${FORCING_DIR}/met_2DHT_${STA}.nc"

# Reuse an existing slice rather than rebuilding it, but ONLY after proving it
# is the slice this run needs. Rebuilding is cheap next to a wrong forcing file
# silently producing a plausible year, so the check is strict: right number of
# records, right first AND last timestamp, and every required variable present.
# Any doubt -> rebuild. FORCING_CACHE=false disables reuse entirely.
_reuse=false
if [[ "${FORCING_CACHE:-true}" == "true" && -s "$_MET" ]]; then
    if python3 - "$_MET" "$_NREC" "$START_DATE" <<'PYEOF'
import sys, netCDF4 as nc, numpy as np, datetime as dt
path, nrec, start = sys.argv[1], int(sys.argv[2]), sys.argv[3]
try:
    f = nc.Dataset(path)
    t = f.variables["time"]
    if len(t) != nrec:
        sys.exit(f"record count {len(t)} != {nrec}")
    d = nc.num2date(t[:], t.units)
    want = dt.datetime.fromisoformat(start)
    if not str(d[0]).startswith(want.strftime("%Y-%m-%d %H")):
        sys.exit(f"first record {d[0]} != {want}")
    hours = (d[-1] - d[0]).total_seconds() / 3600.0
    if abs(hours - (nrec - 1)) > 1e-6:
        sys.exit(f"span {hours} h != {nrec-1} h")
    for v in ("Tair", "Qair", "PSurf", "Wind_E", "Wind_N",
              "SWdown", "LWdown", "Rainf", "Snowf"):
        if v not in f.variables:
            sys.exit(f"missing variable {v}")
    sys.exit(0)
except SystemExit:
    raise
except Exception as e:
    sys.exit(f"unreadable: {e}")
PYEOF
    then
        _reuse=true
        echo "   reusing cached slice $(basename "$_MET") (validated: ${_NREC} records from ${START_DATE})"
    else
        echo "   cached slice rejected, rebuilding"
    fi
fi

if [[ "$_reuse" != "true" ]]; then
python3 "${REPO_ROOT}/forcing/preprocess_wfde5.py" \
    --input "$FORCING_SOURCE" \
    ${FORCING_SOURCE_NEXT:+--next-input "$FORCING_SOURCE_NEXT"} \
    --output "$_MET" \
    --start-date "$START_DATE" --n-hours "$_NREC" --overwrite
fi

echo "== Rendering namelist(s) (ecland's own ecland_create_namelist.py) =="
NAMELIST_ARGS=(-g "$GROUP" -n "$NAMELIST_TEMPLATE" -s "$STA" -t 2D -d "$DATADIR" -w "$WORKDIR")
if [[ "$RUN_CMF" == "true" ]]; then
    # diminfo_${STA}.txt is the one CMF input ecland_run_model.sh's RUN_CMF
    # path unconditionally `cp`s by that exact name -- everything else
    # (inpmat/rivpar/rivclim/bifprm/mpireg) is referenced by absolute path
    # directly inside the rendered CaMa namelist below, sidestepping that
    # script's ${STA}-suffixed symlink convention entirely.
    cp -f "${CMF_WEIGHTS_DIR}/diminfo.txt" "${CLIM_DIR}/diminfo_${STA}.txt"
    NAMELIST_ARGS+=(-c "$NAMELIST_CMF_TEMPLATE")
fi
python3 "${ECLAND_ROOT}/share/ecland/scripts/ecland_create_namelist.py" "${NAMELIST_ARGS[@]}"

RENDERED_NAMELIST="${WORKDIR}/namelist_${STA}"
[[ -f "$RENDERED_NAMELIST" ]] || { echo "ERROR: namelist was not rendered: $RENDERED_NAMELIST" >&2; exit 1; }

# DROFUNIT must equal the coupling interval in seconds. ecLand hands CaMa runoff
# accumulated as metres over ONE coupling interval (cnt41s.F90:218, buffer zeroed
# at :364), and CaMa divides by DROFUNIT to reach m3/m2/s. A mismatch rescales
# ALL discharge silently and leaves the land budget looking perfect: inheriting
# the 12-hourly reference's DROFUNIT=86400 while coupling hourly made discharge
# 24x too small for an entire 37-year campaign before anyone compared the Amazon
# against a gauge. Cheap to check, so check it.
if [[ "$RUN_CMF" == "true" ]]; then
    _rcmf="${WORKDIR}/namelist_cmf_${STA}"
    if [[ -f "$_rcmf" ]]; then
        _tcf=$(grep -oE "^\s*TCOUPFREQ\s*=\s*[0-9.]+" "$RENDERED_NAMELIST" | grep -oE "[0-9.]+$" | head -1)
        _dru=$(grep -oE "^\s*DROFUNIT\s*=\s*[0-9.]+" "$_rcmf" | grep -oE "[0-9.]+$" | head -1)
        if [[ -n "$_tcf" && -n "$_dru" ]]; then
            _want=$(python3 -c "print(float($_tcf)*3600.0)")
            python3 -c "import sys; sys.exit(0 if abs(float($_dru)-float($_want))<1e-6 else 1)" || {
                echo "ERROR: DROFUNIT=${_dru} but TCOUPFREQ=${_tcf} h requires ${_want}." >&2
                echo "       A mismatch rescales all CaMa discharge by ${_tcf}*3600/${_dru}." >&2
                exit 1; }
            echo "== DROFUNIT=${_dru} matches TCOUPFREQ=${_tcf} h =="
        else
            echo "WARNING: could not verify DROFUNIT against TCOUPFREQ" >&2
        fi
    fi
fi
# ecland_create_namelist.py renders the template with a FIXED set of
# format() keys, so NFORCWINDOW cannot be a {placeholder} in the template
# without patching that script. Inject it into the rendered &NAMDIM here
# instead, right after NDFORC, which keeps the templates usable with an
# unmodified ecLand and keeps NFORCWINDOW=0 byte-identical to before.
if [[ "$NFORCWINDOW" -gt 0 ]]; then
    grep -q '^\s*NDFORC=' "$RENDERED_NAMELIST" || {
        echo "ERROR: no NDFORC line in $RENDERED_NAMELIST to anchor NFORCWINDOW to" >&2; exit 1; }
    sed -i "0,/^\(\s*\)NDFORC=.*$/s//&\n    NFORCWINDOW=${NFORCWINDOW}/" "$RENDERED_NAMELIST"
    grep -q "NFORCWINDOW=${NFORCWINDOW}" "$RENDERED_NAMELIST" || {
        echo "ERROR: failed to inject NFORCWINDOW into $RENDERED_NAMELIST" >&2; exit 1; }
fi

# Override the hardcoded hourly post-processing frequency if asked.
if [[ "$OUTPUT_FREQ_HOURS" -gt 0 ]]; then
    _tstep=$(grep -oE "TSTEP=[0-9]+" "$RENDERED_NAMELIST" | head -1 | cut -d= -f2)
    [[ -n "$_tstep" ]] || { echo "ERROR: no TSTEP in $RENDERED_NAMELIST" >&2; exit 1; }
    _nfrpos=$(( OUTPUT_FREQ_HOURS * 3600 / _tstep ))
    [[ "$_nfrpos" -ge 1 ]] || { echo "ERROR: OUTPUT_FREQ_HOURS=$OUTPUT_FREQ_HOURS < TSTEP=${_tstep}s" >&2; exit 1; }
    sed -i "s/^\(\s*\)NFRPOS=[0-9]*/\1NFRPOS=${_nfrpos}/" "$RENDERED_NAMELIST"
    grep -qE "^\s*NFRPOS=${_nfrpos}\b" "$RENDERED_NAMELIST" || { echo "ERROR: failed to set NFRPOS" >&2; exit 1; }
    echo "== output every ${OUTPUT_FREQ_HOURS}h (NFRPOS=${_nfrpos}, TSTEP=${_tstep}s) =="
fi

if [[ "$ECLAND_NPROMA" -gt 0 ]]; then
    if grep -qE "^\s*NPROMA=" "$RENDERED_NAMELIST"; then
        sed -i "s/^\(\s*\)NPROMA=[0-9]*/\1NPROMA=${ECLAND_NPROMA}/" "$RENDERED_NAMELIST"
    else
        sed -i "0,/^\(\s*\)NDFORC=.*$/s//&\n    NPROMA=${ECLAND_NPROMA}/" "$RENDERED_NAMELIST"
    fi
    grep -qE "^\s*NPROMA=${ECLAND_NPROMA}\b" "$RENDERED_NAMELIST" || { echo "ERROR: failed to set NPROMA" >&2; exit 1; }
    echo "== NPROMA=${ECLAND_NPROMA} =="
fi

if [[ "$WRITE_EFL" != "true" ]]; then
    sed -i "s/^\(\s*\)LWREFL=.*/\1LWREFL=.FALSE.            ! disabled: WRITE_EFL=false/" "$RENDERED_NAMELIST"
    grep -qE "^\s*LWREFL=\.FALSE\." "$RENDERED_NAMELIST" || { echo "ERROR: failed to disable LWREFL" >&2; exit 1; }
    echo "== o_efl.nc disabled (WRITE_EFL=false) =="
fi

echo "Rendered: $RENDERED_NAMELIST"
grep -E "NSTOP|NLAT|NLON|NINDAT|NDFORC|NFORCWINDOW|LECMF1WAY" "$RENDERED_NAMELIST" || true

RUN_MODEL_ARGS=(-s "$STA" -b "$ECLAND_EXE" -w "${WORKDIR}/run" -o "$OUTPUT_DIR"
                -f "$FORCING_DIR" -i "$CLIM_DIR" -F 2D -n "$RENDERED_NAMELIST")

if [[ "$RUN_CMF" == "true" ]]; then
    RENDERED_NAMELIST_CMF="${WORKDIR}/namelist_cmf_${STA}"
    [[ -f "$RENDERED_NAMELIST_CMF" ]] || {
        echo "ERROR: CaMa namelist was not rendered: $RENDERED_NAMELIST_CMF" >&2
        echo "(ecland_create_namelist.py only renders it if LECMF1WAY=.TRUE. in the ecLand namelist above)" >&2
        exit 1
    }
    # CaMa-Flood's own output dir must be an ABSOLUTE path that exists
    # before the run starts: the default relative "./cmf_output/" is
    # relative to ecland_run_model.sh's ephemeral, rm-rf'd-then-recreated
    # run directory, which never has that subdirectory -- Fortran reports
    # this as "Permission denied" (really "directory doesn't exist"), not a
    # real permissions problem. Found 2026-09-20. NOT under
    # ${OUTPUT_DIR}/${STA} either -- ecland_run_model.sh does its own
    # `rm -rf ${OUTPUT_DIR}/${STA}` right before running, which would wipe
    # anything pre-staged there the same way.
    CMF_OUTDIR="${WORKDIR}/cmf_output_${STA}/"
    rm -rf "$CMF_OUTDIR"
    mkdir -p "$CMF_OUTDIR"

    # Fill in the absolute CaMa-Flood weight-file paths -- see
    # namelist_cmf_global.tmpl's own header for why these are absolute
    # rather than relying on ecland_run_model.sh's ${STA}-suffixed staging.
    sed -i \
        -e "s|__CAMA_BIFPRM__|${CMF_WEIGHTS_DIR}/bifprm.txt|" \
        -e "s|__CAMA_RIVCLIM__|${CMF_WEIGHTS_DIR}/rivclim.nc|" \
        -e "s|__CAMA_RIVPAR__|${CMF_WEIGHTS_DIR}/rivpar.nc|" \
        -e "s|__CAMA_MPIREG__|${CMF_WEIGHTS_DIR}/mpireg.nc|" \
        -e "s|__CAMA_INPMAT__|${CMF_WEIGHTS_DIR}/inpmat.nc|" \
        -e "s|__CAMA_OUTDIR__|${CMF_OUTDIR}|" \
        "$RENDERED_NAMELIST_CMF"
    # --- CaMa-Flood restart: patch LRESTART/CRESTSTO (see CMF_RESTART_FROM
    # above for why this is here at all, and what it cost to find).
    if [[ -n "$CMF_RESTART_FROM" ]]; then
        # CaMa with LDAMOUT reads 'damsto' from the restart unconditionally
        # (cmf_ctrl_restart_mod.F90 READ_REST_CDF). The naturalised control's
        # restart has no such variable, so chaining a dams run from a control
        # restart dies in NF90_INQ_VARID with an opaque NetCDF error -- check
        # it here instead, where the message can say what is actually wrong.
        if grep -qiE '^\s*LDAMOUT\s*=\s*\.?(TRUE|T)\.?' "$RENDERED_NAMELIST_CMF"; then
            python3 - "$CMF_RESTART_FROM" <<'PYEOF' || exit 1
import sys
import netCDF4 as nc
p = sys.argv[1]
with nc.Dataset(p) as d:
    if "damsto" not in d.variables:
        sys.exit(f"ERROR: LDAMOUT=.TRUE. but {p} has no 'damsto' -- this is a "
                 "naturalised-control restart. Chain a dams run from a dams restart.")
print(f"  CaMa restart carries damsto: {p}")
PYEOF
        fi
        sed -i \
            -e "s|^\s*LRESTART\s*=.*|LRESTART=.TRUE.          ! patched by run_ecland.sh (CMF_RESTART_FROM)|" \
            -e "s|^\s*CRESTSTO\s*=.*|CRESTSTO=\"${CMF_RESTART_FROM}\"|" \
            "$RENDERED_NAMELIST_CMF"
        grep -qE '^LRESTART=\.TRUE\.' "$RENDERED_NAMELIST_CMF" || {
            echo "ERROR: failed to patch LRESTART in $RENDERED_NAMELIST_CMF" >&2; exit 1; }
        grep -qF "CRESTSTO=\"${CMF_RESTART_FROM}\"" "$RENDERED_NAMELIST_CMF" || {
            echo "ERROR: failed to patch CRESTSTO in $RENDERED_NAMELIST_CMF" >&2; exit 1; }
        echo "== CaMa restart chaining: CRESTSTO <- ${CMF_RESTART_FROM} =="
    else
        echo "== CaMa COLD START (CMF_RESTART_FROM unset) -- correct only for a"
        echo "   campaign's first segment; see CMF_RESTART_FROM in this script =="
    fi
    echo "Rendered: $RENDERED_NAMELIST_CMF"
    grep -E "SYEAR|EYEAR|DT |IFRQ_INP|CMPIREGNC" "$RENDERED_NAMELIST_CMF" || true
    RUN_MODEL_ARGS+=(-c "$RENDERED_NAMELIST_CMF")
fi

if [[ "$RUN_CMF" == "true" ]]; then
    if [[ -n "${SLURM_JOB_ID:-}" ]]; then
        # Inside an sbatch allocation: plain `mpirun -np N` does not pick up
        # SLURM's own CPU binding and fails ("A request was made to bind to
        # that would result in binding more processes than cpus", confirmed
        # 2026-09-20) -- srun is the correct launcher here, inherits
        # --ntasks/--cpus-per-task from the allocation automatically. This
        # matches ecland's own ecland-launch script's default behaviour.
        echo "== Running ${ECLAND_EXE##*/} via srun (inside SLURM job ${SLURM_JOB_ID}) =="
        export LAUNCH="srun"
    else
        echo "== Running ${ECLAND_EXE##*/} via mpirun -np ${NPES} (direct, no sbatch/srun) =="
        export LAUNCH="mpirun -np ${NPES}"
    fi
else
    echo "== Running ecland-master-dp (direct execution, no sbatch/srun) =="
    export LAUNCH=""
fi
"${ECLAND_ROOT}/share/ecland/scripts/ecland_run_model.sh" "${RUN_MODEL_ARGS[@]}"

RUN_OUTPUT_DIR="${OUTPUT_DIR}/${STA}"
echo
echo "== Output =="
ls -lh "$RUN_OUTPUT_DIR"
echo
echo "Output dir: $RUN_OUTPUT_DIR"
echo "Log:        ${RUN_OUTPUT_DIR}/run.log"
if [[ "$RUN_CMF" == "true" ]]; then
    echo "CMF output: ${CMF_OUTDIR}"
    # log_CaMa.txt-<rank> is written into ecland_run_model.sh's ephemeral
    # run directory and is NOT moved anywhere -- only recoverable if the
    # run fails (that script's own `rm -rf ${RDIR}` cleanup only runs on
    # success/after a completed loop).
fi

# --- verify the restart state was actually carried -------------------------
# A silent cold start is the documented failure mode, so this must compare
# the MODEL'S OWN first output against the staged restart -- not the staged
# file against its source, which is a copy of it and therefore tautological.
# Discriminating power is large: measured on a 2-day chain test,
#   |prev_restart - first_output| = 3.3e-06   (genuine continuation)
#   |climatology  - first_output| = 176.1     (what a cold start gives)
if [[ -n "$RESTART_FROM" && "$VERIFY_RESTART" == "true" ]]; then
    echo "== Verifying restart continuity =="
    python3 - "$RESTART_FROM" "${RUN_OUTPUT_DIR}/o_gg.nc" "$CLIM_SOILINIT" <<'PYEOF'
import sys, numpy as np
from netCDF4 import Dataset
prev, out, clim = sys.argv[1], sys.argv[2], sys.argv[3]
A, B = Dataset(prev), Dataset(out)
C = Dataset(clim) if clim and clim != prev else None
var = next((v for v in ("SoilMoist","SoilTemp","AvgSurfT")
            if v in A.variables and v in B.variables), None)
if var is None:
    sys.exit("ERROR: no comparable prognostic in restart and o_gg")
a = np.ma.filled(A[var][:], np.nan).astype("f8")
b = B[var][0] if B[var].ndim > a.ndim else B[var][:]
b = np.ma.filled(b, np.nan).astype("f8")
if a.shape != b.shape:
    sys.exit(f"ERROR: {var} shape {a.shape} vs first output {b.shape}")
d_chain = np.nanmean(np.abs(a - b))
msg = f"  {var}: |prev_restart - first_output| = {d_chain:.4g}"
if C is not None and var in C.variables:
    c = np.ma.filled(C[var][:], np.nan).astype("f8")
    if c.shape == a.shape:
        d_cold = np.nanmean(np.abs(c - b))
        msg += f" ; |climatology - first_output| = {d_cold:.4g}"
        print(msg)
        if not d_chain < 0.01 * d_cold:
            sys.exit("ERROR: first output is no closer to the staged restart than to "
                     "climatology -- the run almost certainly COLD-STARTED")
        print("  OK: state was carried from the previous segment")
        sys.exit(0)
print(msg)
print("  WARNING: no climatology reference available; continuity not proven")
PYEOF
fi

# --- verify CaMa's river storage was actually carried ----------------------
# The ecLand check above passes happily while CaMa cold-starts, which is
# exactly how the missing CaMa restart went unnoticed for a whole 37-year
# campaign. Check CaMa separately, against its own first output day: a
# continued run starts the year holding the previous 31 Dec storage
# (~2,100 km3 globally), a cold-started one starts empty and has only
# whatever one day of runoff put in.
if [[ "$RUN_CMF" == "true" && -n "$CMF_RESTART_FROM" && "$VERIFY_CMF_RESTART" == "true" ]]; then
    echo "== Verifying CaMa-Flood restart continuity =="
    python3 - "$CMF_RESTART_FROM" "${CMF_OUTDIR}/o_rivsto.nc" <<'PYEOF'
import sys
import numpy as np
from netCDF4 import Dataset

prev, out = sys.argv[1], sys.argv[2]


def total(a):
    a = np.ma.masked_invalid(np.ma.masked_greater(np.asarray(a, dtype="f8"), 1e19))
    return float(a.sum()) * 1e-9          # km3


with Dataset(prev) as A:
    staged = total(A["rivsto"][:])
with Dataset(out) as B:
    first = total(B["rivsto"][0])

print(f"  staged restart rivsto   = {staged:10.1f} km3")
print(f"  first output day rivsto = {first:10.1f} km3")
if staged <= 0:
    sys.exit("ERROR: staged CaMa restart holds no river storage")
ratio = first / staged
print(f"  ratio = {ratio:.3f}")
# One day of global runoff is ~100 km3, a few percent of the standing storage,
# so a genuine continuation cannot move the total by anything like a factor 2.
if not 0.5 < ratio < 2.0:
    sys.exit("ERROR: CaMa's first output day does not continue the staged "
             "restart -- the run almost certainly COLD-STARTED CaMa "
             "(check LRESTART/CRESTSTO in the rendered CaMa namelist)")
print("  OK: CaMa river storage was carried from the previous segment")
PYEOF
fi

# --- archive to ECFS -------------------------------------------------------
if [[ -n "$ECFS_DIR" ]]; then
    echo "== Archiving to ECFS: ${ECFS_DIR}/${STA} =="
    emkdir -p "${ECFS_DIR}/${STA}" 2>/dev/null || true
    for f in "${RUN_OUTPUT_DIR}"/*; do
        [[ -f "$f" ]] || continue
        b=$(basename "$f")
        ecp -o "$f" "${ECFS_DIR}/${STA}/${b}" || { echo "ERROR: ecp failed for $b" >&2; exit 1; }
    done
    # CaMa-Flood output lives OUTSIDE ${RUN_OUTPUT_DIR} (see CMF_OUTDIR above),
    # so it was previously not archived at all. For a control-vs-dams
    # comparison this is the output that actually differs: with one-way
    # coupling the dams change CaMa's river state, not ecLand's.
    if [[ "$RUN_CMF" == "true" && -d "$CMF_OUTDIR" ]]; then
        emkdir -p "${ECFS_DIR}/${STA}/cmf" 2>/dev/null || true
        for f in "${CMF_OUTDIR}"/*.nc; do
            [[ -f "$f" ]] || continue
            ecp -o "$f" "${ECFS_DIR}/${STA}/cmf/$(basename "$f")" \
                || { echo "ERROR: ecp failed for CaMa $(basename "$f")" >&2; exit 1; }
        done
        echo "== Archived CaMa output ($(du -sh "$CMF_OUTDIR" | cut -f1)) =="
    fi

    echo "== Verifying ECFS copy =="
    els -l "${ECFS_DIR}/${STA}/" || { echo "ERROR: els failed" >&2; exit 1; }
    echo "Archived. Local copy at ${RUN_OUTPUT_DIR} may now be removed."
fi

