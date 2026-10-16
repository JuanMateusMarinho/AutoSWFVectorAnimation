"""QPainter renderer for the display list: fills, gradients, strokes, color transforms, masks and morphs.

`Renderer.draw` expects the painter's own transform to be identity: it sets a transform per shape from the
matrices it is given (Flash convention, px).
"""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QGradient, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient, QTransform)

from autoswf.model.geometry import ColorTransform, Matrix, Point
from autoswf.render.colors import PlayerColors, apply, concat
from autoswf.render.display import ClipInstance, DisplayObject, ShapeInstance, effective_color
from autoswf.render.paths import fill_paths, interpolate_morph, stroke_paths
from autoswf.swf.decode import BitmapStyle, GradientStyle, MorphShapeDef, ShapeDef, SolidStyle

RGBA = tuple[int, int, int, int]
GRADIENT_HALF = 819.2           # half the side of Flash's gradient square, px
IDENTITY = ColorTransform()
SPREADS = {0: QGradient.Spread.PadSpread, 1: QGradient.Spread.ReflectSpread, 2: QGradient.Spread.RepeatSpread}
CAPS = {0: Qt.PenCapStyle.RoundCap, 1: Qt.PenCapStyle.FlatCap, 2: Qt.PenCapStyle.SquareCap}
JOINS = {0: Qt.PenJoinStyle.RoundJoin, 1: Qt.PenJoinStyle.BevelJoin, 2: Qt.PenJoinStyle.MiterJoin}
ARGB = QImage.Format.Format_ARGB32_Premultiplied


def qt_transform(m: Matrix) -> QTransform:
    return QTransform(m.a, m.b, m.c, m.d, m.tx, m.ty)


def _qpath(contours, closed: bool, nonzero: bool = False) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill if nonzero else Qt.FillRule.OddEvenFill)
    for contour in contours:
        sx, sy = contour[0][0]
        path.moveTo(sx / 20, sy / 20)
        for _, control, (ex, ey) in contour:
            if control is None:
                path.lineTo(ex / 20, ey / 20)
            else:
                path.quadTo(control[0] / 20, control[1] / 20, ex / 20, ey / 20)
        if closed or contour[-1][2] == contour[0][0]:
            path.closeSubpath()
    return path


def _build(shape: ShapeDef):
    fills, strokes = fill_paths(shape), stroke_paths(shape)
    layers = []
    for layer in sorted({p.layer for p in fills} | {p.layer for p in strokes}):
        layers.append(([(p.fill, _qpath(p.contours, True, shape.nonzero)) for p in fills if p.layer == layer],
                       [(p.line, _qpath(p.runs, False)) for p in strokes if p.layer == layer]))
    return shape, layers


def _geometry(obj: ShapeInstance):
    """(ShapeDef, layers of (fills, strokes) QPainterPaths), cached per movie (never by id())."""
    cache = obj.movie.cache
    if isinstance(obj.shape, MorphShapeDef):
        key = ("morph", obj.char_id, obj.ratio)
        if key not in cache:
            cache[key] = _build(interpolate_morph(obj.shape, obj.ratio / 65535))
    else:
        key = ("geometry", obj.char_id)
        if key not in cache:
            cache[key] = _build(obj.shape)
    return cache[key]


def _shape_bounds(obj: ShapeInstance) -> tuple[float, float, float, float]:
    if isinstance(obj.shape, MorphShapeDef):
        t = obj.ratio / 65535
        return tuple(a + (b - a) * t for a, b in zip(obj.shape.start.bounds, obj.shape.end.bounds))
    return obj.shape.bounds


