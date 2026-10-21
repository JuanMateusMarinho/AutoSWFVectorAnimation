"""Trace PNG… (Plan 7, spec §8.8): a piece exported from Clip Studio as a PNG with transparency, vectorized in the
app's style, either replacing a layer (its colors matched to the layer's tones, so the AQW colors and the animation
stay) or becoming a new layer (its AQW color suggested from the item's colored tones)."""
from dataclasses import dataclass

import numpy as np

from autoswf.edit.layer import RGBA, EditLayer, LayerEdit, Tone, ToneRef
from autoswf.edit.regions import fill_areas, rebuild_shape, transform_area, union
from autoswf.model.geometry import Matrix
from autoswf.model.shape import Shape, SolidFill
from autoswf.vectorize.art import vectorize_image

MATCH_DISTANCE = 60
OPAQUE = "The PNG has no transparent background; export the piece from Clip Studio with transparency."
EMPTY = "The PNG is empty."


@dataclass
class TracedPng:
    shape: Shape                       # in the PNG's px, one fill per color
    colors: list[RGBA]
    size: tuple[int, int]              # width, height


def read_png(path) -> np.ndarray:
    from PIL import Image
    with Image.open(path) as img:
        rgba = np.array(img.convert("RGBA"))
    alpha = rgba[..., 3]
    if not alpha.any():
        raise ValueError(EMPTY)
    if (alpha == 255).all():
        raise ValueError(OPAQUE)
    return rgba


def trace_png(rgba: np.ndarray, detail: int = 50) -> TracedPng:
    traced = vectorize_image(rgba, detail)
    if traced is None:
        raise ValueError(EMPTY)
    return TracedPng(traced.shape, [s.color for s in traced.styles], (rgba.shape[1], rgba.shape[0]))


def placement(png_size, *, source_size: tuple[int, int] | None = None, source_matrix: Matrix | None = None,
              target_bounds: tuple[float, float, float, float] | None = None) -> Matrix:
    """PNG px -> layer px: where the drawing was when the PNG has the drawing's canvas size, else fitted (aspect kept)
    and centered in the target bounds (x0, x1, y0, y1), else centered on the origin."""
    w, h = png_size
    if source_size is not None and source_matrix is not None and tuple(png_size) == tuple(source_size):
        return source_matrix
    if target_bounds is not None:
        x0, x1, y0, y1 = target_bounds
        scale = min((x1 - x0) / w, (y1 - y0) / h)
        return Matrix(scale, 0, 0, scale, (x0 + x1) / 2 - w * scale / 2, (y0 + y1) / 2 - h * scale / 2)
    return Matrix.translate(-w / 2, -h / 2)


def _distance(a, b) -> float:
    return float(np.sqrt(sum((int(x) - int(y)) ** 2 for x, y in zip(a[:3], b[:3]))))


def _drawn(layer: EditLayer, ref: ToneRef):
    """The color a tone's fill is drawn with (its shown color may be the player's)."""
    d = next((d for d in layer.drawings if d.key == ref.drawing), None)
    if d is None or ref.fill >= len(d.shape.fills) or not isinstance(d.shape.fills[ref.fill], SolidFill):
        return None
    return d.shape.fills[ref.fill].color


def _match(layer: EditLayer, color: RGBA) -> ToneRef | None:
    best, dist = None, None
    for tone in layer.tones:
        candidates = [tone.color] + ([c] if (c := _drawn(layer, tone.ref)) is not None else [])
        d = min(_distance(color, c) for c in candidates)
        if d <= MATCH_DISTANCE and (dist is None or d < dist):
            best, dist = tone.ref, d
    return best


def _areas(traced: TracedPng, matrix: Matrix):
    return [(traced.colors[f], transform_area(a, matrix)) for f, a in sorted(fill_areas(traced.shape).items())]


def replace_layer(layer: EditLayer, traced: TracedPng, matrix: Matrix) -> LayerEdit:
    """The layer's drawings (as shown) cleared and painted again with the PNG, each color into its nearest tone (a
    color no tone matches becomes a fixed tone)."""
    everything = []
    for area in layer.visible_areas().values():
        everything = union(everything, area)
    work = layer.applied(layer.erase(everything))
    notes = []
    for color, area in _areas(traced, matrix):
        ref = _match(layer, color)
        edit = work.paint(area, ref if ref is not None else tuple(color))
        notes += [n for n in edit.notes if n not in notes]
        work = work.applied(edit)
    shapes = {d.key: d.shape for d, old in zip(work.drawings, layer.drawings) if d.shape is not old.shape}
    return LayerEdit(shapes, notes)


def suggest_binding(color: RGBA, bound: list[Tone]) -> tuple[str, str] | None:
    near = [(t, _distance(color, t.color)) for t in bound if t.binding is not None]
    near = [(t, d) for t, d in near if d <= MATCH_DISTANCE]
    return min(near, key=lambda x: x[1])[0].binding if near else None


def new_layer_tones(traced: TracedPng, matrix: Matrix, bound: list[Tone]) -> list[tuple[Shape, tuple[str, str] | None]]:
    """One shape per PNG color, in layer px, with the AQW color suggested for it."""
    out = []
    for color, area in _areas(traced, matrix):
        shape = rebuild_shape(Shape([SolidFill(tuple(color))], []), {0: area})
        out.append((shape, suggest_binding(color, bound)))
    return out
