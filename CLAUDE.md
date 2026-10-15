# CLAUDE.md

Two independent code bases: `ecland/` (global WFDE5 → ecLand → CaMa-Flood) and `lisflood/` (global
GloFAS v5 / LISFLOOD on WFDE5). Work inside one and follow its own CLAUDE.md, AGENTS.md and PLAN.md.

Repository-wide rules: no data in git; any `sbatch`, `git push` or multi-year run needs explicit approval;
the global WFDE5 archive in `/perm/pad/wfde5-ecland/forcing` is read by the RegioLand-Hydro dwarfs and
must never be moved or rewritten without checking them.
