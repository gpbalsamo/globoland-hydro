"""Tests that need no data: the settings builder's contract and the grid nesting algebra.

The real claim this repository rests on -- that repTotalRunoffMaps/repSurfaceRunoffMaps are
output-only and do not move discharge -- cannot be tested without running LISFLOOD twice, so it
lives in PLAN.md as a measured result (one global day, dis.nc compared bitwise) rather than
pretending to be a unit test here.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "common"))
import glofas  # noqa: E402


def test_block_replicate_is_exact_and_conservative():
    rng = np.random.default_rng(0)
    a = rng.random((7, 11))
    g = glofas.block_replicate(a)
    assert g.shape == (70, 110)
    # The exact property is that every sub-cell IS its parent, bit for bit.
    assert np.array_equal(g, np.repeat(np.repeat(a, 10, 0), 10, 1))
    for di in range(10):
        for dj in range(10):
            assert np.array_equal(g[di::10, dj::10], a)
    # The block mean then returns the parent to floating point, but NOT bit-exactly: summing 100
    # identical doubles and dividing by 100 rounds. Asserting equality here would be asserting
    # something false about IEEE arithmetic, not something true about the regridding.
    assert np.allclose(g.reshape(7, 10, 11, 10).mean(axis=(1, 3)), a, rtol=0, atol=1e-15)


def test_bilinear_weights_clamp_and_reproduce_nodes():
    src = np.array([0.0, 1.0, 2.0, 3.0])
    i0, i1, w = glofas.bilinear_weights(src, np.array([-5.0, 0.0, 1.5, 3.0, 9.0]))
    got = src[i0] * (1 - w) + src[i1] * w
    assert np.allclose(got, [0.0, 0.0, 1.5, 3.0, 3.0])          # clamped at both ends


def test_bilinear_weights_handle_descending_source():
    asc = np.array([0.0, 1.0, 2.0, 3.0])
    des = asc[::-1].copy()
    q = np.array([0.25, 1.5, 2.75])
    ia, ib, wa = glofas.bilinear_weights(asc, q)
    ja, jb, wb = glofas.bilinear_weights(des, q)
    assert np.allclose(asc[ia] * (1 - wa) + asc[ib] * wa, des[ja] * (1 - wb) + des[jb] * wb)


def test_interp_2d_does_not_overshoot():
    rng = np.random.default_rng(1)
    a = rng.random((6, 8))
    latw = np.linspace(10.25, 12.75, 6); lonw = np.linspace(0.25, 3.75, 8)
    latg = np.linspace(10.025, 12.975, 60); long_ = np.linspace(0.025, 3.975, 80)
    g = glofas.interp_2d(a, latw, lonw, latg, long_)
    assert g.min() >= a.min() - 1e-6 and g.max() <= a.max() + 1e-6


def test_nesting_rejects_a_grid_that_is_not_10_to_1():
    latw = np.linspace(-89.75, 89.75, 360); lonw = np.linspace(-179.75, 179.75, 720)
    latg = np.linspace(89.975, -59.975, 3000)
    bad = np.linspace(-179.975, 179.975, 3600)                   # 5:1, not 10:1
    try:
        glofas.nesting(latw, lonw, latg, bad)
    except ValueError:
        return
    raise AssertionError("nesting() accepted a non-10:1 longitude axis")


def test_make_settings_help_runs():
    r = subprocess.run([sys.executable, str(REPO / "glofas" / "make_settings.py"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "--no-runoff-maps" in r.stdout
