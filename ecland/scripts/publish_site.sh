#!/usr/bin/env bash
set -euo pipefail

# Publish local files (dashboards, reports, forcing for download, ...) to
# https://sites.ecmwf.int/<space>/<name>/ via `sitesctl` (module load sites).
#
# NEW SCRIPT, not a port. liaise-ecland has no committed equivalent -- its
# own CLAUDE.md ("Redeployed to sites.ecmwf.int/pad/liaise/chains/ via
# sitesctl") shows dashboards were pushed by calling sitesctl directly, ad
# hoc, with no generator/publish script ever committed to that repo. This
# generalises that same sitesctl CLI into a small, reusable, documented
# wrapper instead.
#
# Auth: sitesctl's own --token flag reads $API_AUTHENTICATION_TOKEN,
# $MASTER_TOKEN or $HTTP_ACCESS_TOKEN automatically, but this project's
# token is exported under a differently-named variable (see README.md /
# AGENTS.md) -- default ECMWF_WFDE5, override with --token-env if you used
# a different name in your .profile. The token value itself is never
# printed or logged.
#
# Usage:
#   module load sites
#   scripts/publish_site.sh --source reports/wfde5-fast-.../  --destination /status/
#   scripts/publish_site.sh --source validation/dashboard/index.html --destination /
#   scripts/publish_site.sh --source ... --destination ... --dry-run   # print the sitesctl command, do nothing
#
# Defaults match https://sites.ecmwf.int/pad/wfde5/ (space=pad, name=wfde5).

SPACE=${SITE_SPACE:-pad}
NAME=${SITE_NAME:-wfde5}
TOKEN_ENV=ECMWF_WFDE5
DESTINATION=/
RECURSIVE=0
DRY_RUN=0
SOURCE=""

usage() {
    cat <<'EOF'
Usage: publish_site.sh --source PATH [options]

Required:
  --source PATH          Local file or directory to upload.

Options:
  --destination PATH     Remote path under the site root (default: /).
  --space NAME            Site space (default: $SITE_SPACE or "pad").
  --name NAME             Site name (default: $SITE_NAME or "wfde5").
  --token-env VAR_NAME    Environment variable holding the site's auth
                          token (default: ECMWF_WFDE5). The token value
                          itself is never printed.
  --recursive             Upload a directory recursively (see sitesctl's
                          own --recursive flag).
  --dry-run               Print the sitesctl command that would run, and
                          the resulting URL, without uploading anything.
  -h, --help              Show this help and exit.

Requires `module load sites` first (provides the `sitesctl` binary) and the
token environment variable to be set and non-empty -- see AGENTS.md before
running this for real: publishing is visible to others and needs the same
explicit go-ahead as a real data download.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source) SOURCE=$2; shift 2 ;;
        --destination) DESTINATION=$2; shift 2 ;;
        --space) SPACE=$2; shift 2 ;;
        --name) NAME=$2; shift 2 ;;
        --token-env) TOKEN_ENV=$2; shift 2 ;;
        --recursive) RECURSIVE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ -z "$SOURCE" ]]; then
    echo "ERROR: --source is required" >&2
    usage >&2
    exit 1
fi

TOKEN=${!TOKEN_ENV:-}
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: \$$TOKEN_ENV is not set or empty -- export your site token" \
         "(see .profile) before running this, or pass --token-env to point" \
         "at whichever variable you used." >&2
    exit 1
fi

RECURSIVE_FLAG=()
if [[ "$RECURSIVE" == "1" ]]; then
    RECURSIVE_FLAG=(--recursive)
fi

SITE_URL="https://sites.ecmwf.int/${SPACE}/${NAME}${DESTINATION}"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would run:"
    echo "  sitesctl site --space $SPACE --name $NAME --token \$$TOKEN_ENV" \
         "content upload --source $SOURCE --destination $DESTINATION" \
         "${RECURSIVE_FLAG[*]}"
    echo "Would then be reachable at: $SITE_URL"
    exit 0
fi

if ! command -v sitesctl >/dev/null 2>&1; then
    echo "ERROR: sitesctl not found on PATH -- run 'module load sites' first" >&2
    exit 1
fi

echo "Uploading $SOURCE -> ${SPACE}/${NAME}${DESTINATION}"
sitesctl site --space "$SPACE" --name "$NAME" --token "$TOKEN" \
    content upload --source "$SOURCE" --destination "$DESTINATION" \
    "${RECURSIVE_FLAG[@]}"

echo "Done. Should be reachable at: $SITE_URL"
