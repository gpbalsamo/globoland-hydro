#!/usr/bin/env bash
set -euo pipefail
# Link one year's meteo (prepare_meteo.py) and LISVAP output (run_lisvap.py) under the file-name
# prefixes the operational GloFAS settings expect (PrefixPrecipitation="glofas_tp_*" etc.):
# glofas_{tp,ta,e0,eS0,eT0}_<Y>.nc in <work>/forcing_lisflood. Unchanged from <exp>-glofas.
#   usage: glofas/link_forcing.sh <work_dir> <year>
W=$1; y=$2; F=$W/forcing_lisflood; mkdir -p "$F"
for f in "$W/meteo/glofas_tp_$y.nc" "$W/meteo/glofas_ta_$y.nc" \
         "$W/lisvap_out/$y/e0.nc" "$W/lisvap_out/$y/es.nc" "$W/lisvap_out/$y/et.nc"; do
    [[ -s "$f" ]] || { echo "missing $f" >&2; exit 1; }
done
ln -sf "$W/meteo/glofas_tp_$y.nc" "$F/glofas_tp_$y.nc"
ln -sf "$W/meteo/glofas_ta_$y.nc" "$F/glofas_ta_$y.nc"
ln -sf "$W/lisvap_out/$y/e0.nc"   "$F/glofas_e0_$y.nc"
ln -sf "$W/lisvap_out/$y/es.nc"   "$F/glofas_eS0_$y.nc"
ln -sf "$W/lisvap_out/$y/et.nc"   "$F/glofas_eT0_$y.nc"
