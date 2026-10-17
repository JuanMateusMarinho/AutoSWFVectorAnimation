"""Split a hair mass into locks (spec §9.2): cut at the concave notches between the tips, straight across to the nearest
point of the outline that leaves an elongated piece behind (the "minima" and "short-cut" rules of shape parsing)."""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from autoswf.vectorize.trace import boundary_chains

CUT_WIDTH = 3                      # px
MIN_OUTLINE_POINTS = 40
LOCAL_MAX_POINTS = 8               # a notch is the sharpest point within this many outline points
INSIDE_FRACTION = 0.92             # of a cut's samples that must lie inside the mass
NESTED_OVERLAP = 0.2               # a piece overlapping accepted locks more than this is a nested cut
FALLBACK_TRIES = 6                 # outline points tried per notch and direction when no notch-to-notch cut works
FALLBACK_LENGTH = 1.5              # a cut from a notch to a plain outline point must cut off a piece this many cuts long


@dataclass(frozen=True)
class LockSettings:
    concave_angle: float = 40.0    # degrees of turning that make a notch
    turn_span: float = 1.5         # head units of outline before and after a point used to measure its turning
    smoothing: float = 0.5         # head units: Gaussian sigma along the outline
    max_cut: float = 30.0          # head units
    elongation: float = 2.0        # the outline cut off must be at least this many times the cut
    min_area: float = 6.0          # head units²
    max_fraction: float = 0.3      # of the mass's area


@dataclass(frozen=True)
class Cut:
    a: tuple[float, float]         # mask px
    b: tuple[float, float]


def _bridge_diagonals(mask: np.ndarray) -> np.ndarray:
    """Pixels touching only at a corner get a shared neighbor, so every outline is one closed loop."""
    mask = mask.copy()
    for flip in (False, True):
        m = mask[:, ::-1] if flip else mask
        gap = m[:-1, :-1] & m[1:, 1:] & ~m[:-1, 1:] & ~m[1:, :-1]
        ys, xs = np.nonzero(gap)
        m[ys, xs + 1] = True
    return mask


def _outlines(mask: np.ndarray, settings: LockSettings, scale: float):
    labels = np.where(mask, 0, -1).astype(np.int32)
    for chain in boundary_chains(labels):
        if not chain.closed or len(chain.points) - 1 < MIN_OUTLINE_POINTS:
            continue
        p = chain.points[:-1]
        sigma = settings.smoothing * scale
        smooth = np.stack([ndimage.gaussian_filter1d(p[:, k], sigma, mode="wrap") for k in range(2)], axis=1)
        yield smooth, chain.right == 0


def _arc(p: np.ndarray) -> tuple[np.ndarray, float]:
    steps = np.hypot(*np.diff(np.vstack([p, p[:1]]), axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(steps[:-1])])
    return s, float(steps.sum())


def _turning(p: np.ndarray, s: np.ndarray, length: float, span: float) -> np.ndarray:
    """Signed turning (degrees) between the outline `span` px before and after each point."""
    n = len(p)
    ext = np.vstack([p, p, p])
    se = np.concatenate([s - length, s, s + length])
    a = np.clip(np.searchsorted(se, s - span), 0, 3 * n - 1)
    b = np.clip(np.searchsorted(se, s + span), 0, 3 * n - 1)
    v1, v2 = p - ext[a], ext[b] - p
    return np.degrees(np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(axis=1)))


