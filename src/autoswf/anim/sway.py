"""Sway (spec §11): a chain from a part's root to its tip, a damped angular spring chain driven by a gentle periodic
motion and solved directly as its periodic steady state (the loop a time-stepped simulation settles into, so the last
frame flows into the first), and its motion written as a turn about the root plus one bend mode (morph shapes)."""
import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

from autoswf.anim.timeline import Clip, Key, Pose, Track
from autoswf.model.geometry import Point
from autoswf.model.shape import LineTo, MorphShape, Path, QuadTo, Shape

LINK_LENGTH = 5.0                # head units per chain link
MAX_LINKS = 6
ZETA = 0.35                      # damping ratio of each link's spring
MAX_BENT_SEGMENT = 1.0           # head units: longer segments are split before bending
MIN_BEND = 0.05                  # head units: a bend that moves no point further is left out (the part only turns)
SQRT2 = math.sqrt(2.0)


@dataclass(eq=False)
class Chain:
    nodes: list[Point]           # root, joints, tip (head units)
    length: float                # head units along the part, root to tip
    _u: np.ndarray = field(repr=False, default=None)        # per mask pixel: 0 at the root .. 1 at the tip (NaN off)
    _near: tuple = field(repr=False, default=None)          # nearest reachable pixel of every pixel
    _origin: Point = field(repr=False, default=None)
    _scale: float = field(repr=False, default=1.0)

    def u(self, xs, ys) -> np.ndarray:
        """0 at the root .. 1 at the tip, for head points (the value of the nearest pixel of the part)."""
        h, w = self._u.shape
        cols = np.clip(((np.asarray(xs, float) - self._origin.x) * self._scale).astype(int), 0, w - 1)
        rows = np.clip(((np.asarray(ys, float) - self._origin.y) * self._scale).astype(int), 0, h - 1)
        return self._u[self._near[0][rows, cols], self._near[1][rows, cols]]


def _pixel_graph(pixels: np.ndarray):
    idx = np.full(pixels.shape, -1, np.int64)
    ys, xs = np.nonzero(pixels)
    idx[ys, xs] = np.arange(len(ys))
    h, w = pixels.shape
    rows, cols, costs = [], [], []
    for dy, dx, cost in ((0, 1, 1.0), (1, 0, 1.0), (1, 1, SQRT2), (1, -1, SQRT2)):
        a = idx[0:h - dy, max(0, -dx):w - max(0, dx)]
        b = idx[dy:h, max(0, dx):w - max(0, -dx)]
        ok = (a >= 0) & (b >= 0)
        rows.append(a[ok]); cols.append(b[ok]); costs.append(np.full(int(ok.sum()), cost))
    graph = coo_matrix((np.concatenate(costs), (np.concatenate(rows), np.concatenate(cols))),
                       shape=(len(ys), len(ys))).tocsr()
    return graph, ys, xs


def place_chain(mask, root: Point, tip: Point | None = None, link: float = LINK_LENGTH) -> Chain:
    """The chain from `root` along the part to `tip` (the farthest point along the part when None)."""
    graph, ys, xs = _pixel_graph(mask.pixels)
    if not len(ys):
        raise ValueError("The part has no pixels to place a chain in")
    hx, hy = mask.origin.x + (xs + 0.5) / mask.scale, mask.origin.y + (ys + 0.5) / mask.scale
    start = int(np.argmin((hx - root.x) ** 2 + (hy - root.y) ** 2))
    dist = dijkstra(graph, directed=False, indices=start)
    reach = np.isfinite(dist)
    if tip is None:
        end = int(np.argmax(np.where(reach, dist, -1)))
    else:
        end = int(np.argmin(np.where(reach, (hx - tip.x) ** 2 + (hy - tip.y) ** 2, np.inf)))
    dmax = float(dist[end])
    length = dmax / mask.scale
    n = int(min(max(round(length / link), 1), MAX_LINKS))
    u = np.where(reach, np.minimum(dist / dmax, 1.0) if dmax > 0 else 0.0, np.nan)
    nodes = [root]
    for k in range(1, n):
        band = reach & (np.abs(u - k / n) <= 0.5 / n)
        nodes.append(Point(float(hx[band].mean()), float(hy[band].mean())))
    if n >= 1:
        nodes.append(Point(float(hx[end]), float(hy[end])))
    field_u = np.full(mask.pixels.shape, np.nan)
    field_u[ys, xs] = u
    near = ndimage.distance_transform_edt(~np.isfinite(field_u), return_distances=False, return_indices=True)
    return Chain(nodes, length, field_u, (near[0], near[1]), mask.origin, mask.scale)


