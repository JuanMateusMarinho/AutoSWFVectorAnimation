"""Vector art from a drawing's passes: one gap-free fill shape per part with the cel tones baked in (each face
remembers its flat color and tone levels, so Plan 4 can turn tones into Dark/Darker/Light clips), plus details and
brush-like line art; and the static helm built from it."""
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.aqw.helm import HelmItem
from autoswf.aqw.template import Alignment
from autoswf.drawing.layers import DrawingError
from autoswf.drawing.passes import PartPasses, Passes
from autoswf.drawing.roles import TONE_ROLES
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import GradientFill, Path, Shape, SolidFill
from autoswf.vectorize.fit import DetailSettings, FitSettings, detail_settings
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
    labels: np.ndarray | None = None              # the traced label image (face per pixel, -1 = empty)
    matrix: Matrix | None = None                  # its pixels -> output px
    fit: FitSettings | None = None                # the curve fitting it was traced with
    hidden: np.ndarray | None = None              # its pixels covered at rest by other parts


@dataclass(eq=False)
class VectorArt:
    layers: list[TracedLayer]                     # bottom to top
    alignment: Alignment
    notes: list[str]
    soft: np.ndarray                              # canvas-sized: posterized areas (left out of color metrics)
    tolerance: float = 0.8                        # curve fitting tolerance used, source px


@dataclass(frozen=True)
class VectorizeSettings:
    detail: int = 50
    posterize_steps: int = 3


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
    """Per label: the median color of `rgba` over its painted pixels eroded by 1 px (all of them for thin faces)."""
    color, alpha = _straight(rgba) * 255, rgba[..., 3]
    out = []
    boxes = ndimage.find_objects(labels + 1, max_label=count)
    for i in range(count):
        box = boxes[i]
        mask = labels[box] == i
        painted = mask & (alpha[box] > 0)
        mask = painted if painted.any() else mask
        inner = ndimage.binary_erosion(mask)
        pick = inner if inner.any() else mask
        c = np.median(color[box][pick], axis=0)
        a = float(np.percentile(alpha[box][pick], 95))
        out.append(tuple(int(round(v)) for v in c) + (255 if a >= 0.98 else int(round(a * 255)),))
    return out


def stroke_coverage(rgba: np.ndarray) -> np.ndarray:
    """The pass with each stroke's alpha rescaled so half of the stroke's own peak lands on palette_labels' 0.5 cut:
    faint pencils, low-opacity layers and solid inks all keep their shape (their real opacity is restored later).
    Strokes touching only diagonally are bridged, so thin lines stay one 4-connected piece."""
    alpha = rgba[..., 3]
    strokes, count = ndimage.label(alpha > 0.02, structure=np.ones((3, 3)))
    if count == 0:
        return rgba
    peak = np.zeros(count + 1, np.float32)
    peak[1:] = ndimage.maximum(alpha, strokes, index=np.arange(1, count + 1))
    scale = np.where(strokes > 0, 1.0 / np.maximum(peak[strokes], 1e-6), 1.0)
    out = rgba * scale[..., None]
    over = out[..., 3] > 1
    out[over] /= out[over][:, 3:4]
    for _ in range(2):
        solid = out[..., 3] >= 0.5
        for flip in (False, True):
            s = solid[:, ::-1] if flip else solid
            a = out[:, ::-1, 3] if flip else out[..., 3]
            gap = s[:-1, :-1] & s[1:, 1:] & ~s[:-1, 1:] & ~s[1:, :-1]
            ys, xs = np.nonzero(gap)
            if not len(ys):
                continue
            right_better = a[ys, xs + 1] >= a[ys + 1, xs]          # turn on the stronger of the two corner pixels
            ty = np.where(right_better, ys, ys + 1)
            tx = np.where(right_better, xs + 1, xs)
            sx = xs
            if flip:
                tx, sx = out.shape[1] - 1 - tx, out.shape[1] - 1 - xs
            source = out[ys, sx]                                     # paint it with the stroke's own color
            out[ty, tx, :3] = source[:, :3] / np.maximum(source[:, 3:4], 1e-6) * 0.5
            out[ty, tx, 3] = 0.5
    return out


