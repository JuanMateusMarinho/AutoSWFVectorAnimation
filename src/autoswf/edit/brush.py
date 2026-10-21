"""Brush and eraser strokes (Plan 7): a stroke is the union of a disc at each pen sample and the hull between
consecutive discs; pen pressure changes only the width (AQW art is flat color, so never the opacity)."""
import math
from dataclasses import dataclass

from autoswf.edit.regions import FLATTEN_PX, TWIPS, Area, union

MIN_PRESSURE_WIDTH = 0.15          # width at zero pressure, as a share of the brush size
MIN_SAMPLE_GAP = 0.5               # px: closer samples add nothing


@dataclass(frozen=True)
class Sample:
    x: float                       # layer px
    y: float
    pressure: float = 1.0


def stroke_width(size: float, pressure: float, use_pressure: bool) -> float:
    if not use_pressure:
        return size
    p = min(1.0, max(0.0, pressure))
    return size * (MIN_PRESSURE_WIDTH + (1 - MIN_PRESSURE_WIDTH) * p)


def _disc(x: float, y: float, r: float) -> list[tuple[float, float]]:
    n = 24
    if r > FLATTEN_PX:
        n = max(n, math.ceil(math.pi / math.acos(1 - FLATTEN_PX / r)))
    return [(x + r * math.cos(2 * math.pi * k / n), y + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _twips(poly) -> list[tuple[int, int]]:
    return [(round(x * TWIPS), round(y * TWIPS)) for x, y in poly]


def stroke_area(samples: list[Sample], size: float, *, use_pressure: bool = True) -> Area:
    kept: list[Sample] = []
    for s in samples:
        if not kept or math.hypot(s.x - kept[-1].x, s.y - kept[-1].y) >= MIN_SAMPLE_GAP:
            kept.append(s)
    if not kept:
        return []
    discs = [_disc(s.x, s.y, stroke_width(size, s.pressure, use_pressure) / 2) for s in kept]
    polys = [_twips(discs[0])]
    for a, b in zip(discs, discs[1:]):
        polys.append(_twips(_hull(a + b)))
    return union(polys, [])
