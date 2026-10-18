"""Vector shapes in SWF's model: paths of line/quadratic segments with a fill on each side."""
import math
from dataclasses import dataclass
from typing import Literal

from autoswf.model.geometry import Matrix, Point

Color = tuple[int, int, int, int]   # RGBA, 0-255


@dataclass(frozen=True)
class SolidFill:
    color: Color


@dataclass(frozen=True)
class GradientStop:
    ratio: int            # 0-255
    color: Color


@dataclass(frozen=True)
class GradientFill:
    kind: Literal["linear", "radial"]
    stops: tuple[GradientStop, ...]
    matrix: Matrix        # maps Flash's gradient square (-819.2 .. 819.2 px) into shape space


Fill = SolidFill | GradientFill


@dataclass(frozen=True)
class LineTo:
    x: float
    y: float


@dataclass(frozen=True)
class QuadTo:
    cx: float
    cy: float
    x: float
    y: float


Segment = LineTo | QuadTo


@dataclass
class Path:
    start: Point
    segments: list[Segment]
    fill_left: int | None = None     # SWF FillStyle0
    fill_right: int | None = None    # SWF FillStyle1


@dataclass(eq=False)
class Shape:
    fills: list[Fill]
    paths: list[Path]


@dataclass(eq=False)
class MorphShape:
    """A Flash shape tween: start and end have the same fills, paths and segment kinds; a placement's ratio (0..1)
    picks the shape in between."""
    start: Shape
    end: Shape


def _fill_kind(fill: Fill) -> tuple:
    return ("solid",) if isinstance(fill, SolidFill) else (fill.kind, len(fill.stops))


def same_structure(a: Shape, b: Shape) -> bool:
    """Whether two shapes can be the two ends of one morph shape."""
    if len(a.fills) != len(b.fills) or len(a.paths) != len(b.paths):
        return False
    if any(_fill_kind(f) != _fill_kind(g) for f, g in zip(a.fills, b.fills)):
        return False
    for p, q in zip(a.paths, b.paths):
        if (p.fill_left, p.fill_right) != (q.fill_left, q.fill_right) or len(p.segments) != len(q.segments):
            return False
        if any(type(s) is not type(t) for s, t in zip(p.segments, q.segments)):
            return False
    return True


def translated(shape: Shape, dx: float, dy: float) -> Shape:
    """The same shape moved by (dx, dy): points, curve controls and gradient matrices."""
    move = Matrix.translate(dx, dy)
    fills = [GradientFill(f.kind, f.stops, move @ f.matrix) if isinstance(f, GradientFill) else f for f in shape.fills]
    paths = []
    for p in shape.paths:
        segments = [QuadTo(s.cx + dx, s.cy + dy, s.x + dx, s.y + dy) if isinstance(s, QuadTo) else LineTo(s.x + dx, s.y + dy)
                    for s in p.segments]
        paths.append(Path(Point(p.start.x + dx, p.start.y + dy), segments, p.fill_left, p.fill_right))
    return Shape(fills, paths)


def _shoelace(start: Point, segments: list[Segment]) -> float:
    pts = [(start.x, start.y)]
    for s in segments:
        if isinstance(s, QuadTo):
            pts.append((s.cx, s.cy))
        pts.append((s.x, s.y))
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


def closed_contour(fill: int, start: Point, segments: list[Segment]) -> Path:
    """A closed contour filled on its interior side (y down: clockwise on screen -> right side)."""
    if _shoelace(start, segments) > 0:
        return Path(start, list(segments), fill_right=fill)
    return Path(start, list(segments), fill_left=fill)


def ellipse(fill: int, cx: float, cy: float, rx: float, ry: float) -> Path:
    k = 1 / math.cos(math.pi / 8)
    segments = []
    for i in range(8):
        mid, end = (i + 0.5) * math.pi / 4, (i + 1) * math.pi / 4
        segments.append(QuadTo(cx + rx * k * math.cos(mid), cy + ry * k * math.sin(mid),
                               cx + rx * math.cos(end), cy + ry * math.sin(end)))
    return closed_contour(fill, Point(cx + rx, cy), segments)
