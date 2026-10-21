"""Vector areas for the editor (Plan 7): a Shape's fills as polygon areas in integer twips, set operations on them
(pyclipper), and shapes rebuilt from edited areas that keep, exactly, every original segment an edit did not touch.

An Area is a list of closed paths in twips. Outer paths have positive orientation and holes negative (pyclipper's
convention; with y down that is clockwise on screen, so the fill lies on each directed edge's right, as SWF's
FillStyle1)."""
import math
from collections import defaultdict

import numpy as np
import pyclipper

from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import Fill, LineTo, Path, QuadTo, Shape
from autoswf.vectorize.fit import _try_fit, _unit

TWIPS = 20
FLATTEN_PX = 0.25
SNAP_TWIPS = 2                     # vertices this close are one vertex after an edit
RESAMPLE_PX = 0.5                  # spacing of the points a re-fitted run is fitted through
CORNER_DEGREES = 20.0              # a re-fitted run is broken where it turns more than this (exact corners)
FIT_PX = 0.125                     # how far a re-fitted curve may stray from the edited boundary

Area = list[list[tuple[int, int]]]
TPoint = tuple[int, int]


# ---------------------------------------------------------------- flattening

def _quad_steps(p0, c, p1) -> int:
    d = math.hypot(p0[0] - 2 * c[0] + p1[0], p0[1] - 2 * c[1] + p1[1])
    return max(1, math.ceil(math.sqrt(d / (4 * FLATTEN_PX)))) if d > 0 else 1


def _samples(start: tuple[float, float], seg) -> list[tuple[float, float]]:
    """Points along a segment after its start, ending exactly at its end (px)."""
    if isinstance(seg, LineTo):
        return [(seg.x, seg.y)]
    c, e = (seg.cx, seg.cy), (seg.x, seg.y)
    n = _quad_steps(start, c, e)
    out = []
    for k in range(1, n):
        t = k / n
        u = 1 - t
        out.append((u * u * start[0] + 2 * u * t * c[0] + t * t * e[0],
                    u * u * start[1] + 2 * u * t * c[1] + t * t * e[1]))
    out.append(e)
    return out


def _tw(p) -> TPoint:
    return (round(p[0] * TWIPS), round(p[1] * TWIPS))


def _path_twips(path: Path) -> list[TPoint]:
    pts = [_tw((path.start.x, path.start.y))]
    prev = (path.start.x, path.start.y)
    for seg in path.segments:
        for q in _samples(prev, seg):
            t = _tw(q)
            if t != pts[-1]:
                pts.append(t)
        prev = (seg.x, seg.y)
    return pts


# ---------------------------------------------------------------- set operations

def _valid(paths) -> list[list[TPoint]]:
    return [[(int(x), int(y)) for x, y in p] for p in paths if len(p) >= 3]


def _execute(subject, clip, op) -> Area:
    pc = pyclipper.Pyclipper()
    pc.PreserveCollinear = True
    added = False
    for paths, kind in ((subject, pyclipper.PT_SUBJECT), (clip, pyclipper.PT_CLIP)):
        for p in _valid(paths):
            try:
                pc.AddPath(p, kind, True)
                added = added or kind == pyclipper.PT_SUBJECT
            except pyclipper.ClipperException:      # a path with no area
                pass
    if not added:
        return []
    return [[(x, y) for x, y in p] for p in pc.Execute(op, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)]


def union(a: Area, b: Area) -> Area:
    return _execute(list(a) + list(b), [], pyclipper.CT_UNION)


def difference(a: Area, b: Area) -> Area:
    return _execute(a, b, pyclipper.CT_DIFFERENCE)


def intersection(a: Area, b: Area) -> Area:
    if not a or not b:
        return []
    return _execute(a, b, pyclipper.CT_INTERSECTION)


def offset(a: Area, px: float) -> Area:
    """The area grown (px > 0) or shrunk (px < 0) by px, with round joins."""
    paths = _valid(a)
    if not paths:
        return []
    if px == 0:
        return union(paths, [])
    po = pyclipper.PyclipperOffset()
    po.ArcTolerance = FLATTEN_PX * TWIPS
    po.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return union([[(x, y) for x, y in p] for p in po.Execute(px * TWIPS)], [])


