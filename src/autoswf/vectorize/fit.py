"""Fit quadratic Béziers (SWF's native curve) to a boundary chain: pixel staircases are smoothed away, corners and
brush tips are kept sharp, and each span is the longest curve that stays within the tolerance."""
import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

FitSegment = tuple


@dataclass(frozen=True)
class FitSettings:
    tolerance: float = 0.8       # px: how far the curve may stray from the smoothed boundary
    smoothing: float = 1.0       # px: Gaussian sigma along the boundary
    corner_angle: float = 50.0   # degrees of turning over ±corner_span that make a corner
    corner_span: float = 3.0     # px


@dataclass(frozen=True)
class DetailSettings:
    fit: FitSettings
    min_area: int                # px²: smaller specks merge into their neighbors
    posterize: float             # color distance one posterized step may span


DETAIL_ANCHORS = {0: (2.5, 40, 48.0), 50: (0.8, 12, 24.0), 100: (0.35, 4, 12.0)}


def detail_settings(detail: int) -> DetailSettings:
    """The single "detail" slider (0 = simplest, 100 = most faithful; default 50)."""
    if not 0 <= detail <= 100:
        raise ValueError("Detail must be between 0 and 100")
    lo, hi = (0, 50) if detail <= 50 else (50, 100)
    t = (detail - lo) / (hi - lo)
    tol, area, post = (a + (b - a) * t for a, b in zip(DETAIL_ANCHORS[lo], DETAIL_ANCHORS[hi]))
    return DetailSettings(FitSettings(tolerance=round(tol, 6)), int(round(area)), post)


# ---------------------------------------------------------------- corners

def _arc(p: np.ndarray) -> np.ndarray:
    s = np.zeros(len(p))
    s[1:] = np.cumsum(np.hypot(*np.diff(p, axis=0).T))
    return s


def _turning(p: np.ndarray, span: float, closed: bool) -> np.ndarray:
    n = len(p)
    if closed:
        return _turning(np.vstack([p, p, p]), span, False)[n:2 * n]
    s = _arc(p)
    a = np.clip(np.searchsorted(s, s - span), 0, n - 1)
    b = np.clip(np.searchsorted(s, s + span, side="right") - 1, 0, n - 1)
    v1, v2 = p - p[a], p[b] - p
    n1, n2 = np.hypot(*v1.T), np.hypot(*v2.T)
    ok = (n1 > 1e-9) & (n2 > 1e-9)
    cos = np.ones(n)
    cos[ok] = (v1[ok] * v2[ok]).sum(axis=1) / (n1[ok] * n2[ok])
    angle = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    angle[0] = angle[-1] = 0
    return angle


def _corners(p: np.ndarray, closed: bool, settings: FitSettings) -> list[int]:
    angle = _turning(p, settings.corner_span, closed)
    if not closed:      # next to a pinned end only one side is measured: the end itself is the corner there
        s = _arc(p)
        angle[(s < settings.corner_span) | (s > s[-1] - settings.corner_span)] = 0
    n, found = len(p), []
    for i in np.nonzero(angle >= settings.corner_angle)[0]:
        window = angle[np.arange(i - 3, i + 4) % n] if closed else angle[max(0, i - 3):i + 4]
        if angle[i] >= window.max() and (not found or i - found[-1] > 3):
            found.append(int(i))
    if closed and len(found) > 1 and found[0] + n - found[-1] <= 3:
        found.pop()
    return found


