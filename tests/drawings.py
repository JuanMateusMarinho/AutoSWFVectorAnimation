"""Layered test drawings: small canvas helpers and in-memory drawings built from LayerSpecs."""
from dataclasses import dataclass, field

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


# ---------------------------------------------------------------- helms with parts and their ground truth

@dataclass
class PartsDrawing(TestDrawing):
    __test__ = False
    truth: dict = field(default_factory=dict)          # part name -> canvas bool mask of its flats (topmost part)
    pieces: dict = field(default_factory=dict)         # "Eye L iris" ... -> canvas bool mask
    locations: dict = field(default_factory=dict)      # part name -> expected location of its main color
    roots: dict = field(default_factory=dict)          # lock name -> (x, y) head units
    tips: dict = field(default_factory=dict)


def agreement(found: np.ndarray, truth: np.ndarray, slack: int = 2,
              ignore: np.ndarray | None = None) -> tuple[float, float]:
    """(recall on `truth` eroded by `slack` px, precision of `found` against `truth` dilated by `slack` px), leaving
    out `ignore` pixels (under the line art, where a boundary between flats is anyone's guess)."""
    from scipy import ndimage
    keep = ~ignore if ignore is not None else np.ones(truth.shape, bool)
    inner = (ndimage.binary_erosion(truth, iterations=slack) if slack else truth) & keep
    outer = ndimage.binary_dilation(truth, iterations=slack) if slack else truth
    recall = float((found & inner).sum() / max(inner.sum(), 1))
    precision = float((found & outer & keep).sum() / max((found & keep).sum(), 1))
    return recall, precision


def line_mask(passes) -> np.ndarray:
    """Canvas pixels covered by the line art (alpha >= 0.5)."""
    out = np.zeros((passes.height, passes.width), bool)
    for part in passes.parts:
        x0, y0 = part.origin
        h, w = part.lines.shape[:2]
        out[y0:y0 + h, x0:x0 + w] |= part.lines[..., 3] >= 0.5
    return out


SKIN, HAIR, IRIS, PUPIL, WHITE = (242, 201, 160), (120, 70, 40), (40, 160, 200), (20, 20, 30), (255, 255, 255)
MOUTH, DOME, BAND, GEM, HORN, INK = (150, 40, 50), (60, 90, 170), (200, 170, 60), (200, 40, 60), (235, 230, 200), (30, 20, 40)
EYES = {"L": -22.0, "R": 4.0}
TEETH = [(-36.0 + 10 * k, -26.0 + 10 * k) for k in range(5)]
SIDE_LOCK = [(14, -8), (26, -8), (28, 10), (25, 28), (19, 8)]
HORN_POINTS = [(15, -47), (21, -44), (30, -66)]


def _mask(size: int, scale: float, origin, path) -> np.ndarray:
    """Pixels whose center is inside `path` (head units), without anti-aliasing."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    QGuiApplication.instance() or QGuiApplication([])
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(0)
    p = QPainter(image)
    p.translate(*origin)
    p.scale(scale, scale)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(Qt.GlobalColor.white)
    p.drawPath(path)
    p.end()
    return np.frombuffer(image.constBits(), np.uint8).reshape(size, size, 4)[..., 3] > 127


def _stroke(points, width, closed=False):
    """A constant-width ink line along a polyline (round joins), as a filled path."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainterPathStroker
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return stroker.createStroke(_path(points, closed))


def _qt_fill(p, path, color):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(*color))
    p.drawPath(path)


def _hat_shapes():
    dome = _ellipse(-9, -34, 40, 26).intersected(_path([(-60, -80), (40, -80), (40, -21), (-60, -21)]))
    band = _path([(-52, -21), (34, -21), (34, -14), (-52, -14)])
    return dome, band, _ellipse(-9, -17.5, 2.5, 2.5)