def _opacity_split(labels: np.ndarray, colors: list[RGBA], alpha: np.ndarray) -> tuple[np.ndarray, list[RGBA]]:
    """Each connected piece of a label gets the real opacity of its stroke (95th percentile of the pass's own alpha):
    a 40 % line next to a 100 % line of the same color becomes its own face."""
    out = np.full(labels.shape, -1, np.int32)
    styles: dict[RGBA, int] = {}
    count = int(labels.max()) + 1 if labels.size else 0
    for value, box in enumerate(ndimage.find_objects(labels + 1, max_label=count)):
        if box is None:
            continue
        pieces, n = ndimage.label(labels[box] == value, structure=np.ones((3, 3)))
        levels = ndimage.labeled_comprehension(alpha[box], pieces, np.arange(1, n + 1),
                                               lambda a: np.percentile(a, 95), np.float64, 0.0)
        for piece, level in enumerate(levels, start=1):
            a = 255 if level >= 0.98 else max(1, int(round(level * 255)))
            style = tuple(colors[value][:3]) + (a,)
            index = styles.setdefault(style, len(styles))
            out[box][pieces == piece] = index
    return out, list(styles)


def _paste(canvas: np.ndarray, mask: np.ndarray, origin: tuple[int, int]) -> None:
    x0, y0 = origin
    h, w = mask.shape
    canvas[y0:y0 + h, x0:x0 + w] |= mask


def _split_tints(labels: np.ndarray, keys: np.ndarray, fills: np.ndarray, ds: DetailSettings) -> np.ndarray:
    """A face whose baked colors are clearly two or more flat colors (one tone layer painted with several tints over
    the same flat color) is split along those colors; the new faces keep the face's key. Returns the extended keys."""
    snapped = palette_labels(fills, posterize=ds.posterize, min_pixels=ds.min_area).labels
    keys = list(keys)
    count = int(labels.max()) + 1 if labels.size else 0
    for face, box in enumerate(ndimage.find_objects(labels + 1, max_label=count)):
        if box is None:
            continue
        mask = labels[box] == face
        colors, sizes = np.unique(snapped[box][mask], return_counts=True)
        big = [c for c, n in zip(colors, sizes) if c >= 0 and n >= max(4 * ds.min_area, 0.05 * mask.sum())]
        if len(big) < 2:
            continue
        big.sort(key=lambda c: -sizes[list(colors).index(c)])
        for c in big[1:]:
            region = labels[box]
            region[mask & (snapped[box] == c)] = len(keys)
            keys.append(keys[face])
    return np.array(keys)


def _under_lines(labels: np.ndarray, lines: np.ndarray) -> None:
    """Fills tuck under the line art drawn over them (as Animate artists draw them): two shapes that only touch leave
    a seam, a fill reaching under its line does not. A fill grows into the line's coverage up to 1.5 px from the line's
    far edge, and only as deep as about twice that distance (so it never runs along a stroke that leaves the fill, and
    never appears under lines that touch no fill)."""
    cover = stroke_coverage(lines)[..., 3] >= 0.5
    fill = labels >= 0
    zone = cover & ~fill
    if not zone.any() or not fill.any():
        return
    to_fill, nearest = ndimage.distance_transform_edt(~fill, return_indices=True)
    outside = ~fill & ~cover
    to_out = ndimage.distance_transform_edt(~outside) if outside.any() else np.full(labels.shape, np.inf)
    grow = zone & (to_out >= 1.5) & (to_fill <= 2 * to_out + 1)
    labels[grow] = labels[nearest[0][grow], nearest[1][grow]]


