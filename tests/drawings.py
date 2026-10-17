"""Layered test drawings: small canvas helpers and in-memory drawings built from LayerSpecs."""
from dataclasses import dataclass

import numpy as np

from autoswf.aqw.template import Alignment
from autoswf.drawing.layers import Drawing, LayerNode
from autoswf.drawing.writers import LayerSpec

SUPERSAMPLE = 4


def _coverage(w: int, h: int, cx: float, cy: float, r: float) -> np.ndarray:
    """Fraction of each pixel inside the circle (4 x 4 samples per pixel)."""
    offsets = (np.arange(SUPERSAMPLE) + 0.5) / SUPERSAMPLE
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cover = np.zeros((h, w), np.float32)
    for oy in offsets:
        for ox in offsets:
            cover += (xx + ox - cx) ** 2 + (yy + oy - cy) ** 2 <= r * r
    return cover / SUPERSAMPLE ** 2


def _paint(w: int, h: int, color, alpha: np.ndarray) -> np.ndarray:
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = color[:3]
    out[..., 3] = np.round(np.clip(alpha, 0, 1) * color[3]).astype(np.uint8)
    out[out[..., 3] == 0] = 0
    return out


def rect(w: int, h: int, color, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    a = np.zeros((h, w), np.float32)
    a[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 1
    return _paint(w, h, color, a)


def disc(w: int, h: int, color, cx: float, cy: float, r: float, soft: bool = False) -> np.ndarray:
    if soft:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        return _paint(w, h, color, 1 - np.hypot(xx + 0.5 - cx, yy + 0.5 - cy) / r)
    return _paint(w, h, color, _coverage(w, h, cx, cy, r))


def ring(w: int, h: int, color, cx: float, cy: float, r_out: float, r_in: float) -> np.ndarray:
    return _paint(w, h, color, _coverage(w, h, cx, cy, r_out) - _coverage(w, h, cx, cy, r_in))


def _node(spec: LayerSpec) -> LayerNode:
    fields = dict(visible=spec.visible, opacity=spec.opacity, blend=spec.blend)
    if spec.pixels is None:
        return LayerNode(spec.name, "group", children=[_node(c) for c in spec.children], **fields)
    return LayerNode.from_canvas(spec.name, spec.pixels, clipping=spec.clipping, **fields)


def drawing_from_specs(width: int, height: int, specs: list[LayerSpec]) -> Drawing:
    return Drawing(None, width, height, [_node(s) for s in specs])


# ---------------------------------------------------------------- synthetic layered helm

@dataclass
class TestDrawing:
    __test__ = False
    width: int
    height: int
    layers: list[LayerSpec]
    alignment: Alignment


def _qt_layer(size: int, scale: float, origin: tuple[float, float], paint) -> np.ndarray:
    """Draw with QPainter in head units (anti-aliased) and return straight uint8 RGBA."""
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from autoswf.render.effects import qimage_to_array
    QGuiApplication.instance() or QGuiApplication([])
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(*origin)
    p.scale(scale, scale)
    paint(p)
    p.end()
    arr = qimage_to_array(image)
    a = arr[..., 3:4]
    straight = np.where(a > 0, arr[..., :3] / np.maximum(a, 1e-12), 0)
    return np.round(np.dstack([straight, a]) * 255).astype(np.uint8)


def _path(points, closed=True):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    path.moveTo(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(QPointF(x, y))
    if closed:
        path.closeSubpath()
    return path


def _ellipse(cx, cy, rx, ry):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


def _arc(cx, cy, rx, ry, a0, a1, n=80):
    t = np.radians(np.linspace(a0, a1, n))
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1)


def _brush(points, width):
    """A tapered brush stroke along a polyline: a filled polygon whose width swells from 0 at both ends."""
    pts = np.asarray(points, float)
    if len(pts) < 40:                                    # resample straight polylines densely
        t = np.linspace(0, 1, 120)
        seg = np.cumsum(np.r_[0, np.hypot(*np.diff(pts, axis=0).T)])
        pts = np.stack([np.interp(t * seg[-1], seg, pts[:, 0]), np.interp(t * seg[-1], seg, pts[:, 1])], axis=1)
    d = np.gradient(pts, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    normal = np.stack([-d[:, 1], d[:, 0]], axis=1)
    half = width / 2 * np.sin(np.linspace(0, np.pi, len(pts))) ** 0.5
    return _path(np.vstack([pts + normal * half[:, None], (pts - normal * half[:, None])[::-1]]))


def synthetic_helm(size: int = 480) -> TestDrawing:
    """A cel-shaded hat on a face, drawn the way the user layers a drawing: Flats, Shadow (multiply), Occlusion
    (multiply), Light (screen, with one airbrushed highlight), Details, Line (tapered brush strokes)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QRadialGradient
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    dome = _ellipse(-9, -30, 40, 28).intersected(_path([(-60, -80), (40, -80), (40, -16), (-60, -16)]))
    face = _ellipse(-9, 5, 30, 36)
    locks = [(-40, -11), (-28, 8), (-20, -11), (-12, 10), (-2, -11), (8, 6), (22, -11)]

    def fill(p, path, color):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(*color))
        p.drawPath(path)

    def flats(p):
        fill(p, face, (242, 201, 160))
        fill(p, _path(locks), (120, 70, 40))
        fill(p, dome, (60, 90, 170))
        band = _path([(-52, -20), (34, -20), (34, -11), (-52, -11)])
        fill(p, band, (200, 170, 60))
        fill(p, _ellipse(-9, -15.5, 5, 5), (200, 40, 60))
        for cx in (-22, 4):
            fill(p, _ellipse(cx, 10, 6, 5), (255, 255, 255))
            fill(p, _ellipse(cx + 1, 10.5, 3.2, 3.2), (40, 160, 200))

    def shadow(p):
        fill(p, _ellipse(-9, -30, 40, 28).subtracted(_ellipse(-16, -32, 40, 28)), (150, 130, 200))
        fill(p, face.subtracted(_ellipse(-15, 3, 30, 36)), (150, 130, 200))

    def occlusion(p):
        fill(p, _path([(-50, -11), (32, -11), (32, -7), (-50, -7)]), (110, 90, 160))

    def light(p):
        glow = QRadialGradient(QPointF(-20, -36), 12)
        glow.setColorAt(0, QColor(255, 255, 255, 255))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(-32, -48, 24, 24))
        fill(p, _ellipse(-10.5, -17.5, 1.5, 1.5), (255, 255, 255))

    def details(p):
        for cx in (-40, -28, 10, 22):
            fill(p, _ellipse(cx, -15.5, 1.6, 1.6), (255, 240, 150))
        star = [(5 + (4 if k % 2 == 0 else 1.7) * np.sin(k * np.pi / 5), -30 - (4 if k % 2 == 0 else 1.7) * np.cos(k * np.pi / 5))
                for k in range(10)]
        fill(p, _path(star), (255, 240, 120))

    def line(p):
        strokes = [(_arc(-9, 5, 30, 36, 15, 165), 1.4), (_arc(-9, 5, 30, 36, 160, 200), 1.0),
                   (_arc(-9, 5, 30, 36, -20, 20), 1.0), (_arc(-9, -30, 40, 28, 180, 360), 1.6),
                   ([(-52, -20), (-9, -21.5), (34, -20)], 1.0), ([(-52, -11), (34, -11)], 1.2),
                   (_arc(-9, -15.5, 5.4, 5.4, -90, 90), 0.6), (_arc(-9, -15.5, 5.4, 5.4, 90, 270), 0.6),
                   (locks, 1.0), (_arc(-22, 10, 6.5, 5.5, 190, 350), 1.2), (_arc(4, 10, 6.5, 5.5, 190, 350), 1.2)]
        for points, width in strokes:
            fill(p, _brush(points, width), (30, 20, 40))

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    layers = [LayerSpec("Flats", layer(flats)),
              LayerSpec("Shadow", layer(shadow), blend="multiply", clipping=True),
              LayerSpec("Occlusion", layer(occlusion), blend="multiply", clipping=True),
              LayerSpec("Light", layer(light), blend="screen", clipping=True),
              LayerSpec("Details", layer(details)),
              LayerSpec("Line", layer(line))]
    return TestDrawing(size, size, layers, Alignment(scale, origin))