def _hat_tones(dome, horn=None):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QRadialGradient

    def shadow(p):
        crescent = dome.subtracted(_ellipse(-16, -34, 40, 26))
        if horn is not None:
            crescent = crescent.subtracted(horn)
        _qt_fill(p, crescent, (150, 130, 200))

    def light(p):
        glow = QRadialGradient(QPointF(-20, -40), 10)
        glow.setColorAt(0, QColor(255, 255, 255, 255))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(-30, -50, 20, 20))

    def details(p):
        for cx in (-42, -30, 12, 24):
            _qt_fill(p, _ellipse(cx, -17.5, 1.4, 1.4), (255, 240, 150))
        star = [(5 + (4 if k % 2 == 0 else 1.7) * np.sin(k * np.pi / 5),
                 -38 - (4 if k % 2 == 0 else 1.7) * np.cos(k * np.pi / 5)) for k in range(10)]
        _qt_fill(p, _path(star), (255, 240, 120))
    return shadow, light, details


def _hat_lines():
    # the dome's outline leaves a gap where the horn stands on it (an outline drawn over the horn would cut it)
    return [_brush(_arc(-9, -34, 40, 26, 180, 300), 1.6), _brush(_arc(-9, -34, 40, 26, 335, 360), 1.6),
            _stroke([(-52, -21), (34, -21)], 1.0), _stroke([(-52, -14), (34, -14)], 1.0),
            _stroke(_arc(-9, -17.5, 2.8, 2.8, 0, 360), 0.6, closed=True)]


def _truth(size, scale, origin, ordered) -> dict:
    """Topmost part per pixel from (name, path) pairs in drawing order."""
    owner = np.full((size, size), -1, np.int32)
    names = []
    for name, path in ordered:
        if name not in names:
            names.append(name)
        owner[_mask(size, scale, origin, path)] = names.index(name)
    return {name: owner == i for i, name in enumerate(names)}


