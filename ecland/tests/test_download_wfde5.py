"""Synthetic tests for forcing/download_wfde5.py's request-building and
assembly logic -- no CDS call, no real WFDE5 archive. Tiny in-memory NetCDF
files stand in for what CDS actually delivers (one file per variable per
month, short WFDE5 variable names, global grid) so assemble_period() can be
exercised end-to-end via --skip-download.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from netCDF4 import Dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "forcing"))

import download_wfde5 as dl  # noqa: E402


def test_build_requests_has_no_area_key_and_splits_by_reference_dataset():
    requests = dl.build_requests(1988, ["01"], "3_0")
    assert len(requests) == 2
    cru, cru_gpcc = requests
    assert cru["reference_dataset"] == "cru"
    assert cru_gpcc["reference_dataset"] == "cru_and_gpcc"
    assert set(cru["variable"]) == set(dl.CDS_VARIABLES_CRU.keys())
    assert set(cru_gpcc["variable"]) == set(dl.CDS_VARIABLES_CRU_GPCC.keys())
    # No global crop: CDS has no "area" request key at all (see module
    # docstring) -- the request must never try to add one.
    for request in requests:
        assert "area" not in request
        assert request["product"] == "wfde5"
        assert request["month"] == ["01"]


def test_output_path_for_full_year_vs_month_subset():
    out_dir = Path("out")
    assert dl.output_path_for(out_dir, 1988, dl.ALL_MONTHS) == out_dir / "WFDE5_CRU_GPCC_1988.nc"
    assert dl.output_path_for(out_dir, 1988, ["01"]) == out_dir / "WFDE5_CRU_GPCC_1988_01-01.nc"


def _write_dynamic_var(path: Path, short_name: str, n_time: int, lat: np.ndarray, lon: np.ndarray) -> None:
    with Dataset(path, "w") as ds:
        ds.createDimension("time", n_time)
        ds.createDimension("lat", lat.size)
        ds.createDimension("lon", lon.size)
        tvar = ds.createVariable("time", "f8", ("time",))
        tvar[:] = np.arange(n_time, dtype=np.float64)
        tvar.units = "hours since 1988-01-01 00:00:00"
        tvar.calendar = "standard"
        latvar = ds.createVariable("lat", "f4", ("lat",))
        latvar[:] = lat
        lonvar = ds.createVariable("lon", "f4", ("lon",))
        lonvar[:] = lon
        var = ds.createVariable(short_name, "f4", ("time", "lat", "lon"))
        var[:] = np.full((n_time, lat.size, lon.size), 1.0, dtype=np.float32)


def _write_static_var(path: Path, short_name: str, lat: np.ndarray, lon: np.ndarray) -> None:
    with Dataset(path, "w") as ds:
        ds.createDimension("lat", lat.size)
        ds.createDimension("lon", lon.size)
        latvar = ds.createVariable("lat", "f4", ("lat",))
        latvar[:] = lat
        lonvar = ds.createVariable("lon", "f4", ("lon",))
        lonvar[:] = lon
        var = ds.createVariable(short_name, "f4", ("lat", "lon"))
        var[:] = np.full((lat.size, lon.size), 100.0, dtype=np.float32)


@pytest.fixture
def synthetic_raw_dir(tmp_path):
    """Stand in for what --skip-download expects under raw-dir/<year>/."""
    lat = np.array([-1.0, 0.0, 1.0], dtype=np.float32)
    lon = np.array([-2.0, -1.0, 0.0, 1.0], dtype=np.float32)
    n_time = 3  # e.g. a 3-hour synthetic "month"
    raw_dir = tmp_path / "raw"
    year_dir = raw_dir / "1988"
    year_dir.mkdir(parents=True)

    for short_name in dl.SHORT_NAMES - dl.STATIC_VARIABLES:
        _write_dynamic_var(year_dir / f"{short_name}.nc", short_name, n_time, lat, lon)
    for short_name in dl.STATIC_VARIABLES:
        _write_static_var(year_dir / f"{short_name}.nc", short_name, lat, lon)

    return raw_dir, lat, lon, n_time


def test_assemble_period_end_to_end_via_skip_download(tmp_path, synthetic_raw_dir):
    raw_dir, lat, lon, n_time = synthetic_raw_dir
    output_dir = tmp_path / "out"

    exit_code = dl.main(
        [
            "--start-year", "1988",
            "--end-year", "1988",
            "--months", "01",
            "--skip-download",
            "--keep-raw",
            "--raw-dir", str(raw_dir),
            "--output-dir", str(output_dir),
        ]
    )
    assert exit_code == 0

    output_path = output_dir / "WFDE5_CRU_GPCC_1988_01-01.nc"
    assert output_path.exists()

    with Dataset(output_path) as ds:
        assert ds.variables["lat"].shape == lat.shape
        assert ds.variables["lon"].shape == lon.shape
        assert ds.variables["time"].shape == (n_time,)
        for short_name in dl.SHORT_NAMES - dl.STATIC_VARIABLES:
            assert short_name in ds.variables
            assert ds.variables[short_name].shape == (n_time, lat.size, lon.size)
            assert ds.variables[short_name].units == dl.VARIABLE_ATTRS[short_name][0]
        for short_name in dl.STATIC_VARIABLES:
            assert short_name in ds.variables
            assert ds.variables[short_name].shape == (lat.size, lon.size)
        assert ds.variables["Height_Lev1"][...] == dl.HEIGHT_LEV1
        assert ds.variables["Height_Levuv"][...] == dl.HEIGHT_LEVUV
        # No LIAISE-era cropping language, and no crop actually applied --
        # the full synthetic "global" grid must survive assembly unchanged.
        assert "LIAISE" not in ds.comment


def test_identify_variable_rejects_unknown_file(tmp_path):
    path = tmp_path / "unknown.nc"
    with Dataset(path, "w") as ds:
        ds.createDimension("lat", 2)
        ds.createDimension("lon", 2)
        ds.createVariable("lat", "f4", ("lat",))
        ds.createVariable("lon", "f4", ("lon",))
        ds.createVariable("totally_unrecognised_field", "f4", ("lat", "lon"))
    with pytest.raises(ValueError, match="could not identify"):
        dl.identify_variable(path)