def _inside(mask: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    d = float(np.hypot(*(b - a)))
    t = np.linspace(0, 1, max(2, int(d * 2)))
    q = a + t[:, None] * (b - a)
    xs = np.clip(np.floor(q[:, 0]).astype(int), 0, mask.shape[1] - 1)
    ys = np.clip(np.floor(q[:, 1]).astype(int), 0, mask.shape[0] - 1)
    return float(mask[ys, xs].mean())


def _candidates(mask: np.ndarray, scale: float, settings: LockSettings):
    """Groups of possible cuts, one group per notch and direction along the outline: a cut to the next notch in that
    direction when it is valid (both ends concave: the "minima rule"), else the nearest valid outline points before
    the next notch (fallback cuts, which must cut off a long piece). Each cut is (notch, other end, outline points of
    the arc cut off)."""
    for p, inside_right in _outlines(mask, settings, scale):
        s, length = _arc(p)
        turn = _turning(p, s, length, settings.turn_span * scale)
        concave = -turn if inside_right else turn
        n = len(p)
        notches = [int(i) for i in np.nonzero(concave >= settings.concave_angle)[0]
                   if concave[i] >= concave[np.arange(i - LOCAL_MAX_POINTS, i + LOCAL_MAX_POINTS + 1) % n].max()]
        step = max(1, int(round(scale / 4)))
        samples = np.arange(0, n, step)

        def between(i, j, direction):
            return np.arange(i, i + (j - i) % n + 1) % n if direction == 1 else np.arange(j, j + (i - j) % n + 1) % n

        def valid(i, j, arc_len):
            d = float(np.hypot(*(p[j] - p[i])))
            return (0.4 * scale < d <= settings.max_cut * scale and arc_len >= settings.elongation * d
                    and _inside(mask, p[i], p[j]) >= INSIDE_FRACTION)

        for k, i in enumerate(notches):
            for direction in (1, -1):
                others = [notches[(k + direction * m) % len(notches)] for m in range(1, len(notches))]
                nxt = others[0] if others else None
                limit = ((s[nxt] - s[i]) * direction) % length if nxt is not None else length
                if nxt is not None and valid(i, nxt, limit):
                    yield [(p[i], p[nxt], p[between(i, nxt, direction)], False)]
                    continue
                arc = ((s[samples] - s[i]) * direction) % length
                dist = np.hypot(*(p[samples] - p[i]).T)
                ok = ((dist > 0.4 * scale) & (dist <= settings.max_cut * scale) & (arc >= settings.elongation * dist)
                      & (arc < limit))
                group = []
                for j in samples[ok][np.argsort(dist[ok])]:
                    if _inside(mask, p[i], p[j]) >= INSIDE_FRACTION:
                        group.append((p[i], p[j], p[between(i, j, direction)], True))
                        if len(group) == FALLBACK_TRIES:
                            break
                if group:
                    yield group


def _piece(work: np.ndarray, a, b, arc) -> tuple[np.ndarray, np.ndarray] | None:
    """The part of the mass a straight cut from a to b separates on the side of `arc`, and the cut's pixels."""
    line = Image.new("L", (work.shape[1], work.shape[0]), 0)
    ImageDraw.Draw(line).line([tuple(a), tuple(b)], fill=1, width=CUT_WIDTH)
    cut = np.asarray(line) > 0
    pieces, count = ndimage.label(work & ~cut)
    if count < 2:
        return None
    votes = []
    for x, y in arc[len(arc) // 8: len(arc) - len(arc) // 8 or None]:
        xi, yi = int(np.clip(x, 0, work.shape[1] - 1)), int(np.clip(y, 0, work.shape[0] - 1))
        near = pieces[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2]
        votes += [int(v) for v in near.ravel() if v > 0]
    if not votes:
        return None
    return pieces == np.bincount(votes).argmax(), cut


def _length(piece: np.ndarray, a, b) -> float:
    """How far the piece reaches from the line through the cut (px)."""
    ys, xs = np.nonzero(piece)
    (ax, ay), (bx, by) = a, b
    norm = max(float(np.hypot(bx - ax, by - ay)), 1e-9)
    return float(np.abs((xs + 0.5 - ax) * (by - ay) - (ys + 0.5 - ay) * (bx - ax)).max() / norm)


def split_locks(mask: np.ndarray, scale: float, settings: LockSettings = LockSettings()) -> tuple[np.ndarray, list[Cut]]:
    """Int32 image (0 = the rest of the mass, k = lock k) and the accepted cuts (mask px)."""
    mask = np.asarray(mask, bool)
    out = np.zeros(mask.shape, np.int32)
    if not mask.any():
        return out, []
    work = _bridge_diagonals(mask)
    total = work.sum() / scale ** 2
    found = []
    for group in _candidates(work, scale, settings):
        best = None
        for a, b, arc, fallback in group:
            result = _piece(work, a, b, arc)
            if result is None:
                continue
            piece, cut = result
            area = piece.sum() / scale ** 2
            if not settings.min_area <= area <= settings.max_fraction * total:
                continue
            if fallback and _length(piece, a, b) < FALLBACK_LENGTH * float(np.hypot(*(b - a))):
                continue
            if best is None or area < best[0]:
                best = (area, piece, Cut((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))), cut)
        if best is not None:
            found.append(best)
    found.sort(key=lambda f: -f[0])
    taken = np.zeros(mask.shape, bool)
    cut_pixels = np.zeros(mask.shape, bool)
    cuts = []
    for area, piece, cut_line, line_pixels in found:
        if (piece & taken).sum() > NESTED_OVERLAP * piece.sum():
            continue
        piece = piece & ~taken
        cuts.append(cut_line)
        out[piece] = len(cuts)
        taken |= piece
        cut_pixels |= line_pixels
    loose = mask & cut_pixels & (out == 0)                 # cut pixels go back to the nearest side
    if loose.any():
        known = mask & ~loose
        _, (iy, ix) = ndimage.distance_transform_edt(~known, return_indices=True)
        out[loose] = out[iy[loose], ix[loose]]
    out[~mask] = 0
    return out, cuts
