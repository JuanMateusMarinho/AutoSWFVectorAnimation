"""Vector art from a drawing's passes: one gap-free fill shape per part with the cel tones baked in (each face
remembers its flat color and tone levels, so Plan 4 can turn tones into Dark/Darker/Light clips), plus details and
brush-like line art; and the static helm built from it."""
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.aqw.helm import HelmItem
from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import PartPasses, Passes
from autoswf.drawing.roles import TONE_ROLES
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import GradientFill, Path, Shape, SolidFill
from autoswf.vectorize.fit import DetailSettings, detail_settings
from autoswf.vectorize.gradient import fit_gradient
from autoswf.vectorize.palette import merge_small, palette_labels, relative_threshold
from autoswf.vectorize.planar import trace_shape

RGBA = tuple[int, int, int, int]
LAYER_NAMES = {"fills": "Fills", "details": "Details", "line": "Line"}


@dataclass(frozen=True)
class FaceStyle:
    color: RGBA                                   # baked color of the face
    flat: RGBA | None                             # flat color underneath (None for a tone over nothing)
    tones: tuple[tuple[str, int], ...] = ()       # (tone role, posterized level 1..n)


@dataclass(eq=False)
class TracedLayer:
    name: str
    role: str                                     # "fills", "details", "line" or "gradient"
    part: str | None
    shape: Shape
    styles: list[FaceStyle]                       # per fill index


@dataclass(eq=False)
class VectorArt:
    layers: list[TracedLayer]                     # bottom to top
    alignment: Alignment
    notes: list[str]
    soft: np.ndarray                              # canvas-sized: posterized areas (left out of color metrics)


@dataclass(frozen=True)
class VectorizeSettings:
    detail: int = 50
    posterize_steps: int = 3
    gradient_layers: frozenset[str] = field(default_factory=frozenset)


def _straight(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4]
    return np.where(a > 0, rgba[..., :3] / np.maximum(a, 1e-12), 0)


def _tone_levels(alpha: np.ndarray, soft: bool, steps: int) -> np.ndarray:
    nonzero = alpha[alpha > 0]
    if nonzero.size == 0:
        return np.zeros(alpha.shape, np.int32)
    if not soft:
        return (alpha >= relative_threshold(alpha)).astype(np.int32)
    m = float(np.percentile(nonzero, 95))
    return sum((alpha >= m * (k - 0.5) / steps).astype(np.int32) for k in range(1, steps + 1))