def object_bounds(obj: DisplayObject, matrix: Matrix) -> tuple[float, float, float, float] | None:
    """(xmin, xmax, ymin, ymax) of the transformed shape bounds of the visible descendants (masks excluded)."""
    if not obj.visible:
        return None
    m = matrix @ obj.matrix
    if isinstance(obj, ShapeInstance):
        xmin, xmax, ymin, ymax = _shape_bounds(obj)
        pts = [m.apply(Point(x, y)) for x in (xmin, xmax) for y in (ymin, ymax)]
        return (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts))
    result = None
    for c in getattr(obj, "children", ()):
        if c.clip_depth is not None:
            continue
        b = object_bounds(c, m)
        if b is not None:
            result = b if result is None else (min(result[0], b[0]), max(result[1], b[1]),
                                               min(result[2], b[2]), max(result[3], b[3]))
    return result


def _device_rect(bounds, painter: QPainter, pad: float = 1.0) -> QRect:
    xmin, xmax, ymin, ymax = bounds
    rect = QRectF(xmin - pad, ymin - pad, xmax - xmin + 2 * pad, ymax - ymin + 2 * pad).toAlignedRect()
    device = painter.device()
    return rect.intersected(QRect(0, 0, device.width(), device.height()))


def _new_layer(rect: QRect) -> tuple[QImage, QPainter]:
    image = QImage(rect.size(), ARGB)
    image.fill(0)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return image, p