def solve_chain(links: int, length: int, stiffness: float, wind: float, phase: float) -> np.ndarray:
    """Link angles (frames x links, radians, unscaled) of the periodic steady state: each link is a damped angular
    spring to the previous one (the first to the head); the head rocks the root once per loop and wind pushes the links
    twice per loop, harder toward the tip. `phase` delays everything by that many frames."""
    omega = 2 * math.pi / length
    k = (omega * (1.5 + 4.5 * stiffness)) ** 2
    c = 2 * ZETA * math.sqrt(k)
    stiff = np.zeros((links, links))
    for j in range(links):
        stiff[j, j] += k
        if j > 0:
            stiff[j, j - 1] -= k
        if j < links - 1:
            stiff[j, j] += k
            stiff[j, j + 1] -= k
    frames = np.arange(length)
    theta = np.zeros((length, links))
    for harmonic, force in ((1, np.eye(links)[0] * k), (2, k * wind * np.arange(1, links + 1) / links)):
        if not np.any(force):
            continue
        w = harmonic * omega
        response = np.linalg.solve((-w * w + 1j * w * c) * np.eye(links) + stiff, force.astype(complex))
        theta += np.real(np.outer(np.exp(1j * w * (frames - phase)), response))
    return theta


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def bend_points(chain: Chain, angles: np.ndarray, xs, ys) -> tuple[np.ndarray, np.ndarray]:
    """The bend without the root's turn: from the tip-most joint down to the first, each joint turns the points beyond
    it by its link's angle relative to the previous link, blended over one link around the joint."""
    xs, ys = np.array(xs, float), np.array(ys, float)
    n = len(chain.nodes) - 1
    u = chain.u(xs, ys)
    for k in range(n - 1, 0, -1):
        delta = angles[k] - angles[k - 1]
        if delta == 0:
            continue
        a = delta * _smoothstep((u - k / n) * n + 0.5)
        cx, cy = chain.nodes[k].x, chain.nodes[k].y
        ca, sa = np.cos(a), np.sin(a)
        dx, dy = xs - cx, ys - cy
        xs, ys = cx + ca * dx - sa * dy, cy + sa * dx + ca * dy
    return xs, ys


