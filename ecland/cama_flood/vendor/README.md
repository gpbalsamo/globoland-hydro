# Vendored companion tools

`calc_outclm.py`, `calc_rivpar.py`, `gen_mask_mixKinIner.py` are re-vendored
unmodified from `gpbalsamo/liaise-ecland` (`cama_flood/vendor/`, commit
`ab8a0ab`, 2026-09-17), which itself vendored them from an ECMWF colleague's
personal, non-permanent ecFlow suite include directory
(`/ec/vol/ifs/rd/pad/ja8f/include/`, E. Dutra 2019/2020) — otherwise-unavailable
operational CaMa-Flood tooling, not something to reimplement. See each file's
own header for its specific provenance note and (for `calc_outclm.py`) the one
local dtype fix already applied upstream.

Required by `cama_flood/build_global_cmf_fixdir.sh` — see that script's header.

This is a second-hand vendoring (liaise-ecland vendored from the colleague's
directory; this repo vendors from liaise-ecland's copy, not the original
directory directly) — if that original directory ever needs to be
re-consulted (e.g. a newer fix appears there), check `liaise-ecland`'s own
copy first, since it may already have picked it up.