def synthetic_parts_helm(size: int = 720, hair=HAIR, skin=SKIN) -> PartsDrawing:
    """A cel-shaded helm with the part kinds of spec 9.1 a helm usually has, painted in passes like the user's
    drawings (Flats, Shadow, Occlusion, Light, Details, Line), with the ground truth of its parts (head units; the AQW
    head faces right)."""
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    face, ear = _ellipse(-9, 10, 30, 33), _ellipse(-40, 14, 7, 10)
    mouth = _ellipse(-6, 31, 5, 1.8)
    hair_band = _path([(-42, -14), (26, -14), (26, -8), (-42, -8)])
    teeth = [_path([(x0, -8), (x1, -8), ((x0 + x1) / 2, 4)]) for x0, x1 in TEETH]
    side = _path(SIDE_LOCK)
    dome, band, gem = _hat_shapes()
    horn = _path(HORN_POINTS)
    eye = {}
    for side_name, cx in EYES.items():
        eye[side_name] = {"white": _ellipse(cx, 14, 6, 5), "iris": _ellipse(cx + 1, 14.5, 3.2, 3.2),
                          "pupil": _ellipse(cx + 1, 14.5, 1.4, 1.4), "highlight": _ellipse(cx + 2.2, 13.2, 0.9, 0.9)}
    brows = {s: _ellipse(cx, 6.5, 5, 1.1) for s, cx in EYES.items()}
    flats_order = [("Ear L", ear, skin), ("Face", face, skin), ("Mouth", mouth, MOUTH)]
    for s in "LR":
        for piece, color in (("white", WHITE), ("iris", IRIS), ("pupil", PUPIL), ("highlight", WHITE)):
            flats_order.append(("Eye %s %s" % (s, piece), eye[s][piece], color))
        flats_order.append(("Brow " + s, brows[s], hair))
    flats_order.append(("Hair", hair_band, hair))
    flats_order += [("Lock %d" % (k + 1), tooth, hair) for k, tooth in enumerate(teeth)]
    flats_order += [("Lock 6", side, hair), ("Helm", dome, DOME), ("Helm", band, BAND), ("Accessory 1", gem, GEM),
                    ("Horn R", horn, HORN)]
    hat_shadow, hat_light, hat_details = _hat_tones(dome, horn)

    hair_mass = hair_band
    for path in teeth + [side]:
        hair_mass = hair_mass.united(path)

    def flats(p):                                   # the hair is painted as one fill, like a bucket fill in CSP
        for name, path, color in flats_order:
            if name == "Hair":
                _qt_fill(p, hair_mass, color)
            elif not name.startswith("Lock"):
                _qt_fill(p, path, color)

    def shadow(p):
        _qt_fill(p, _ellipse(14, 26, 5, 8).intersected(face), (150, 130, 200))
        hat_shadow(p)

    def occlusion(p):
        _qt_fill(p, _path([(-42, -14), (26, -14), (26, -11.5), (-42, -11.5)]), (110, 90, 160))

    def light(p):
        _qt_fill(p, _ellipse(-20, -11, 6, 1.2), (255, 255, 255))
        hat_light(p)

    def line(p):
        strokes = [_brush(_arc(-9, 10, 30, 33, 15, 165), 1.4), _brush(_arc(-9, 10, 30, 33, 140, 215), 1.2),
                   _brush(_arc(-9, 10, 30, 33, 8, 20), 1.2), _brush(_arc(-40, 14, 7, 10, 90, 270), 1.0),
                   _brush(_arc(-6, 31, 5.4, 2.2, 180, 360), 0.8)]
        zigzag = [(-42, -14), (-42, -8)]
        for x0, x1 in TEETH:
            zigzag += [(x0, -8), ((x0 + x1) / 2, 4)]
        zigzag += [(14, -8), (19, 8), (25, 28), (28, 10), (26, -8), (26, -14)]
        strokes.append(_stroke(zigzag, 1.2))
        strokes += [_brush(_arc(cx, 14, 6.5, 5.5, 190, 350), 1.2) for cx in EYES.values()]
        strokes += _hat_lines() + [_stroke(HORN_POINTS, 1.0, closed=True)]
        for path in strokes:
            _qt_fill(p, path, INK)

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    layers = [LayerSpec("Flats", layer(flats)),
              LayerSpec("Shadow", layer(shadow), blend="multiply", clipping=True),
              LayerSpec("Occlusion", layer(occlusion), blend="multiply", clipping=True),
              LayerSpec("Light", layer(light), blend="screen", clipping=True),
              LayerSpec("Details", layer(hat_details)),
              LayerSpec("Line", layer(line))]
    owners = _truth(size, scale, origin, [(name, path) for name, path, _ in flats_order])
    truth, pieces = {}, {}
    for name, mask in owners.items():
        if name.startswith("Eye "):
            pieces[name] = mask
            part = " ".join(name.split()[:2])
            truth[part] = truth.get(part, np.zeros_like(mask)) | mask
        else:
            truth[name] = mask
    locations = {name: None for name in truth}
    locations.update({"Face": "Skin", "Ear L": "Skin", "Hair": "Hair", "Brow L": "Hair", "Brow R": "Hair"})
    locations.update({"Lock %d" % k: "Hair" for k in range(1, 7)})
    roots = {"Lock %d" % (k + 1): ((x0 + x1) / 2, -8.0) for k, (x0, x1) in enumerate(TEETH)}
    tips = {"Lock %d" % (k + 1): ((x0 + x1) / 2, 4.0) for k, (x0, x1) in enumerate(TEETH)}
    roots["Lock 6"], tips["Lock 6"] = (20.0, -8.0), (25.0, 28.0)
    return PartsDrawing(size, size, layers, Alignment(scale, origin), truth, pieces, locations, roots, tips)


def smooth_helmet(size: int = 480) -> PartsDrawing:
    """A skin face in a smooth steel helmet with a face opening: the helmet borders the face but is not hair."""
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    face = _ellipse(-9, 10, 30, 33)
    opening = _ellipse(-9, 14, 26, 30)
    helmet = _ellipse(-9, 0, 44, 50).subtracted(opening)

    def flats(p):
        _qt_fill(p, face, SKIN)
        _qt_fill(p, helmet, (90, 110, 140))

    def line(p):
        for path in (_stroke(_arc(-9, 0, 44, 50, 0, 360), 1.2, closed=True),
                     _stroke(_arc(-9, 14, 26, 30, 0, 360), 1.2, closed=True)):
            _qt_fill(p, path, INK)

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    layers = [LayerSpec("Flats", layer(flats)), LayerSpec("Line", layer(line))]
    truth = _truth(size, scale, origin, [("Face", face), ("Helm", helmet)])
    return PartsDrawing(size, size, layers, Alignment(scale, origin), truth, {}, {"Face": "Skin", "Helm": None})