@dataclass(eq=False)
class Bend:
    chain: Chain
    angles: np.ndarray           # frames x links, radians
    ratios: list[float]          # the morph ratio of each frame
    error: float                 # head units: farthest the one-mode morph strays from the simulated bend
    coefficients: np.ndarray = field(repr=False, default=None)  # the bend mode's weight per frame (mean 0)

    def _field(self, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Mean displacement over the loop and the bend mode at points (each P x 2)."""
        moved = np.stack([np.stack(bend_points(self.chain, a, xs, ys), axis=-1) for a in self.angles])
        res = moved - np.stack([xs, ys], axis=-1)[None]
        mean = res.mean(axis=0)
        a = self.coefficients
        mode = np.tensordot(a, res - mean[None], axes=(0, 0)) / float(np.dot(a, a))
        return mean, mode

    def morph_points(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        xs, ys = np.asarray(xs, float), np.asarray(ys, float)
        mean, mode = self._field(xs, ys)
        base = np.stack([xs, ys], axis=-1) + mean
        a = self.coefficients
        return base + a.min() * mode, base + a.max() * mode

    def morph(self, shape: Shape, offset: Point) -> MorphShape:
        """The shape as a morph between the bend mode's two extremes; shape coordinates + offset are head units."""
        base = _subdivided(shape)
        points = []
        for p in base.paths:
            points.append((p.start.x, p.start.y))
            for s in p.segments:
                if isinstance(s, QuadTo):
                    points.append((s.cx, s.cy))
                points.append((s.x, s.y))
        pts = np.array(points, float).reshape(-1, 2)
        start, end = self.morph_points(pts[:, 0] + offset.x, pts[:, 1] + offset.y)
        shift = np.array([offset.x, offset.y])
        return MorphShape(_rebuilt(base, start - shift), _rebuilt(base, end - shift))


def _split(p0, seg):
    if isinstance(seg, LineTo):
        mx, my = (p0[0] + seg.x) / 2, (p0[1] + seg.y) / 2
        return [LineTo(mx, my), LineTo(seg.x, seg.y)]
    m0 = ((p0[0] + seg.cx) / 2, (p0[1] + seg.cy) / 2)
    m1 = ((seg.cx + seg.x) / 2, (seg.cy + seg.y) / 2)
    mid = ((m0[0] + m1[0]) / 2, (m0[1] + m1[1]) / 2)
    return [QuadTo(m0[0], m0[1], mid[0], mid[1]), QuadTo(m1[0], m1[1], seg.x, seg.y)]


def _seg_length(p0, seg) -> float:
    if isinstance(seg, LineTo):
        return math.hypot(seg.x - p0[0], seg.y - p0[1])
    return math.hypot(seg.cx - p0[0], seg.cy - p0[1]) + math.hypot(seg.x - seg.cx, seg.y - seg.cy)


def _subdivided(shape: Shape) -> Shape:
    paths = []
    for p in shape.paths:
        out, at = [], (p.start.x, p.start.y)
        todo = list(p.segments)
        while todo:
            seg = todo.pop(0)
            if _seg_length(at, seg) > MAX_BENT_SEGMENT:
                todo[:0] = _split(at, seg)
                continue
            out.append(seg)
            at = (seg.x, seg.y)
        paths.append(Path(p.start, out, p.fill_left, p.fill_right))
    return Shape(shape.fills, paths)


def _rebuilt(base: Shape, points: np.ndarray) -> Shape:
    it = iter(points.tolist())
    paths = []
    for p in base.paths:
        sx, sy = next(it)
        segments = []
        for s in p.segments:
            if isinstance(s, QuadTo):
                cx, cy = next(it)
                x, y = next(it)
                segments.append(QuadTo(cx, cy, x, y))
            else:
                x, y = next(it)
                segments.append(LineTo(x, y))
        paths.append(Path(Point(sx, sy), segments, p.fill_left, p.fill_right))
    return Shape(base.fills, paths)


def _bend(chain: Chain, angles: np.ndarray) -> Bend | None:
    rows, cols = np.nonzero(np.isfinite(chain._u))
    xs = chain._origin.x + (cols + 0.5) / chain._scale
    ys = chain._origin.y + (rows + 0.5) / chain._scale
    moved = np.stack([np.stack(bend_points(chain, a, xs, ys), axis=-1) for a in angles])
    res = moved - np.stack([xs, ys], axis=-1)[None]
    if np.hypot(res[..., 0], res[..., 1]).max() <= MIN_BEND:
        return None
    flat = res.reshape(len(angles), -1)
    mean = flat.mean(axis=0)
    u, s, vt = np.linalg.svd(flat - mean, full_matrices=False)
    a = u[:, 0] * s[0]
    err = (mean + np.outer(a, vt[0]) - flat).reshape(res.shape)
    span = a.max() - a.min()
    ratios = [float((v - a.min()) / span) for v in a]
    return Bend(chain, angles, ratios, float(np.hypot(err[..., 0], err[..., 1]).max()), a)


def sway_ranks(rigs: dict, parts: Iterable[str]) -> dict[str, int]:
    """Neighbouring order of the swaying parts: left to right by pivot."""
    return {name: k for k, name in enumerate(sorted(parts, key=lambda n: (rigs[n].pivot.x, n)))}


def sway_clip(rig, params, rank: int) -> Clip:
    if rig.mask is None:
        raise ValueError("'%s' has no shape to sway" % rig.name)
    chain = place_chain(rig.mask, rig.pivot, rig.tip)
    links = len(chain.nodes) - 1
    theta = solve_chain(links, params.length, params.stiffness, params.wind, rank * params.delay)
    peak = float(np.abs(theta[:, -1]).max())
    if params.amplitude > 0 and peak > 0:
        theta = theta * (math.radians(params.amplitude) / peak)
    else:
        theta = np.zeros_like(theta)
    bend = _bend(chain, theta) if links >= 2 else None
    keys = {f: Key(Pose(rotation=math.degrees(theta[f, 0]), bend=bend.ratios[f] if bend else None))
            for f in range(params.length)}
    tracks = {layer: Track(layer, dict(keys)) for layer in rig.layers}
    return Clip(rig.name, params, params.length, tracks, {layer: bend for layer in rig.layers} if bend else {},
                {"links": links})
