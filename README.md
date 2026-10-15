# GloboLand-Hydro

Global land-surface and hydrology runs on WFDE5 forcing, 1988–2024 — the global counterpart of
RegioLand-Hydro (whose dwarfs crop their forcing and ancillaries from the archive built here).

| Folder | Was | What |
|---|---|---|
| `ecland/` | wfde5-ecland (branch `initial-wfde5-workflow`, b0a64e5) | Global WFDE5 0.5° archive, global surfclim/soilinit, ecLand + CaMa-Flood global runs |
| `lisflood/` | wfde5-glofas (`master`, 5975c48) | Global LISFLOOD (GloFAS v5) on WFDE5, retaining runoff |

Both were imported with their full git history on 2026-10-15. Each keeps its own README, CLAUDE.md,
AGENTS.md and PLAN.md: work inside one folder and follow its rules.

**Data and live working copies.** Unlike RegioLand-Hydro, both code bases still keep their products
inside their own tree (`forcing/`, `run/`, `init_clim/work`, `work/`, all gitignored). On ECMWF HPC the
data stay in the original working copies `/perm/pad/wfde5-ecland` and `/perm/pad/wfde5-glofas`, which the
RegioLand-Hydro dwarfs read (`ecland/config/paths.yaml: wfde5_ecland_root`). A fresh clone of this
repository therefore has code only: point its `config/paths.yaml` at the data, or run from the original
working copies until the data move here.
