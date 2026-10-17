# tests/vectorize/test_fit.py
import math
import numpy as np
import pytest
from autoswf.vectorize.fit import FitSettings, detail_settings, fit_chain
from autoswf.vectorize.trace import boundary_chains

def sample(start, segs, n=16):
    out, cur = [], np.array(start)
    for s in segs:
        end = np.array(s[-2:])
        ctrl = np.array(s[1:3]) if s[0] == "Q" else (cur + end) / 2
        t = np.linspace(0, 1, n)[:, None]
        out.append((1 - t) ** 2 * cur + 2 * (1 - t) * t * ctrl + t ** 2 * end)
        cur = end
    return np.vstack(out)

def outline(labels):
    (c,) = [c for c in boundary_chains(labels) if c.closed]
    return c

def test_disc_becomes_a_few_smooth_quadratics_on_the_true_circle():
    yy, xx = np.mgrid[0:100, 0:100]
    lab = np.where((xx + 0.5 - 50) ** 2 + (yy + 0.5 - 50) ** 2 <= 40 ** 2, 0, -1)
    start, segs = fit_chain(outline(lab).points, True)
    assert 4 <= len(segs) <= 12 and sum(s[0] == "Q" for s in segs) >= len(segs) - 2
    r = np.hypot(*(sample(start, segs) - 50).T)
    assert np.abs(r - 40).max() <= 1.2

def test_square_keeps_its_exact_corners():
    lab = np.full((60, 60), -1); lab[10:50, 10:50] = 0
    start, segs = fit_chain(outline(lab).points, True)
    pts = sorted({tuple(np.round(start, 6))} | {tuple(np.round(s[-2:], 6)) for s in segs})
    assert len(segs) == 4 and all(s[0] == "L" for s in segs)
    assert np.allclose(pts, [(10, 10), (10, 50), (50, 10), (50, 50)], atol=1e-6)

def test_brush_tip_stays_sharp():
    lab = np.full((60, 120), -1)
    for x in range(10, 110):                    # a spike tapering from 30 px to a point at x = 110
        h = (110 - x) * 0.15
        lab[int(30 - h):int(30 + h) + 1, x] = 0
    start, segs = fit_chain(outline(lab).points, True)
    tip = max([start] + [s[-2:] for s in segs], key=lambda p: p[0])
    assert tip[0] >= 109

def test_open_chain_ends_are_pinned_and_staircases_are_straight():
    pts = [(0, 0)]
    for i in range(20):
        pts += [(2 * i + 1, i), (2 * i + 2, i), (2 * i + 2, i + 1)]
    pts = np.array(pts, float)
    start, segs = fit_chain(pts, False)
    assert tuple(start) == (0, 0) and tuple(segs[-1][-2:]) == (40, 20) and len(segs) == 1 and segs[0][0] == "L"

def test_tolerance_trades_nodes_for_fidelity():
    yy, xx = np.mgrid[0:200, 0:200]
    lab = np.where((xx - 100) ** 2 / 90 ** 2 + (yy - 100) ** 2 / 40 ** 2 + 0.15 * np.sin(xx / 7) <= 1, 0, -1)
    pts = outline(lab).points
    counts = [len(fit_chain(pts, True, FitSettings(tolerance=t))[1]) for t in (0.4, 0.8, 2.0)]
    assert counts[0] >= counts[1] >= counts[2] and counts[0] > counts[2]

def test_detail_settings():
    assert detail_settings(50).fit == FitSettings(0.8, 1.0, 50.0, 3.0) and detail_settings(50).min_area == 12
    assert (detail_settings(0).fit.tolerance, detail_settings(100).fit.tolerance) == (2.5, 0.35)
    assert detail_settings(75).fit.tolerance == pytest.approx(0.575)
    with pytest.raises(ValueError, match="Detail must be between 0 and 100"):
        detail_settings(101)
