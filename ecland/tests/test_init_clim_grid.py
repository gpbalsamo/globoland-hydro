"""Synthetic tests for init_clim/flip_latitude_to_ascending.py and
init_clim/validate_init_grid.py -- no real WFDE5/MARS/ERA5 data, tiny
in-memory-sized NetCDF fixtures only.
"""
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "init_clim"))

import flip_latitude_to_ascending as flip  # noqa: E402
import validate_init_grid as validate  # noqa: E402


def _write_grid_file(path: Path, lat: np.ndarray, lon: np.ndarray, extra_vars=()) -> None:
    with Dataset(path, "w") as ds:
        ds.createDimension("lat", lat.size)
        ds.createDimension("lon", lon.size)
        latvar = ds.createVariable("lat", "f8", ("lat",))
        latvar[:] = lat
        lonvar = ds.createVariable("lon", "f8", ("lon",))
        lonvar[:] = lon
        for name, fill_value in extra_vars:
            var = ds.createVariable(name, "f4", ("lat", "lon"), fill_value=fill_value)
            # Distinct per-row values so a flip is actually detectable, not
            # a coincidental no-op on uniform data.
            var[:] = np.arange(lat.size)[:, None] * np.ones((1, lon.size))


def test_needs_flip_detects_descending():
    assert flip.needs_flip(np.array([10.0, 5.0, 0.0])) is True
    assert flip.needs_flip(np.array([0.0, 5.0, 10.0])) is False
    assert flip.needs_flip(np.array([5.0])) is False


def test_flip_in_place_reorders_lat_and_data(tmp_path):
    lat_desc = np.array([2.0, 1.0, 0.0])
    lon = np.array([-1.0, 0.0, 1.0])
    path = tmp_path / "descending.nc"
    _write_grid_file(path, lat_desc, lon, extra_vars=[("field", 1e20)])

    changed = flip.flip_in_place(path)
    assert changed is True

    with Dataset(path) as ds:
        lat_after = np.asarray(ds.variables["lat"][:])
        field_after = np.asarray(ds.variables["field"][:])

    assert np.allclose(lat_after, [0.0, 1.0, 2.0])
    # Row 0 used to be lat=2.0 with value 0; after flip it should carry the
    # value that was originally at lat=0.0 (value 2), proving data moved
    # together with the coordinate, not just the coordinate variable alone.
    assert np.allclose(field_after[0], 2.0)
    assert np.allclose(field_after[-1], 0.0)


def test_flip_in_place_noop_when_already_ascending(tmp_path):
    lat_asc = np.array([0.0, 1.0, 2.0])
    lon = np.array([-1.0, 0.0, 1.0])
    path = tmp_path / "ascending.nc"
    _write_grid_file(path, lat_asc, lon, extra_vars=[("field", 1e20)])

    changed = flip.flip_in_place(path)
    assert changed is False


def test_validate_init_grid_pass_when_grids_match(tmp_path, capsys):
    lat = np.array([-1.0, 0.0, 1.0])
    lon = np.array([-2.0, -1.0, 0.0, 1.0])

    forcing = tmp_path / "forcing.nc"
    surfclim = tmp_path / "surfclim.nc"
    soilinit = tmp_path / "soilinit.nc"
    for path in (forcing, surfclim, soilinit):
        _write_grid_file(path, lat, lon)

    exit_code = validate.main(
        ["--forcing", str(forcing), "--surfclim", str(surfclim), "--soilinit", str(soilinit)]
    )
    assert exit_code == 0
    assert "PASS" in capsys.readouterr().out


def test_validate_init_grid_fails_on_axis_mismatch(tmp_path, capsys):
    lat_asc = np.array([-1.0, 0.0, 1.0])
    lat_desc = np.array([1.0, 0.0, -1.0])
    lon = np.array([-2.0, -1.0, 0.0, 1.0])

    forcing = tmp_path / "forcing.nc"
    surfclim = tmp_path / "surfclim.nc"
    soilinit = tmp_path / "soilinit.nc"
    _write_grid_file(forcing, lat_asc, lon)
    _write_grid_file(surfclim, lat_desc, lon)  # deliberately mismatched
    _write_grid_file(soilinit, lat_asc, lon)

    exit_code = validate.main(
        ["--forcing", str(forcing), "--surfclim", str(surfclim), "--soilinit", str(soilinit)]
    )
    assert exit_code == 1
    assert "FAIL" in capsys.readouterr().out