class Renderer:
    def __init__(self):
        self.notes: set[str] = set()
        self._colors: PlayerColors | None = None
        self._filter_scale = 1.0

    def draw(self, painter: QPainter, obj: DisplayObject, matrix: Matrix, colors: PlayerColors | None, *,
             filter_scale: float = 1.0) -> None:
        self._colors, self._filter_scale = colors, filter_scale
        self._draw(painter, obj, matrix, IDENTITY)
        painter.resetTransform()

    def render_image(self, obj: DisplayObject, width: int, height: int, matrix: Matrix, colors: PlayerColors | None, *,
                     background: RGBA | None = None, filter_scale: float = 1.0) -> QImage:
        image = QImage(width, height, ARGB)
        image.fill(QColor(*background) if background else QColor(0, 0, 0, 0))
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw(p, obj, matrix, colors, filter_scale=filter_scale)
        p.end()
        return image

    # ------------------------------------------------------------ tree

    def _draw(self, painter: QPainter, obj: DisplayObject, parent: Matrix, parent_ct: ColorTransform) -> None:
        if not obj.visible:
            return
        m = parent @ obj.matrix
        own = effective_color(obj, self._colors)
        ct = concat(parent_ct, own) if own is not None else parent_ct
        if isinstance(obj, ShapeInstance):
            self._draw_shape(painter, obj, m, ct)
        elif isinstance(obj, ClipInstance):
            self._draw_children(painter, obj.children, m, ct)

    def _draw_children(self, painter: QPainter, children: list[DisplayObject], m: Matrix, ct: ColorTransform) -> None:
        i = 0
        while i < len(children):
            child = children[i]
            if child.clip_depth is None or child.depth is None:
                self._draw(painter, child, m, ct)
                i += 1
                continue
            j = i + 1
            while j < len(children) and children[j].depth is not None and children[j].depth <= child.clip_depth:
                j += 1
            self._draw_masked(painter, child, children[i + 1:j], m, ct)
            i = j

    def _draw_masked(self, painter: QPainter, mask: DisplayObject, group: list[DisplayObject], m: Matrix,
                     ct: ColorTransform) -> None:
        bounds = object_bounds(mask, m)
        if bounds is None or not group:
            return
        rect = _device_rect(bounds, painter)
        if rect.isEmpty():
            return
        shift = Matrix.translate(-rect.x(), -rect.y())
        content, p = _new_layer(rect)
        self._draw_children(p, group, shift @ m, ct)
        p.resetTransform()
        mask_image, mp = _new_layer(rect)
        self._draw_mask_fills(mp, mask, shift @ m)
        mp.end()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.drawImage(0, 0, mask_image)
        p.end()
        painter.resetTransform()
        painter.drawImage(rect.topLeft(), content)

    def _draw_mask_fills(self, painter: QPainter, obj: DisplayObject, parent: Matrix) -> None:
        m = parent @ obj.matrix
        if isinstance(obj, ShapeInstance):
            _, layers = _geometry(obj)
            painter.setTransform(qt_transform(m))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 255))
            for fills, _ in layers:
                for _, path in fills:
                    painter.drawPath(path)
        elif isinstance(obj, ClipInstance):
            for c in obj.children:
                if c.visible and c.clip_depth is None:
                    self._draw_mask_fills(painter, c, m)

    # ------------------------------------------------------------ shapes

    def _brush(self, style, ct: ColorTransform) -> QBrush | None:
        if isinstance(style, SolidStyle):
            r, g, b, a = apply(ct, style.color)
            return QBrush(QColor(r, g, b, a)) if a else None
        if isinstance(style, GradientStyle):
            if style.kind == "linear":
                gradient = QLinearGradient(-GRADIENT_HALF, 0, GRADIENT_HALF, 0)
            else:
                gradient = QRadialGradient(QPointF(0, 0), GRADIENT_HALF, QPointF(style.focal * GRADIENT_HALF, 0))
            for ratio, color in style.stops:
                gradient.setColorAt(ratio / 255, QColor(*apply(ct, color)))
            gradient.setSpread(SPREADS.get(style.spread, QGradient.Spread.PadSpread))
            if style.interpolation == 1:
                self.notes.add("Linear-RGB gradients are approximated")
            brush = QBrush(gradient)
            brush.setTransform(qt_transform(style.matrix))
            return brush
        if isinstance(style, BitmapStyle):
            self.notes.add("Bitmap fills are not rendered")
        return None

    def _pen(self, style, brush: QBrush, scale: float) -> QPen:
        if style.no_hscale or style.no_vscale:
            self.notes.add("Non-scaling strokes are approximated")
            pen = QPen(brush, max(style.width, 1.0))
            pen.setCosmetic(True)
        else:
            pen = QPen(brush, max(style.width, 1.0 / scale))     # never thinner than one device pixel
        pen.setCapStyle(CAPS.get(style.start_cap, Qt.PenCapStyle.RoundCap))
        pen.setJoinStyle(JOINS.get(style.join, Qt.PenJoinStyle.RoundJoin))
        pen.setMiterLimit(style.miter_limit)
        return pen

    def _draw_shape(self, painter: QPainter, obj: ShapeInstance, m: Matrix, ct: ColorTransform) -> None:
        shape, layers = _geometry(obj)
        scale = math.sqrt(abs(m.a * m.d - m.b * m.c)) or 1e-9
        painter.setTransform(qt_transform(m))
        for fills, strokes in layers:
            painter.setPen(Qt.PenStyle.NoPen)
            for index, path in fills:
                brush = self._brush(shape.fills[index], ct)
                if brush is not None:
                    painter.setBrush(brush)
                    painter.drawPath(path)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for index, path in strokes:
                style = shape.lines[index]
                brush = self._brush(style.fill, ct)
                if brush is not None:
                    painter.setPen(self._pen(style, brush, scale))
                    painter.drawPath(path)


def render_fitted(obj: DisplayObject, scale: float, colors: PlayerColors | None, padding: int = 2, *,
                  renderer: Renderer | None = None) -> QImage:
    """An image just big enough for `obj` at `scale` (plus padding)."""
    bounds = object_bounds(obj, Matrix.scale(scale, scale))
    if bounds is None:
        bounds = (0.0, 0.0, 0.0, 0.0)
    xmin, xmax, ymin, ymax = bounds
    width, height = math.ceil(xmax - xmin) + 2 * padding, math.ceil(ymax - ymin) + 2 * padding
    matrix = Matrix.translate(padding - xmin, padding - ymin) @ Matrix.scale(scale, scale)
    return (renderer or Renderer()).render_image(obj, width, height, matrix, colors, filter_scale=scale)