def _compact(labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dense labels 0..n-1 (-1 stays) and, per new label, the old label it was."""
    used = np.unique(labels[labels >= 0])
    lookup = np.full(int(labels.max()) + 2 if labels.size else 1, -1, np.int32)
    lookup[used] = np.arange(len(used))
    return np.where(labels >= 0, lookup[labels], -1).astype(np.int32), used


def _face_colors(labels: np.ndarray, rgba: np.ndarray, count: int) -> list[RGBA]:
    """Per label: the median color of `rgba` over its pixels eroded by 1 px (all of them for thin faces)."""
    color, alpha = _straight(rgba) * 255, rgba[..., 3]
    out = []
    boxes = ndimage.find_objects(labels + 1, max_label=count)
    for i in range(count):
        box = boxes[i]
        mask = labels[box] == i
        inner = ndimage.binary_erosion(mask)
        pick = inner if inner.any() else mask
        c = np.median(color[box][pick], axis=0)
        a = float(np.median(alpha[box][pick]))
        out.append(tuple(int(round(v)) for v in c) + (255 if a >= 0.98 else int(round(a * 255)),))
    return out


def _rescaled(rgba: np.ndarray) -> np.ndarray:
    """Alpha rescaled so the pass's own relative threshold lands on 0.5 (faint pencils and solid inks alike)."""
    threshold = relative_threshold(rgba[..., 3])
    out = rgba * (0.5 / max(threshold, 1e-6))
    over = out[..., 3] > 1
    out[over] /= out[over][:, 3:4]
    return out


def _paste(canvas: np.ndarray, mask: np.ndarray, origin: tuple[int, int]) -> None:
    x0, y0 = origin
    h, w = mask.shape
    canvas[y0:y0 + h, x0:x0 + w] |= mask


def _fills(part: PartPasses, ds: DetailSettings, settings: VectorizeSettings, soft: np.ndarray):
    flat = palette_labels(part.flats, posterize=ds.posterize, min_pixels=ds.min_area)
    tones = [t for t in part.tones if not set(t.layers) & settings.gradient_layers]
    levels = [_tone_levels(t.alpha, t.soft, settings.posterize_steps) for t in tones]
    keys = np.stack([flat.labels + 1] + levels, axis=-1).reshape(-1, 1 + len(levels))
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    labels = inverse.reshape(flat.labels.shape).astype(np.int32)
    empty = [i for i, k in enumerate(unique) if not k.any()]
    if empty:
        labels[labels == empty[0]] = -1
    labels, old = _compact(merge_small(labels, ds.min_area))
    if not old.size:
        return None
    colors = _face_colors(labels, part.fills, len(old))
    styles = []
    for i, key in enumerate(unique[old]):
        flat_color = flat.colors[key[0] - 1] if key[0] > 0 else None
        styles.append(FaceStyle(colors[i], flat_color, tuple((t.role, int(v)) for t, v in zip(tones, key[1:]) if v > 0)))
    for t in tones:
        if t.soft:
            _paste(soft, t.alpha > 0.02, part.origin)
    if flat.posterized:
        _paste(soft, np.isin(flat.labels, list(flat.posterized)), part.origin)
    return labels, styles


def _simple(rgba: np.ndarray, ds: DetailSettings, origin, soft: np.ndarray):
    li = palette_labels(_rescaled(rgba), posterize=ds.posterize, min_pixels=ds.min_area)
    labels, old = _compact(merge_small(li.labels, ds.min_area))
    if not old.size:
        return None
    if li.posterized:
        _paste(soft, np.isin(li.labels, list(li.posterized)), origin)
    return labels, [FaceStyle(li.colors[i], None) for i in old]


def _gradient_layer(part: PartPasses, tone, name: str, ds: DetailSettings, matrix: Matrix, soft: np.ndarray,
                    notes: list[str]) -> TracedLayer | None:
    """A soft tone drawn as one gradient-filled shape over the fills, in normal blend."""
    alpha = tone.alpha
    mask = alpha > 2 / 255
    if not mask.any():
        return None
    strong = alpha >= 0.5 * alpha.max()
    a = alpha[strong][:, None]
    color = np.median((part.fills[strong][:, :3] - part.flats[strong][:, :3] * (1 - a)) / a, axis=0)
    color = tuple(int(round(v)) for v in np.clip(color, 0, 1) * 255)
    gradient, _ = fit_gradient(color, alpha)
    fill = GradientFill(gradient.kind, gradient.stops, matrix @ gradient.matrix)
    labels = merge_small(np.where(mask, 0, -1).astype(np.int32), ds.min_area)
    if any(b != "normal" for b in tone.blends):
        notes.append("Layer '%s' is drawn as a normal gradient; its blend mode is approximated" % name)
    _paste(soft, mask, part.origin)
    shape = trace_shape(labels, [fill], ds.fit, matrix)
    return TracedLayer(name + " (gradient)", "gradient", part.part, shape, [FaceStyle(color + (255,), None)])


def vectorize(passes: Passes, alignment: Alignment, settings: VectorizeSettings = VectorizeSettings()) -> VectorArt:
    ds = detail_settings(settings.detail)
    soft = np.zeros((passes.height, passes.width), bool)
    tone_names = {n for part in passes.parts for t in part.tones for n in t.layers}
    missing = sorted(settings.gradient_layers - tone_names)
    if missing:
        raise ValueError("No tone layer named '%s' to draw with gradients (only shadow, occlusion and light layers "
                         "can be gradients)" % missing[0])
    notes = list(passes.notes)
    layers = []
    for part in passes.parts:
        matrix = alignment.matrix() @ Matrix.translate(*part.origin)
        prefix = "%s: " % part.part if part.part else ""
        traced = {"fills": _fills(part, ds, settings, soft),
                  "details": _simple(part.details, ds, part.origin, soft),
                  "line": _simple(part.lines, ds, part.origin, soft)}
        for role in part.order:
            result = traced.get(role)
            if result is None:
                continue
            labels, styles = result
            shape = trace_shape(labels, [SolidFill(s.color) for s in styles], ds.fit, matrix)
            layers.append(TracedLayer(prefix + LAYER_NAMES[role], role, part.part, shape, styles))
            if role == "fills":
                for tone in part.tones:
                    wanted = [n for n in tone.layers if n in settings.gradient_layers]
                    overlay = _gradient_layer(part, tone, prefix + wanted[0], ds, matrix, soft, notes) if wanted else None
                    if overlay is not None:
                        layers.append(overlay)
    return VectorArt(layers, alignment, notes, soft)


def _recolored(layer: TracedLayer, name: str, mapping: list[FaceStyle | None]) -> TracedLayer:
    """The same geometry with each face i drawn as mapping[i] (None = empty); faces with equal styles share a fill
    and the edges between them are dropped."""
    styles, index = [], {}
    for style in mapping:
        if style is not None and style not in index:
            index[style] = len(styles)
            styles.append(style)
    fill_of = [index[s] if s is not None else None for s in mapping]
    paths = []
    for p in layer.shape.paths:
        left = fill_of[p.fill_left] if p.fill_left is not None else None
        right = fill_of[p.fill_right] if p.fill_right is not None else None
        if left != right:
            paths.append(Path(p.start, p.segments, fill_left=left, fill_right=right))
    return TracedLayer(name, layer.role, layer.part, Shape([SolidFill(s.color) for s in styles], paths), styles)


def split_tones(layer: TracedLayer) -> list[TracedLayer]:
    """[base (flat colors only), one layer per tone role] with the same edges, for color-custom clips (Plan 4)."""
    base = [FaceStyle(s.flat, s.flat) if s.flat is not None else None for s in layer.styles]
    out = [_recolored(layer, layer.name + " base", base)]
    for role in TONE_ROLES:
        mapping = [s if role in dict(s.tones) else None for s in layer.styles]
        if any(mapping):
            out.append(_recolored(layer, "%s %s" % (layer.name, role), mapping))
    return out


def helm_from_art(art: VectorArt, link: str, *, separate_tones: bool = False) -> HelmItem:
    layers = []
    for layer in art.layers:
        layers += split_tones(layer) if separate_tones and layer.role == "fills" else [layer]
    root = Symbol(link, [Frame([Placement(layer.shape, depth) for depth, layer in enumerate(layers, start=1)])])
    return HelmItem(link, root)


def segment_count(art: VectorArt) -> int:
    return sum(len(p.segments) for layer in art.layers for p in layer.shape.paths)
