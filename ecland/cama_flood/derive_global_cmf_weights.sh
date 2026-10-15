#!/usr/bin/env bash
set -euo pipefail

# Derive the ecLand <-> CaMa-Flood interpolation weights for a GLOBAL
# (unclipped) coupled run -- generalises liaise-ecland's
# cama_flood/derive_cmf_weights.sh (see docs/migration_from_liaise.md) by
# REMOVING its two LIAISE-specific steps entirely, per docs/cama_interface.md:
# "for a global run there is no clip: the full global CaMa-Flood network is
# the target."
#
# What LIAISE's script did that this one does NOT need:
#   1. sel_region.py clip of ncdata.nc/bifprm.txt/rivpar.nc/outclm.nc/mpireg.nc
#      to a small regional box (with -e to keep crossing basins whole) --
#      global means using FIXDIR's own files AS-IS, no clip.
#   2. Flattening mpireg.nc to a single region -- that was specifically
#      because LIAISE ran NPROC_CMF=1. For a global run WANTING real MPI
#      parallelism, build_global_cmf_fixdir.sh's own NPES_CMF=<N> already
#      selects a genuine multi-region mpireg-<N>.nc from the shared
#      CMFDIR -- use it directly, unflattened.
#
# What's still needed, unclipped: gen_inpmat.py mapping THIS repo's own
# ecLand grid (surfclim/soilinit, 360x720 global 0.5 deg) onto the global
# river network in FIXDIR, plus rivclim.nc (a plain variable subset of
# ncdata.nc, no index selection) and diminfo.txt.
#
# Requires the same ecland-side setup as derive_cmf_weights.sh (the
# gen_inpmat.py Cython extension, built automatically here too) and FIXDIR
# from build_global_cmf_fixdir.sh at the SAME CMF_RES.
#
# Usage:
#   cd cama_flood
#   FIXDIR=./work_global/glb_15min CMF_RES=glb_15min \
#     ECLAND_GRID_FILE=../init_clim/work/output/wfde5-ecland/surfclim_GLOBAL_1988-2024.nc \
#     ./derive_global_cmf_weights.sh

ECLAND_ROOT=${ECLAND_ROOT:-/perm/pad/ecland}
SCRIPTS_DIR="${ECLAND_ROOT}/tools/create_forcing/scripts/osm_pyutils"

CMFDIR=${CMFDIR:-/home/rdx/data/50r1/camaflood/static_network_nc_v2.1}
CMF_RES=${CMF_RES:?set CMF_RES, e.g. glb_15min -- must match the FIXDIR build}
FIXDIR=${FIXDIR:?set FIXDIR to the build_global_cmf_fixdir.sh output dir for this CMF_RES}
NPES_CMF=${NPES_CMF:?set NPES_CMF to the same value used when building FIXDIR (selects mpireg-<N>.nc)}

# ecLand grid reference file, used only for its lat/lon dimensions -- any
# file on the exact global ecLand grid works (surfclim and soilinit share
# it). Must be the SAME grid forcing/download_wfde5.py produces (see
# docs/grid_strategy.md) -- init_clim/validate_init_grid.py is what proves
# that, not this script.
ECLAND_GRID_FILE=${ECLAND_GRID_FILE:?set ECLAND_GRID_FILE to a surfclim/soilinit file on the real ecLand grid}

# Compute the real (2-way) inverse mapping, or fill it with dummy values
# (1-way coupling only). Matches LECMF1WAY=.TRUE. with no 2-way lake
# coupling (NCMF2LAKEC=0), the same default liaise-ecland used.
COMPUTE_INV=${COMPUTE_INV:-false}

WORKDIR=${WORKDIR:-./work_global_weights/${CMF_RES}}
OUTDIR=${OUTDIR:-./work_global_weights/${CMF_RES}_out}

# Resolution-dependent, NOT clip-dependent (see derive_cmf_weights.sh's own
# note: gen_inpmat.py preallocates by the GLOBAL river-network grid size
# regardless of clipping, and NMAX only reflects how many 0.5 deg ecLand
# cells overlap one river-network cell -- observed 5-11 regardless of
# CMF_RES). Same table as derive_cmf_weights.sh; do not fall through to a
# generic wildcard at finer resolutions without re-deriving this by the
# same reasoning (glb_01min's global grid is large enough to OOM a naive
# guess -- see that script's own warning).
case ${CMF_RES} in
  glb_15min) NMAX=156; NMAXI=40  ;;
  glb_06min) NMAX=23;  NMAXI=78  ;;
  glb_03min) NMAX=48;  NMAXI=152 ;;
  glb_01min) NMAX=10;  NMAXI=40  ;;
  *) echo "ERROR: unsupported CMF_RES: ${CMF_RES} (add an explicit NMAX/NMAXI case, don't guess)" >&2; exit 1 ;;
esac

for f in "$ECLAND_GRID_FILE" "$FIXDIR/ncdata.nc" "$FIXDIR/bifprm.txt" \
         "$FIXDIR/rivpar.nc" "$FIXDIR/outclm.nc" "$FIXDIR/mpireg.nc" \
         "$CMFDIR/$CMF_RES/1min.catmxy.nc" "$CMFDIR/$CMF_RES/1min.grdare.nc"; do
    [[ -f "$f" ]] || { echo "ERROR: required input not found: $f" >&2; exit 1; }
done

