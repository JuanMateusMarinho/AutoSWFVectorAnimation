"""Layered test drawings made from official AQW items in the local cache (never committed): each shape of the item
goes to the painting pass it plays (color-custom shade, black line art, gradients as details), and each pass is
rendered on its own, so the vector ground truth of the drawing is known."""
import dataclasses

import numpy as np

from autoswf.aqw.template import Alignment
from autoswf.drawing.writers import LayerSpec
from autoswf.model.geometry import Matrix
from autoswf.render.display import ClipInstance, ScriptContext, ShapeInstance, instantiate, run_pending_actions
from autoswf.render.effects import qimage_to_array
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import GradientStyle, ShapeDef, SolidStyle
from drawings import TestDrawing

SHADE_ROLES = {"none": "Flats", "dark": "Shadow", "darker": "Occlusion", "light": "Light"}
LAYER_ORDER = ("Flats", "Shadow", "Occlusion", "Light", "Details", "Line")
MIN_LINE_WIDTH = 0.4           # head units: Flash hairlines would be 1 px at 10x, too thin for brush-like lines
MARGIN = 20


def _shapes(obj, shade=None, out=None):
    """Visible drawn shapes in draw order with the shade of their nearest colorable ancestor."""
    out = [] if out is None else out
    if not obj.visible:
        return out
    if obj.color_custom is not None:
        shade = obj.color_custom[1].lower()
    if isinstance(obj, ShapeInstance):
        if obj.clip_depth is None:
            out.append((obj, shade))
    elif isinstance(obj, ClipInstance):
        for child in obj.children:
            _shapes(child, shade, out)
    return out


def _dark(shape: ShapeDef) -> bool:
    fills = [f for f in shape.fills if isinstance(f, SolidStyle)]
    return bool(shape.fills) and len(fills) == len(shape.fills) and all(
        max(f.color[:3]) <= 40 and f.color[3] >= 230 for f in fills)


def _render(obj, view: Matrix, size: tuple[int, int]) -> np.ndarray:
    return qimage_to_array(Renderer(cache_bytes=0).render_image(obj, *size, view, None))


def _show_only(shapes, keep) -> None:
    for inst, _ in shapes:
        inst.visible = inst in keep


def official_drawing(movie, class_name: str, scale: float = 10.0) -> TestDrawing:
    obj = instantiate(movie, movie.classes[class_name])
    run_pending_actions(obj, ScriptContext(None))
    shapes = _shapes(obj)
    widened = {}
    for inst, _ in shapes:
        if isinstance(inst.shape, ShapeDef) and any(l.width < MIN_LINE_WIDTH for l in inst.shape.lines):
            if inst.char_id not in widened:
                lines = tuple(dataclasses.replace(l, width=max(l.width, MIN_LINE_WIDTH)) for l in inst.shape.lines)
                widened[inst.char_id] = dataclasses.replace(inst.shape, lines=lines)
            inst.shape = widened[inst.char_id]
    xmin, xmax, ymin, ymax = object_bounds(obj, Matrix.scale(scale, scale))
    size = (int(np.ceil(xmax - xmin)) + 2 * MARGIN, int(np.ceil(ymax - ymin)) + 2 * MARGIN)
    origin = (MARGIN - xmin, MARGIN - ymin)
    view = Matrix.translate(*origin) @ Matrix.scale(scale, scale)

    roles = {}
    for inst, shade in shapes:
        s = inst.shape
        if shade is not None:
            roles[inst] = SHADE_ROLES.get(shade, "Flats")
        elif isinstance(s, ShapeDef) and any(isinstance(f, GradientStyle) for f in s.fills):
            roles[inst] = "Details"
        elif isinstance(s, ShapeDef) and ((s.lines and not s.fills) or _dark(s)):
            roles[inst] = "Line"
        else:
            roles[inst] = "Flats"
    for i, (inst, _) in enumerate(shapes):            # black shapes under later colored shapes are flats, not lines
        if roles[inst] != "Line":
            continue
        later = {s for s, _ in shapes[i + 1:] if roles[s] != "Line"}
        if not later:
            continue
        _show_only(shapes, {inst})
        mine = _render(obj, view, size)[..., 3] > 0.5
        _show_only(shapes, later)
        covered = _render(obj, view, size)[..., 3] > 0.5
        if mine.any() and (mine & covered).sum() > 0.05 * mine.sum():
            roles[inst] = "Flats"

    layers = []
    for name in LAYER_ORDER:
        members = {inst for inst, role in roles.items() if role == name}
        if not members:
            continue
        _show_only(shapes, members)
        image = _render(obj, view, size)
        a = image[..., 3:4]
        straight = np.where(a > 0, image[..., :3] / np.maximum(a, 1e-12), 0)
        layers.append(LayerSpec(name, np.round(np.dstack([straight, a]) * 255).astype(np.uint8)))
    _show_only(shapes, {inst for inst, _ in shapes})
    return TestDrawing(size[0], size[1], layers, Alignment(scale, origin))


def official_segment_count(movie, class_name: str) -> int:
    """Edges of every visible shape instance of the class, as the artist drew them in Animate."""
    obj = instantiate(movie, movie.classes[class_name])
    run_pending_actions(obj, ScriptContext(None))
    total = 0
    for inst, _ in _shapes(obj):
        shape = inst.shape.start if hasattr(inst.shape, "start") else inst.shape
        total += len(shape.edges)
    return total