def components(a: Area) -> list[Area]:
    """Each outer path with its holes (an island inside a hole is a component of its own)."""
    pc = pyclipper.Pyclipper()
    paths = _valid(a)
    if not paths:
        return []
    pc.AddPaths(paths, pyclipper.PT_SUBJECT, True)
    tree = pc.Execute2(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    out = []

    def visit(node):
        for child in node.Childs:
            if child.IsHole:
                continue
            comp = [[(x, y) for x, y in child.Contour]]
            for hole in child.Childs:
                comp.append([(x, y) for x, y in hole.Contour])
                visit(hole)
            out.append(comp)

    visit(tree)
    return out


def contains(a: Area, x_px: float, y_px: float) -> bool:
    pt = _tw((x_px, y_px))
    winding = 0
    for p in a:
        if len(p) >= 3 and pyclipper.PointInPolygon(pt, p) != 0:
            winding += 1 if pyclipper.Orientation(p) else -1
    return winding > 0


def area_px(a: Area) -> float:
    return sum(pyclipper.Area(p) for p in a if len(p) >= 3) / (TWIPS * TWIPS)


def transform_area(a: Area, m: Matrix) -> Area:
    out = []
    for p in a:
        q = [m.apply(Point(x / TWIPS, y / TWIPS)) for x, y in p]
        out.append([_tw((v.x, v.y)) for v in q])
    if m.a * m.d - m.b * m.c < 0:
        out = [p[::-1] for p in out]
    return union(out, [])


def stroke_width_px(a: Area) -> float:
    """The average width of a line-like area: twice its area over its outline's length."""
    perimeter = sum(math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]) for p in a for i in range(len(p))) / TWIPS
    return 2 * area_px(a) / perimeter if perimeter > 0 else 0.0


def bounds_px(a: Area) -> tuple[float, float, float, float] | None:
    pts = [pt for p in a for pt in p]
    if not pts:
        return None
    xs, ys = [x for x, _ in pts], [y for _, y in pts]
    return (min(xs) / TWIPS, max(xs) / TWIPS, min(ys) / TWIPS, max(ys) / TWIPS)


# ---------------------------------------------------------------- shape -> areas

def _near_keys(p: TPoint):
    yield p
    ring = sorted(((dx, dy) for dx in range(-SNAP_TWIPS, SNAP_TWIPS + 1) for dy in range(-SNAP_TWIPS, SNAP_TWIPS + 1)
                   if (dx, dy) != (0, 0)), key=lambda d: d[0] * d[0] + d[1] * d[1])
    for dx, dy in ring:
        yield (p[0] + dx, p[1] + dy)


def _loops(polylines: list[list[TPoint]]) -> list[list[TPoint]]:
    """Directed polylines (fill on their right) chained end to start into closed loops."""
    starts: dict[TPoint, list[int]] = defaultdict(list)
    for i, pl in enumerate(polylines):
        starts[pl[0]].append(i)
    used = [False] * len(polylines)
    loops = []
    for i in range(len(polylines)):
        if used[i]:
            continue
        origin, loop, j = polylines[i][0], [], i
        while j is not None:
            used[j] = True
            loop.extend(polylines[j] if not loop else polylines[j][1:])
            end = loop[-1]
            if abs(end[0] - origin[0]) <= SNAP_TWIPS and abs(end[1] - origin[1]) <= SNAP_TWIPS and len(loop) > 2:
                break
            j = None
            for key in _near_keys(end):
                j = next((k for k in starts.get(key, ()) if not used[k]), None)
                if j is not None:
                    break
        loops.append(loop)
    return loops


def fill_areas(shape: Shape) -> dict[int, Area]:
    per_fill: dict[int, list[list[TPoint]]] = defaultdict(list)
    for path in shape.paths:
        if path.fill_left == path.fill_right:
            continue
        pts = _path_twips(path)
        if len(pts) < 2:
            continue
        if path.fill_right is not None:
            per_fill[path.fill_right].append(pts)
        if path.fill_left is not None:
            per_fill[path.fill_left].append(pts[::-1])
    out = {}
    for fill, polylines in per_fill.items():
        area = union(_loops(polylines), [])
        if area:
            out[fill] = area
    return out


# ---------------------------------------------------------------- areas -> shape

