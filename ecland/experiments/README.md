# experiments/

One subdirectory per experiment (e.g. `pilot_2026/`), each self-contained with
the metadata `run/run_ecland.sh` logs: this repo's own commit, ecLand's
commit/version, forcing version, experiment ID, dates, grid, executable,
namelist, hostname, start/end time. No experiment output (NetCDF/GRIB) is
committed — only metadata and small diagnostic summaries. See the root
`.gitignore`.