def _fills(part: PartPasses, ds: DetailSettings, settings: VectorizeSettings, soft: np.ndarray):
    flat = palette_labels(stroke_coverage(part.flats), posterize=ds.posterize, min_pixels=ds.min_area)
    tones = [t for t in part.tones if not t.gradient]
    levels = [_tone_levels(t.alpha, t.soft, settings.posterize_steps) for t in tones]
    code = (flat.labels + 1).astype(np.int64)                 # one int per (flat, tone levels) key: fast unique
    for level in levels:
        code = code * 16 + level
    codes, inverse = np.unique(code, return_inverse=True)
    labels = inverse.reshape(flat.labels.shape).astype(np.int32)
    unique = np.zeros((len(codes), 1 + len(levels)), np.int64)
    for k in range(len(levels), 0, -1):
        unique[:, k] = codes % 16
        codes = codes // 16
    unique[:, 0] = codes
    empty = [i for i, k in enumerate(unique) if not k.any()]
    if empty:
        labels[labels == empty[0]] = -1
    unique = _split_tints(labels, unique, part.fills, ds)
    if {"line", "fills"} <= set(part.order) and part.order.index("line") > part.order.index("fills"):
        _under_lines(labels, part.lines)
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
    li = palette_labels(stroke_coverage(rgba), posterize=ds.posterize, min_pixels=ds.min_area)
    labels, colors = _opacity_split(merge_small(li.labels, ds.min_area), li.colors, rgba[..., 3])
    if not colors:
        return None
    if li.posterized:
        _paste(soft, np.isin(li.labels, list(li.posterized)), origin)
    return labels, [FaceStyle(c, None) for c in colors]


def _gradient_layer(part: PartPasses, tone, ds: DetailSettings, matrix: Matrix, soft: np.ndarray,
                    notes: list[str], prefix: str) -> TracedLayer | None:
    """A soft tone layer drawn as one gradient-filled shape over the fills (which leave it out), in normal blend."""
    alpha = tone.alpha
    mask = alpha > 2 / 255
    if not mask.any() or tone.color is None:
        return None
    gradient, _ = fit_gradient(tone.color, alpha)
    fill = GradientFill(gradient.kind, gradient.stops, matrix @ gradient.matrix)
    labels = merge_small(np.where(mask, 0, -1).astype(np.int32), ds.min_area)
    if any(b != "normal" for b in tone.blends):
        notes.append("Layer '%s' is drawn as a normal gradient; its blend mode is approximated" % tone.layers[0])
    _paste(soft, mask, part.origin)
    shape = trace_shape(labels, [fill], ds.fit, matrix)
    return TracedLayer(prefix + tone.layers[0] + " (gradient)", "gradient", part.part, shape,
                       [FaceStyle(tone.color + (255,), None)])


def vectorize(passes: Passes, alignment: Alignment, settings: VectorizeSettings = VectorizeSettings()) -> VectorArt:
    ds = detail_settings(settings.detail)
    soft = np.zeros((passes.height, passes.width), bool)
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
            hidden = part.hidden if role == "fills" else None
            shape = trace_shape(labels, [SolidFill(s.color) for s in styles], ds.fit, matrix, hidden)
            layers.append(TracedLayer(prefix + LAYER_NAMES[role], role, part.part, shape, styles, labels, matrix, ds.fit,
                                      hidden))
            if role == "fills":
                for tone in part.tones:
                    overlay = _gradient_layer(part, tone, ds, matrix, soft, notes, prefix) if tone.gradient else None
                    if overlay is not None:
                        layers.append(overlay)
    if not layers:
        raise DrawingError("Nothing was traced: every region is smaller than the detail setting keeps (try a higher "
                           "--detail) or too faint")
    return VectorArt(layers, alignment, notes, soft, ds.fit.tolerance)


def recolored(layer: TracedLayer, name: str, mapping: list[FaceStyle | None]) -> TracedLayer:
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
    out = [recolored(layer, layer.name + " base", base)]
    for role in TONE_ROLES:
        mapping = [s if role in dict(s.tones) else None for s in layer.styles]
        if any(mapping):
            out.append(recolored(layer, "%s %s" % (layer.name, role), mapping))
    return out


def helm_from_art(art: VectorArt, link: str, *, separate_tones: bool = False) -> HelmItem:
    layers = []
    for layer in art.layers:
        layers += split_tones(layer) if separate_tones and layer.role == "fills" else [layer]
    root = Symbol(link, [Frame([Placement(layer.shape, depth) for depth, layer in enumerate(layers, start=1)])])
    return HelmItem(link, root)


def segment_count(art: VectorArt) -> int:
    return sum(len(p.segments) for layer in art.layers for p in layer.shape.paths)