class _Original:
    """The original shape's segments flattened to twips, to find the ones an edit left whole."""

    def __init__(self, shape: Shape):
        self.segments = {}                 # uid -> (start px, segment, twips samples from start to end)
        self.at: dict[TPoint, list[tuple[tuple[int, int], int]]] = defaultdict(list)
        for i, path in enumerate(shape.paths):
            prev = (path.start.x, path.start.y)
            for j, seg in enumerate(path.segments):
                tw = [_tw(prev)]
                for q in _samples(prev, seg):
                    t = _tw(q)
                    if t != tw[-1]:
                        tw.append(t)
                if len(tw) >= 2:
                    self.segments[(i, j)] = (prev, seg, tw)
                    for k, t in enumerate(tw):
                        self.at[t].append(((i, j), k))
                prev = (seg.x, seg.y)

    def points(self):
        return self.at.keys()

    def matches(self, pts: list[TPoint], i: int) -> list[tuple[int, tuple[int, int], bool]]:
        """Whole original segments that start at pts[i]: (end index, uid, forward)."""
        out = []
        for uid, k in self.at.get(pts[i], ()):
            tw = self.segments[uid][2]
            n = len(tw) - 1
            if k == 0 and i + n < len(pts) and all(pts[i + m] == tw[m] for m in range(n + 1)):
                out.append((i + n, uid, True))
            elif k == n and i + n < len(pts) and all(pts[i + m] == tw[n - m] for m in range(n + 1)):
                out.append((i + n, uid, False))
        return out

    def scan(self, pts: list[TPoint]) -> list[tuple[int, int, tuple[int, int], bool]]:
        found, i = [], 0
        while i < len(pts) - 1:
            here = self.matches(pts, i)
            if here:
                end, uid, forward = max(here, key=lambda m: (m[0], m[2]))
                found.append((i, end, uid, forward))
                i = end
            else:
                i += 1
        return found

    def ends(self, uid, forward: bool) -> tuple[tuple[float, float], tuple[float, float]]:
        start, seg, _ = self.segments[uid]
        return (start, (seg.x, seg.y)) if forward else ((seg.x, seg.y), start)

    def segment(self, uid, forward: bool):
        start, seg, _ = self.segments[uid]
        if forward:
            return seg
        if isinstance(seg, QuadTo):
            return QuadTo(seg.cx, seg.cy, start[0], start[1])
        return LineTo(start[0], start[1])