def _line(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = points.mean(axis=0)
    direction = np.linalg.svd(points - center, full_matrices=False)[2][0]
    return center, direction


def _refine(p: np.ndarray, i: int, closed: bool) -> None:
    """Move corner `i` to where the straight runs on its two sides meet, when that is within 2 px: midpoints cut
    pixel corners and brush tips, this puts them back."""
    n = len(p)
    idx_before = [(i - k) % n if closed else i - k for k in range(1, 6)]
    idx_after = [(i + k) % n if closed else i + k for k in range(1, 6)]
    before = [p[j] for j in idx_before if 0 <= j < n]
    after = [p[j] for j in idx_after if 0 <= j < n]
    if len(before) < 2 or len(after) < 2:
        return
    (c1, d1), (c2, d2) = _line(np.array(before)), _line(np.array(after))
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 0.2:
        return
    t = ((c2 - c1)[0] * d2[1] - (c2 - c1)[1] * d2[0]) / cross
    point = c1 + t * d1
    if np.hypot(*(point - p[i])) <= 2.0:
        p[i] = point


# ---------------------------------------------------------------- smoothing

def _smooth_run(seg: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian smoothing of the inner points; odd reflection at both ends keeps the end points fixed."""
    if sigma <= 0 or len(seg) < 3:
        return seg
    r = min(int(3 * sigma) + 1, len(seg) - 1)
    ext = np.vstack([2 * seg[0] - seg[1:r + 1][::-1], seg, 2 * seg[-1] - seg[-r - 1:-1][::-1]])
    out = ndimage.gaussian_filter1d(ext, sigma, axis=0, mode="nearest")[r:-r]
    out[0], out[-1] = seg[0], seg[-1]
    return out


# ---------------------------------------------------------------- fitting

def _quad_points(p0: np.ndarray, c: np.ndarray, p1: np.ndarray, n: int) -> np.ndarray:
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * c + t ** 2 * p1


def _max_distance(data: np.ndarray, curve: np.ndarray) -> float:
    d = np.hypot(data[:, None, 0] - curve[None, :, 0], data[:, None, 1] - curve[None, :, 1])
    return max(float(d.min(axis=1).max()), float(d.min(axis=0).max()))


def _try_fit(seg: np.ndarray, t0: np.ndarray, t1: np.ndarray, tolerance: float):
    p0, p1 = seg[0], seg[-1]
    chord = p1 - p0
    length = math.hypot(*chord)
    if length > 1e-9:
        normal = np.array([-chord[1], chord[0]]) / length
        if np.abs((seg - p0) @ normal).max() <= tolerance:
            return ("L",)
    if len(seg) < 3:
        return ("L",)
    a = np.array([t0, t1]).T
    if abs(np.linalg.det(a)) < 1e-6:
        return None
    s, u = np.linalg.solve(a, chord)
    if not (0 < s < 2 * length + 2 and 0 < u < 2 * length + 2):
        return None
    control = p0 + s * t0
    if _max_distance(seg, _quad_points(p0, control, p1, max(8, 3 * len(seg)))) > tolerance:
        return None
    return ("Q", control)


def _unit(v: np.ndarray) -> np.ndarray:
    n = math.hypot(*v)
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def fit_chain(points: np.ndarray, closed: bool, settings: FitSettings = FitSettings()):
    """(start point, segments) — ("L", x, y) lines and ("Q", cx, cy, x, y) quadratic curves. Open chains start at
    points[0] and end exactly at points[-1]."""
    points = np.asarray(points, np.float64)
    if closed:
        mids = (points[:-1] + points[1:]) / 2
    else:
        mids = np.vstack([points[:1], (points[:-1] + points[1:]) / 2, points[-1:]])
    if len(mids) < 3:
        return (float(points[0][0]), float(points[0][1])), [("L", float(x), float(y)) for x, y in points[1:]]

    corners = _corners(mids, closed, settings)
    for c in corners:
        _refine(mids, c, closed)
    if closed:
        if corners:
            start = corners[0]
        else:
            mids = ndimage.gaussian_filter1d(mids, settings.smoothing, axis=0, mode="wrap") if settings.smoothing > 0 else mids
            start = int(np.argmax(_turning(mids, settings.corner_span, True)))
        q = np.vstack([np.roll(mids, -start, axis=0), mids[start:start + 1]])
        pins = sorted({0, len(q) - 1} | {(c - start) % len(mids) for c in corners})
        sharp = set(pins) if corners else set()
    else:
        q = mids
        pins = sorted({0, len(q) - 1} | set(corners))
        sharp = set(pins)
    if not (closed and not corners):
        for a, b in zip(pins, pins[1:]):
            q[a:b + 1] = _smooth_run(q[a:b + 1], settings.smoothing)
    n = len(q)

    def tangent(i: int, forward: bool, lo: int, hi: int) -> np.ndarray:
        if i in sharp:                                   # one-sided at corners and open ends
            j = min(i + 3, hi) if forward else max(i - 3, lo)
            return _unit(q[j] - q[i]) if forward else _unit(q[i] - q[j])
        if closed and (i == 0 or i == n - 1):            # smooth joint where a closed chain starts
            return _unit(q[1] - q[n - 2])
        return _unit(q[min(i + 3, hi)] - q[max(i - 3, lo)])

    segments = []
    for a, b in zip(pins, pins[1:]):
        i = a
        while i < b:
            def fits(j):
                return _try_fit(q[i:j + 1], tangent(i, True, a, b), tangent(j, False, a, b), settings.tolerance)
            good, good_fit, bad, step = i + 1, ("L",), None, 2
            while True:
                j = min(i + step, b)
                result = fits(j)
                if result is None:
                    bad = j
                    break
                good, good_fit = j, result
                if j == b:
                    break
                step *= 2
            if bad is not None:
                while bad - good > 1:
                    mid = (good + bad) // 2
                    result = fits(mid)
                    if result is None:
                        bad = mid
                    else:
                        good, good_fit = mid, result
            end = q[good]
            if good_fit[0] == "L":
                segments.append(("L", float(end[0]), float(end[1])))
            else:
                c = good_fit[1]
                segments.append(("Q", float(c[0]), float(c[1]), float(end[0]), float(end[1])))
            i = good
    return (float(q[0][0]), float(q[0][1])), segments
