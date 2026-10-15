"""Synthetic tests for run/check_run.py -- no real ecLand executable or
output, tiny fabricated run directories only.
"""
import sys
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "run"))

import check_run  # noqa: E402


def _write_output_var(path: Path, data: np.ndarray) -> None:
    with Dataset(path, "w") as ds:
        ds.createDimension("time", data.shape[0])
        ds.createDimension("lat", data.shape[1])
        ds.createDimension("lon", data.shape[2])
        var = ds.createVariable("AvgSurfT", "f4", ("time", "lat", "lon"))
        var[:] = data


def _make_clean_run_dir(tmp_path: Path) -> Path:
    output_dir = tmp_path / "GLOBAL_19880101-19880102"
    output_dir.mkdir()
    (output_dir / "run.log").write_text("STEP=48 WALs 2.390\nMASTER1s: Time total: 105.397\n")
    (output_dir / "restartout.nc").write_bytes(b"not a real netcdf, existence is all that's checked by this test path")
    data = np.full((2, 3, 4), 280.0, dtype=np.float32)
    data[0, 0, 0] = 1.0e20  # ecLand's own fill value -- must NOT be flagged
    _write_output_var(output_dir / "o_gg.nc", data)
    return output_dir


def test_pass_on_clean_run(tmp_path):
    output_dir = _make_clean_run_dir(tmp_path)
    assert check_run.main(["--output-dir", str(output_dir)]) == 0


def test_fails_on_missing_restart(tmp_path):
    output_dir = _make_clean_run_dir(tmp_path)
    (output_dir / "restartout.nc").unlink()
    assert check_run.main(["--output-dir", str(output_dir)]) == 1


def test_fails_on_fortran_abort_in_log(tmp_path):
    output_dir = _make_clean_run_dir(tmp_path)
    (output_dir / "run.log").write_text(
        "STEP=0 DATE= 19880101 0\n"
        "Caught signal 8 (Floating point exception: floating-point invalid operation)\n"
        "forrtl: error (75): floating point exception\n"
    )
    assert check_run.main(["--output-dir", str(output_dir)]) == 1


def test_fails_on_real_nan_not_fill_value(tmp_path):
    output_dir = _make_clean_run_dir(tmp_path)
    data = np.full((2, 3, 4), 280.0, dtype=np.float32)
    data[1, 1, 1] = np.nan  # a genuine NaN, not the 1e20 fill value
    _write_output_var(output_dir / "o_gg.nc", data)
    assert check_run.main(["--output-dir", str(output_dir)]) == 1


def test_fails_on_no_output_directory(tmp_path):
    assert check_run.main(["--output-dir", str(tmp_path / "does-not-exist")]) == 1
