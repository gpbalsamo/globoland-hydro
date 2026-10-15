"""Synthetic tests for forcing/preprocess_wfde5.py -- no real WFDE5 archive,
tiny in-memory-sized NetCDF fixtures only.
"""
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from netCDF4 import Dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "forcing"))

import preprocess_wfde5 as pp  # noqa: E402


def _write_synthetic_wfde5(path: Path, n_hours: int, lat: np.ndarray, lon: np.ndarray) -> None:
    with Dataset(path, "w") as ds:
        ds.createDimension("time", n_hours)
        ds.createDimension("lat", lat.size)
        ds.createDimension("lon", lon.size)

        tvar = ds.createVariable("time", "f8", ("time",))
        tvar[:] = np.arange(n_hours, dtype=np.float64)
        tvar.units = "hours since 1988-01-01 00:00:00"
        tvar.calendar = "proleptic_gregorian"

        latvar = ds.createVariable("lat", "f4", ("lat",))
        latvar[:] = lat
        lonvar = ds.createVariable("lon", "f4", ("lon",))
        lonvar[:] = lon

        # One masked ("ocean") cell at (0, 0); everything else valid.
        mask = np.zeros((n_hours, lat.size, lon.size), dtype=bool)
        mask[:, 0, 0] = True

        for name, value in [("Tair", 280.0), ("Qair", 0.005), ("PSurf", 99000.0),
                             ("SWdown", 100.0), ("LWdown", 300.0), ("Rainf", 0.0001),
                             ("Snowf", 0.0), ("Wind", 3.0)]:
            data = np.ma.array(np.full((n_hours, lat.size, lon.size), value, dtype=np.float32), mask=mask)
            var = ds.createVariable(name, "f4", ("time", "lat", "lon"), fill_value=1.0e20)
            var[:] = data


@pytest.fixture
def synthetic_input(tmp_path):
    lat = np.array([-1.0, 0.0, 1.0], dtype=np.float32)
    lon = np.array([-2.0, -1.0, 0.0, 1.0], dtype=np.float32)
    path = tmp_path / "wfde5_synthetic.nc"
    _write_synthetic_wfde5(path, n_hours=30, lat=lat, lon=lon)
    return path, lat, lon


def test_convert_masked_cells_use_safe_fill_not_zero(tmp_path, synthetic_input):
    input_path, lat, lon = synthetic_input
    output_path = tmp_path / "met_2DHT_TEST.nc"

    pp.convert(input_path, output_path, datetime(1988, 1, 1, 0, 0, 0), n_hours=25, overwrite=False)

    with Dataset(output_path) as ds:
        tair = np.asarray(ds.variables["Tair"][:])
        psurf = np.asarray(ds.variables["PSurf"][:])
        # The masked cell (lat idx 0, lon idx 0) must NOT be 0.0 -- that's
        # exactly what crashed ecLand's surfexcdriver_ctl on 2026-09-19.
        assert not np.any(tair[:, 0, 0] == 0.0)
        assert not np.any(psurf[:, 0, 0] == 0.0)
        assert np.allclose(tair[:, 0, 0], pp.MASKED_FILL_VALUES["Tair"])
        assert np.allclose(psurf[:, 0, 0], pp.MASKED_FILL_VALUES["PSurf"])
        # Real (unmasked) data must pass through unchanged.
        assert np.allclose(tair[:, 1, 1], 280.0)


def test_convert_splits_wind_into_components(tmp_path, synthetic_input):
    input_path, lat, lon = synthetic_input
    output_path = tmp_path / "met_2DHT_TEST.nc"
    pp.convert(input_path, output_path, datetime(1988, 1, 1, 0, 0, 0), n_hours=25, overwrite=False)

    with Dataset(output_path) as ds:
        assert "Wind_E" in ds.variables
        assert "Wind_N" in ds.variables
        wind_e = np.asarray(ds.variables["Wind_E"][:])
        wind_n = np.asarray(ds.variables["Wind_N"][:])
        assert np.allclose(wind_n, 0.0)
        # Magnitude must reproduce the original scalar wind speed exactly.
        assert np.allclose(np.sqrt(wind_e**2 + wind_n**2), wind_e)


def test_convert_rejects_start_date_not_in_file(tmp_path, synthetic_input):
    input_path, lat, lon = synthetic_input
    output_path = tmp_path / "met_2DHT_TEST.nc"
    with pytest.raises(ValueError, match="not found in input time axis"):
        pp.convert(input_path, output_path, datetime(1990, 1, 1, 0, 0, 0), n_hours=25, overwrite=False)


def test_convert_rejects_too_many_hours(tmp_path, synthetic_input):
    input_path, lat, lon = synthetic_input
    output_path = tmp_path / "met_2DHT_TEST.nc"
    with pytest.raises(ValueError, match="only 30 are available"):
        pp.convert(input_path, output_path, datetime(1988, 1, 1, 0, 0, 0), n_hours=999, overwrite=False)