def hat_only(size: int = 480) -> PartsDrawing:
    """The parts helm's hat alone (dome, band and gem with tones, details and outlines): nothing should be colorable."""
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    dome, band, gem = _hat_shapes()
    shadow, light, details = _hat_tones(dome)

    def flats(p):
        for path, color in ((dome, DOME), (band, BAND), (gem, GEM)):
            _qt_fill(p, path, color)

    def line(p):
        for path in _hat_lines():
            _qt_fill(p, path, INK)

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    layers = [LayerSpec("Flats", layer(flats)), LayerSpec("Shadow", layer(shadow), blend="multiply", clipping=True),
              LayerSpec("Light", layer(light), blend="screen", clipping=True), LayerSpec("Details", layer(details)),
              LayerSpec("Line", layer(line))]
    truth = _truth(size, scale, origin, [("Helm", dome), ("Helm", band), ("Accessory 1", gem)])
    return PartsDrawing(size, size, layers, Alignment(scale, origin), truth, {}, {"Helm": None, "Accessory 1": None})


def plated_helmet(color=(90, 110, 140), size: int = 480) -> PartsDrawing:
    """The smooth helmet split into plates by a crest line and two cheek-guard seams: still a helmet, not hair."""
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    face = _ellipse(-9, 10, 30, 33)
    opening = _ellipse(-9, 14, 26, 30)
    helmet = _ellipse(-9, 0, 44, 50).subtracted(opening)

    def flats(p):
        _qt_fill(p, face, SKIN)
        _qt_fill(p, helmet, color)

    def line(p):
        for path in (_stroke(_arc(-9, 0, 44, 50, 0, 360), 1.2, closed=True),
                     _stroke(_arc(-9, 14, 26, 30, 0, 360), 1.2, closed=True),
                     _stroke([(-9, -56), (-9, -10)], 1.0), _stroke([(-60, -5), (-20, -5)], 1.0),
                     _stroke([(2, -5), (42, -5)], 1.0)):
            _qt_fill(p, path, INK)

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    return PartsDrawing(size, size, [LayerSpec("Flats", layer(flats)), LayerSpec("Line", layer(line))],
                        Alignment(scale, origin))


def hat_over_hair(size: int = 480) -> PartsDrawing:
    """The parts helm's hat over its hair and locks, with no face at all."""
    scale, origin = size / 120, (0.55 * size, 0.5575 * size)
    mass = _path([(-42, -14), (26, -14), (26, -8), (-42, -8)])
    for x0, x1 in TEETH:
        mass = mass.united(_path([(x0, -8), (x1, -8), ((x0 + x1) / 2, 4)]))
    mass = mass.united(_path(SIDE_LOCK))
    dome, band, gem = _hat_shapes()

    def flats(p):
        _qt_fill(p, mass, HAIR)
        for path, color in ((dome, DOME), (band, BAND), (gem, GEM)):
            _qt_fill(p, path, color)

    def line(p):
        zigzag = [(-42, -14), (-42, -8)]
        for x0, x1 in TEETH:
            zigzag += [(x0, -8), ((x0 + x1) / 2, 4)]
        zigzag += [(14, -8), (19, 8), (25, 28), (28, 10), (26, -8), (26, -14)]
        for path in [_stroke(zigzag, 1.2)] + _hat_lines():
            _qt_fill(p, path, INK)

    layer = lambda paint: _qt_layer(size, scale, origin, paint)
    return PartsDrawing(size, size, [LayerSpec("Flats", layer(flats)), LayerSpec("Line", layer(line))],
                        Alignment(scale, origin))


def folder_helm(names=("Hair", "Face", "Bangs")) -> TestDrawing:
    """Hair painted in two folders, one under and one over the face folder (a common way to layer a head)."""
    W = H = 240
    hair, skin = HAIR + (255,), SKIN + (255,)
    back = rect(W, H, hair, 50, 20, 190, 80)
    bangs = rect(W, H, hair, 70, 60, 170, 110)
    for k in range(5):
        x = 70 + 20 * k
        bangs[110:130, x + 4:x + 16] = hair
    face = disc(W, H, skin, 120, 130, 60)
    layers = [LayerSpec(names[0], children=[LayerSpec("Flats", back)]),
              LayerSpec(names[1], children=[LayerSpec("Flats", face)]),
              LayerSpec(names[2], children=[LayerSpec("Flats", bangs)])]
    return TestDrawing(W, H, layers, Alignment(2.0, (137, 130)))