# Build (or rebuild, if stale) the Cython extension gen_inpmat.py needs --
# same staleness check as build_global_cmf_fixdir.sh/derive_cmf_weights.sh.
SO_FILE=$(find "$SCRIPTS_DIR" -maxdepth 1 -iname 'cython_ext*.so' -print -quit)
if [[ -z "$SO_FILE" || "$SCRIPTS_DIR/cython_ext.pyx" -nt "$SO_FILE" ]]; then
    echo "Building cython_ext (into ${SCRIPTS_DIR})"
    ( cd "$SCRIPTS_DIR" && rm -f cython_ext.c cython_ext*.so && rm -rf osm_pyutils build \
      && python3 setup_cython.py build_ext --inplace --path=. )
    NESTED_SO=$(find "$SCRIPTS_DIR/osm_pyutils" -maxdepth 1 -iname 'cython_ext*.so' -print -quit 2>/dev/null)
    if [[ -n "$NESTED_SO" ]]; then
        mv "$NESTED_SO" "$SCRIPTS_DIR/"
        rmdir "$SCRIPTS_DIR/osm_pyutils" 2>/dev/null || true
    fi
fi

ECLAND_GRID_FILE=$(cd -- "$(dirname -- "$ECLAND_GRID_FILE")" && pwd)/$(basename -- "$ECLAND_GRID_FILE")
FIXDIR=$(cd -- "$FIXDIR" && pwd)

# Resolve OUTDIR too, before cd'ing into WORKDIR below -- a relative OUTDIR
# would otherwise silently be reinterpreted relative to WORKDIR instead of
# the directory this script was invoked from (the exact bug
# derive_cmf_weights.sh's own header warns about, for FIXDIR).
mkdir -p "$WORKDIR" "$OUTDIR"
OUTDIR=$(cd -- "$OUTDIR" && pwd)
cd "$WORKDIR"
export PYTHONPATH="${SCRIPTS_DIR}:${PYTHONPATH:-}"

CINV_FLAG=""
if [[ "$COMPUTE_INV" != "true" ]]; then
    CINV_FLAG="-cinv"
fi

echo "== [$CMF_RES] Deriving ecLand -> CaMa-Flood interpolation weights (global, no clip) =="
time python3 "$SCRIPTS_DIR/gen_inpmat.py" \
    -igrid "$ECLAND_GRID_FILE" \
    -iriv "$FIXDIR/ncdata.nc" \
    -ihcat "$CMFDIR/$CMF_RES/1min.catmxy.nc" \
    -iharea "$CMFDIR/$CMF_RES/1min.grdare.nc" \
    -o inpmat_tmp.nc \
    ${CINV_FLAG} \
    -n "$NMAX" -nI "$NMAXI"

# gen_inpmat.py's own netCDF4-python writer produces chunk sizes that do not
# match its variables' real dimensions (observed 2026-09-20: inpx/inpy
# chunked [12,360,720] against an actual (24,720,1440) shape -- the input
# grid's dims leaking into the river-network variables' chunk spec). This
# writes without error but crashed ecland-master-cmflood-dp's Fortran/HDF5
# reader deep inside zlib's inflate. liaise-ecland's own validated
# derive_cmf_weights.sh NEVER used gen_inpmat.py's raw output directly --
# it always re-wrote it via `cdo -f nc4 -z zip_6 -selindexbox`, even though
# that command's only *documented* purpose was clipping. A global run has
# no clip, but this re-write (chunking/compression normalisation) is
# hypothesised to be required regardless -- see PLAN.md Milestone 4/5 for
# whether this was confirmed to fix the crash or not. Do not skip this step
# just because there is nothing to clip.
cdo -f nc4 -z zip_6 copy inpmat_tmp.nc inpmat.nc

echo "== [$CMF_RES] Extracting rivclim.nc (plain variable subset, no clip) =="
ncks -O -v ctmare,elevtn,nxtdst,rivlen,fldhgt,lat,lon,nextx,nexty "$FIXDIR/ncdata.nc" rivclim.nc

echo "== Writing diminfo.txt =="
NX=$(ncdump -h rivclim.nc | grep "^.lon = " | head -1 | awk '{print $3}')
NY=$(ncdump -h rivclim.nc | grep "^.lat = " | head -1 | awk '{print $3}')
NLFP=$(ncdump -h rivclim.nc | grep "^.lev = " | head -1 | awk '{print $3}')
NXIN=$(ncdump -h inpmat.nc | grep "^.lonin = " | head -1 | awk '{print $3}')
NYIN=$(ncdump -h inpmat.nc | grep "^.latin = " | head -1 | awk '{print $3}')
INPN=$(ncdump -h inpmat.nc | grep "^.lev = " | head -1 | awk '{print $3}')

cat > diminfo.txt << EOF
$NX       !! nXX
$NY       !! nYY
$NLFP     !! floodplain layer
$NXIN     !! input nXX
$NYIN     !! input nYY
$INPN     !! input num
NONE
0     !! west  edge
0     !! east  edge
0     !! north edge
0     !! south edge
EOF

cp -f inpmat.nc rivclim.nc diminfo.txt "$FIXDIR/rivpar.nc" "$FIXDIR/outclm.nc" "$FIXDIR/bifprm.txt" "$FIXDIR/mpireg.nc" "$OUTDIR/"

echo
echo "Done. Global CaMa-Flood coupling weights written to: $OUTDIR"
ls -lh "$OUTDIR"
