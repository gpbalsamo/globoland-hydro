#!/usr/bin/env bash
set -euo pipefail

# Build global surfclim/soilinit via ecland's own actively-maintained
# tools/create_forcing/ecland_create_forcing.py (2D pipeline, bounding box
# set to the whole globe), NOT the older init_clim.py driver -- see
# PLAN.md Milestone 2's 2026-09-17 investigation note: init_clim.py's own
# `osm_pyutils.grid_gaussian` import no longer resolves against the current
# ecland checkout, whereas this tool is what that checkout actually
# maintains today.
#
# The bounding box (clatn/clats/clonw/clone = 89.75/-89.75/-179.75/179.75,
# dx=0.5) is deliberately the cell-center convention, not 90/-180/-90/180 --
# it reproduces extract_create_inicond_2D.bash's own built-in "global" box
# formula (90-dx/2, -90+dx/2, -180+dx/2, 180-dx/2), so the output grid lands
# exactly on WFDE5's real, verified grid (see docs/forcing_variables.md).
#
# The only real data acquisition this triggers is a single-date, global,
# ~25-parameter ERA5 surface analysis via MARS (tens of MB) -- the static
# climatology (climate.v015/639l_2) is a direct file copy from the shared
# ECMWF archive, no retrieval at all.
#
# The tool writes lat in native MARS/GRIB order (descending, north-to-south)
# -- confirmed 2026-09-19 on a real run. WFDE5 (forcing/download_wfde5.py) is
# ascending (south-to-north). This script flips surfclim/soilinit to
# ascending immediately after the tool runs (flip_latitude_to_ascending.py)
# and then runs validate_init_grid.py as a real gate -- it exits non-zero if
# the grids don't end up identical, rather than trusting that they do.
#
# Usage:
#   module load nco
#   init_clim/build_global_surfclim_soilinit.sh
#   START_DATE=19880101 END_DATE=20241231 init_clim/build_global_surfclim_soilinit.sh

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

export ECLAND_ROOT=${ECLAND_ROOT:-/perm/pad/ecland}
export GROUP=${GROUP:-wfde5-ecland}
export START_DATE=${START_DATE:-19880101}
export END_DATE=${END_DATE:-20241231}
export WORKDIR=${WORKDIR:-${REPO_ROOT}/init_clim/work/era5_ini}
export OUTDIR=${OUTDIR:-${REPO_ROOT}/init_clim/work/output}
FORCING_REF=${FORCING_REF:-${REPO_ROOT}/forcing/WFDE5_CRU_GPCC/WFDE5_CRU_GPCC_1988_01-01.nc}

FORCING_TOOL="${ECLAND_ROOT}/tools/create_forcing/ecland_create_forcing.py"
[[ -f "$FORCING_TOOL" ]] || { echo "ERROR: not found: $FORCING_TOOL (check ECLAND_ROOT)" >&2; exit 1; }

if ! command -v ncks >/dev/null 2>&1; then
    echo "ERROR: ncks not on PATH -- run 'module load nco' first" >&2
    exit 1
fi

mkdir -p "$WORKDIR" "$OUTDIR"
RENDERED_CONFIG="${WORKDIR}/config_global.yaml"
envsubst < "${SCRIPT_DIR}/config_global.yaml.tmpl" > "$RENDERED_CONFIG"
echo "Rendered config: $RENDERED_CONFIG"

echo "== Running ecland_create_forcing.py (global 2D box) =="
python3 "$FORCING_TOOL" -c "$RENDERED_CONFIG"

SURFCLIM="${OUTDIR}/${GROUP}/surfclim_GLOBAL_${START_DATE:0:4}-${END_DATE:0:4}.nc"
SOILINIT="${OUTDIR}/${GROUP}/surfinit_GLOBAL_${START_DATE:0:4}-${END_DATE:0:4}.nc"

echo
echo "== Output =="
ls -lh "${OUTDIR}/${GROUP}/"

echo
echo "== Fixing latitude order (native MARS/GRIB is descending; WFDE5 is ascending) =="
python3 "${SCRIPT_DIR}/flip_latitude_to_ascending.py" "$SURFCLIM" "$SOILINIT"

echo
echo "== Validating against the real WFDE5 forcing grid =="
if [[ -f "$FORCING_REF" ]]; then
    python3 "${SCRIPT_DIR}/validate_init_grid.py" \
        --forcing "$FORCING_REF" --surfclim "$SURFCLIM" --soilinit "$SOILINIT"
else
    echo "WARNING: FORCING_REF not found ($FORCING_REF) -- skipping grid validation." >&2
    echo "Do not trust these outputs until validate_init_grid.py has actually been run." >&2
fi

echo
echo "surfclim: $SURFCLIM"
echo "soilinit: $SOILINIT"
