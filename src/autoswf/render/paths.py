"""SWF edges -> closed fill contours and stroke runs (in twips), and morph-shape interpolation."""
from collections import defaultdict, deque
from dataclasses import dataclass

from autoswf.model.geometry import Matrix
from autoswf.swf.decode import (BitmapStyle, Edge, FillStyle, GradientStyle, LineStyle, MorphShapeDef, ShapeDef,
                                SolidStyle)

Point = tuple[int, int]
Segment = tuple[Point, Point | None, Point]      # start, control (None = straight), end


@dataclass(frozen=True)
class FillPath:
    layer: int
    fill: int
    contours: tuple[tuple[Segment, ...], ...]


@dataclass(frozen=True)
class StrokePath:
    layer: int
    line: int
    runs: tuple[tuple[Segment, ...], ...]


def _join(segments: list[Segment]) -> tuple[tuple[Segment, ...], ...]:
    """Chain segments into contours: each contour follows, from its current end, the first unused segment
    (record order) that starts there, until it closes or nothing continues it."""
    starts: dict[Point, deque] = defaultdict(deque)
    for i, s in enumerate(segments):
        starts[s[0]].append(i)
    used = [False] * len(segments)
    contours = []
    for i in range(len(segments)):
        if used[i]:
            continue
        origin, contour, j = segments[i][0], [], i
        while j is not None:
            used[j] = True
            contour.append(segments[j])
            point = segments[j][2]
            if point == origin:
                break
            queue, j = starts.get(point), None
            while queue:
                k = queue.popleft()
                if not used[k]:
                    j = k
                    break
        contours.append(tuple(contour))
    return tuple(contours)


def fill_paths(shape: ShapeDef) -> list[FillPath]:
    groups: dict[tuple[int, int], list[Segment]] = defaultdict(list)
    for e in shape.edges:
        if e.fill0 == e.fill1:
            continue
        if e.fill1 is not None:
            groups[(e.layer, e.fill1)].append((e.start, e.control, e.end))
        if e.fill0 is not None:
            groups[(e.layer, e.fill0)].append((e.end, e.control, e.start))
    return [FillPath(layer, fill, _join(segs)) for (layer, fill), segs in sorted(groups.items())]


def stroke_paths(shape: ShapeDef) -> list[StrokePath]:
    groups: dict[tuple[int, int], list[list[Segment]]] = defaultdict(list)
    for e in shape.edges:
        if e.line is None:
            continue
        runs = groups[(e.layer, e.line)]
        if runs and runs[-1][-1][2] == e.start:
            runs[-1].append((e.start, e.control, e.end))
        else:
            runs.append([(e.start, e.control, e.end)])
    return [StrokePath(layer, line, tuple(tuple(r) for r in runs)) for (layer, line), runs in sorted(groups.items())]


# ---------------------------------------------------------------- morph shapes

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _point(p, q, t: float) -> Point:
    return (round(_lerp(p[0], q[0], t)), round(_lerp(p[1], q[1], t)))


def _color(a, b, t: float) -> tuple[int, int, int, int]:
    return tuple(round(_lerp(x, y, t)) for x, y in zip(a, b))


def _matrix(a: Matrix, b: Matrix, t: float) -> Matrix:
    return Matrix(*(_lerp(x, y, t) for x, y in zip((a.a, a.b, a.c, a.d, a.tx, a.ty), (b.a, b.b, b.c, b.d, b.tx, b.ty))))


def _fill(a: FillStyle, b: FillStyle, t: float) -> FillStyle:
    if isinstance(a, SolidStyle) and isinstance(b, SolidStyle):
        return SolidStyle(_color(a.color, b.color, t))
    if isinstance(a, GradientStyle) and isinstance(b, GradientStyle):
        stops = tuple((round(_lerp(ra, rb, t)), _color(ca, cb, t)) for (ra, ca), (rb, cb) in zip(a.stops, b.stops))
        return GradientStyle(a.kind, _matrix(a.matrix, b.matrix, t), stops, a.spread, a.interpolation, _lerp(a.focal, b.focal, t))
    if isinstance(a, BitmapStyle) and isinstance(b, BitmapStyle):
        return BitmapStyle(a.bitmap_id, _matrix(a.matrix, b.matrix, t))
    return a if t < 0.5 else b


def _line(a: LineStyle, b: LineStyle, t: float) -> LineStyle:
    return LineStyle(_lerp(a.width, b.width, t), _fill(a.fill, b.fill, t), a.start_cap, a.end_cap, a.join,
                     a.miter_limit, a.no_hscale, a.no_vscale)


def _control(e: Edge):
    if e.control is not None:
        return e.control
    return ((e.start[0] + e.end[0]) / 2, (e.start[1] + e.end[1]) / 2)


def interpolate_morph(morph: MorphShapeDef, t: float) -> ShapeDef:
    s, e = morph.start, morph.end
    edges = []
    for a, b in zip(s.edges, e.edges):
        control = None if a.control is None and b.control is None else _point(_control(a), _control(b), t)
        edges.append(Edge(_point(a.start, b.start, t), control, _point(a.end, b.end, t), a.fill0, a.fill1, a.line, a.layer))
    bounds = tuple(_lerp(x, y, t) for x, y in zip(s.bounds, e.bounds))
    return ShapeDef(morph.id, bounds, tuple(_fill(a, b, t) for a, b in zip(s.fills, e.fills)),
                    tuple(_line(a, b, t) for a, b in zip(s.lines, e.lines)), tuple(edges), s.nonzero)