class _Snapper:
    """Merges vertices closer than SNAP_TWIPS, preferring the original shape's points."""

    def __init__(self, preferred):
        self.cells: dict[TPoint, list[TPoint]] = defaultdict(list)
        for p in preferred:
            self._add(p)

    def _cell(self, p: TPoint) -> TPoint:
        return (p[0] // 4, p[1] // 4)

    def _add(self, p: TPoint) -> None:
        self.cells[self._cell(p)].append(p)

    def __call__(self, p: TPoint) -> TPoint:
        cx, cy = self._cell(p)
        best, dist = None, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in self.cells.get((cx + dx, cy + dy), ()):
                    d = max(abs(q[0] - p[0]), abs(q[1] - p[1]))
                    if d <= SNAP_TWIPS and (dist is None or d < dist):
                        best, dist = q, d
        if best is None:
            self._add(p)
            return p
        return best


class _Grid:
    def __init__(self, points, cell: int = 64):
        self.cell = cell
        self.cells: dict[TPoint, list[TPoint]] = defaultdict(list)
        for p in points:
            self.cells[(p[0] // cell, p[1] // cell)].append(p)

    def between(self, a: TPoint, b: TPoint) -> list[TPoint]:
        """Vertices lying on the open segment a-b (within a twip), in order from a."""
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        if length2 == 0:
            return []
        out = []
        for gx in range((x0 - 1) // self.cell, (x1 + 1) // self.cell + 1):
            for gy in range((y0 - 1) // self.cell, (y1 + 1) // self.cell + 1):
                for p in self.cells.get((gx, gy), ()):
                    if p == a or p == b or not (x0 - 1 <= p[0] <= x1 + 1 and y0 - 1 <= p[1] <= y1 + 1):
                        continue
                    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
                    if not 0 < t < 1:
                        continue
                    cross = abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / math.sqrt(length2)
                    if cross <= 1:
                        out.append((t, p))
        return [p for _, p in sorted(out)]


def _edges(areas: dict[int, Area], original: _Original) -> list[tuple[TPoint, TPoint, int | None, int | None]]:
    """Every boundary edge once, (a, b, fill on the left, fill on the right) going a -> b."""
    snap = _Snapper(original.points())
    loops: dict[int, list[list[TPoint]]] = {}
    for fill, area in areas.items():
        for path in area:
            pts = []
            for p in path:
                q = snap(p)
                if not pts or q != pts[-1]:
                    pts.append(q)
            while len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                loops.setdefault(fill, []).append(pts)
    grid = _Grid({p for ls in loops.values() for pts in ls for p in pts})
    directed: dict[tuple[TPoint, TPoint], list[int]] = defaultdict(list)
    for fill, ls in loops.items():
        for pts in ls:
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                chain = [a] + grid.between(a, b) + [b]
                for p, q in zip(chain, chain[1:]):
                    directed[(p, q)].append(fill)
    edges, seen = [], set()
    for (a, b), rights in directed.items():
        if (a, b) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        lefts = directed.get((b, a), [])
        for k in range(max(len(rights), len(lefts))):
            right = rights[k] if k < len(rights) else None
            left = lefts[k] if k < len(lefts) else None
            if left != right:
                edges.append((a, b, left, right))
    return edges


def _chains(edges) -> list[tuple[list[TPoint], int | None, int | None]]:
    """Edges joined into runs through vertices where exactly two edges with the same fills meet."""
    incident: dict[TPoint, list[int]] = defaultdict(list)
    for i, (a, b, _, _) in enumerate(edges):
        incident[a].append(i)
        incident[b].append(i)
    used = [False] * len(edges)

    def from_vertex(i: int, v: TPoint):
        a, b, left, right = edges[i]
        return (a, b, left, right) if a == v else (b, a, right, left)

    def next_edge(v: TPoint, current: int, pair, outward: bool):
        if len(incident[v]) != 2:
            return None
        j = incident[v][0] if incident[v][1] == current else incident[v][1]
        if j == current or used[j]:
            return None
        _, end, left, right = from_vertex(j, v)
        if (left, right) == pair if outward else (right, left) == pair:
            return j, end
        return None

    out = []
    for i in range(len(edges)):
        if used[i]:
            continue
        used[i] = True
        a, b, left, right = edges[i]
        pts, current = [a, b], i
        while pts[-1] != pts[0]:
            step = next_edge(pts[-1], current, (left, right), True)
            if step is None:
                break
            current, end = step
            used[current] = True
            pts.append(end)
        if pts[-1] != pts[0]:
            current = i
            while True:
                step = next_edge(pts[0], current, (left, right), False)
                if step is None:
                    break
                current, end = step
                used[current] = True
                pts.insert(0, end)
        out.append((pts, left, right))
    return out


def _densify(points: list[tuple[float, float]]) -> np.ndarray:
    out = [points[0]]
    for p, q in zip(points, points[1:]):
        n = max(1, math.ceil(math.hypot(q[0] - p[0], q[1] - p[1]) / RESAMPLE_PX))
        for k in range(1, n + 1):
            out.append((p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n))
    return np.array(out, np.float64)


def _turn(a, b, c) -> float:
    """Degrees the polyline turns at b."""
    ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - b[0], c[1] - b[1]
    nu, nv = math.hypot(ux, uy), math.hypot(vx, vy)
    if nu == 0 or nv == 0:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / (nu * nv)))))


def _straight(points) -> bool:
    (x0, y0), (x1, y1) = points[0], points[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return len(points) <= 2
    return all(abs((x - x0) * (y1 - y0) - (y - y0) * (x1 - x0)) / length <= FLATTEN_PX for x, y in points[1:-1])


def _fit_points(q: np.ndarray) -> list:
    """Lines and quadratic curves through dense points (px), from q[0] exactly to q[-1], within FLATTEN_PX."""
    n = len(q)

    def tangent(k: int) -> np.ndarray:
        if k == 0:
            return _unit(q[min(3, n - 1)] - q[0])
        if k == n - 1:
            return _unit(q[n - 1] - q[max(n - 4, 0)])
        return _unit(q[min(k + 3, n - 1)] - q[max(k - 3, 0)])

    segs, i = [], 0
    while i < n - 1:
        def fits(j: int):
            return _try_fit(q[i:j + 1], tangent(i), tangent(j), FIT_PX)
        good, good_fit, bad, step = i + 1, ("L",), None, 2
        while True:
            j = min(i + step, n - 1)
            result = fits(j)
            if result is None:
                bad = j
                break
            good, good_fit = j, result
            if j == n - 1:
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
        end = (float(q[good][0]), float(q[good][1]))
        if good_fit[0] == "L":
            segs.append(LineTo(*end))
        else:
            segs.append(QuadTo(float(good_fit[1][0]), float(good_fit[1][1]), *end))
        i = good
    return segs


def _fit_open(points: list[tuple[float, float]]) -> list:
    """Segments from points[0] exactly to points[-1], broken at corners first."""
    cuts = [0] + [i for i in range(1, len(points) - 1)
                  if _turn(points[i - 1], points[i], points[i + 1]) > CORNER_DEGREES]
    cuts.append(len(points) - 1)
    segs = []
    for a, b in zip(cuts, cuts[1:]):
        piece = points[a:b + 1]
        if _straight(piece):
            segs.append(LineTo(*piece[-1]))
            continue
        fitted = _fit_points(_densify(piece))
        last = fitted[-1]
        fitted[-1] = LineTo(*piece[-1]) if isinstance(last, LineTo) else QuadTo(last.cx, last.cy, *piece[-1])
        segs.extend(fitted)
    return segs


def _fitted(points: list[tuple[float, float]], closed: bool) -> tuple[tuple[float, float], list]:
    """Segments through a run of points (px); open runs start at points[0] and end exactly at points[-1]."""
    pts = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    if not closed:
        return pts[0], _fit_open(pts)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    corners = [i for i in range(n) if _turn(pts[i - 1], pts[i], pts[(i + 1) % n]) > CORNER_DEGREES]
    ring = pts[corners[0]:] + pts[:corners[0]] if corners else pts
    return ring[0], _fit_open(ring + [ring[0]])


def _emit(pts: list[TPoint], left, right, original: _Original) -> Path:
    closed = len(pts) > 2 and pts[0] == pts[-1]
    if closed:
        # start the ring where its earliest original segment starts, so an untouched path comes back as it was
        ring = pts[:-1]
        twice = ring + ring
        starts = [(uid, i) for i in range(len(ring)) for _, uid, _ in original.matches(twice, i)]
        if starts:
            first = min(starts)[1]
            pts = ring[first:] + ring[:first] + [ring[first]]
    found = original.scan(pts)
    if sum(1 for f in found if not f[3]) > sum(1 for f in found if f[3]):
        pts, left, right = pts[::-1], right, left
        found = original.scan(pts)
    if not found:
        start, segs = _fitted([(x / TWIPS, y / TWIPS) for x, y in (pts[:-1] if closed else pts)], closed)
        return Path(Point(*start), segs, left, right)

    pieces = []
    cursor = 0
    for s, e, uid, forward in found:
        if s > cursor:
            pieces.append(("fit", cursor, s))
        pieces.append(("seg", uid, forward))
        cursor = e
    if cursor < len(pts) - 1:
        pieces.append(("fit", cursor, len(pts) - 1))

    def start_of(piece):
        return original.ends(piece[1], piece[2])[0] if piece[0] == "seg" else None

    def end_of(piece):
        return original.ends(piece[1], piece[2])[1] if piece[0] == "seg" else None

    segments, path_start = [], None
    for n, piece in enumerate(pieces):
        if piece[0] == "seg":
            if path_start is None:
                path_start = start_of(piece)
            segments.append(original.segment(piece[1], piece[2]))
            continue
        run = [(x / TWIPS, y / TWIPS) for x, y in pts[piece[1]:piece[2] + 1]]
        before = pieces[n - 1] if n > 0 else (pieces[-1] if closed else None)
        after = pieces[n + 1] if n + 1 < len(pieces) else (pieces[0] if closed else None)
        if before is not None and before[0] == "seg":
            run[0] = end_of(before)
        if after is not None and after[0] == "seg":
            run[-1] = start_of(after)
        if path_start is None:
            path_start = run[0]
        segments.extend(_fitted(run, False)[1])
    return Path(Point(*path_start), segments, left, right)


def rebuild_shape(original: Shape, areas: dict[int, Area], fills: list[Fill] | None = None) -> Shape:
    """A shape whose fill regions are `areas`; every original segment still whole on the new boundaries comes back
    exactly as it was (same direction where possible), only the rest is fitted again."""
    index = _Original(original)
    paths = [_emit(pts, left, right, index) for pts, left, right in _chains(_edges(areas, index))]
    return Shape(list(original.fills if fills is None else fills), paths)
