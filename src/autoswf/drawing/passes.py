"""Split a drawing into the painting passes the vectorizer traces: flat colors, the coverage of each tone (shadow,
occlusion, light), the fill composite with the tones' blend modes baked in, details and line art — per part folder."""
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.drawing.composite import composite
from autoswf.drawing.layers import Drawing, DrawingError, LayerNode
from autoswf.drawing.roles import IGNORE, ROLES, TONE_ROLES, LayerRole

FILL_ROLES = ("flat",) + TONE_ROLES
GROUPS = (("fills", FILL_ROLES), ("details", ("details",)), ("line", ("line",)))
NO_ROLES_NOTE = ("No layer name matches a painting pass (line, flats, shadow, occlusion, light, details); the whole "
                 "drawing is vectorized as flat colors. Name your layers or pass --role \"LAYER=ROLE\".")


@dataclass
class ToneCoverage:
    role: str
    alpha: np.ndarray                    # H x W float32 coverage 0..1 (clipping and opacity applied)
    soft: bool
    layers: tuple[str, ...]
    blends: tuple[str, ...] = ()
    color: tuple[int, int, int] | None = None    # the layers' own paint color where they are strong
    gradient: bool = False                       # drawn as an SWF gradient (left out of the fill composite)


@dataclass
class PartPasses:
    part: str | None
    origin: tuple[int, int]              # canvas pixel of the arrays' top-left corner
    flats: np.ndarray                    # float32 premultiplied RGBA (also fills, details, lines)
    tones: list[ToneCoverage]
    fills: np.ndarray
    details: np.ndarray
    lines: np.ndarray
    order: list[str]                     # "fills", "details", "line" bottom to top as in the source
    tone_above_lines: bool = False


@dataclass
class Passes:
    width: int
    height: int
    parts: list[PartPasses]
    full: np.ndarray                     # every used layer on the whole canvas
    flattened: bool
    notes: list[str] = field(default_factory=list)
    gradient_layers: frozenset[str] = frozenset()


def is_soft(alpha: np.ndarray) -> bool:
    """Airbrushed or gradient coverage, as opposed to hard cel shading with anti-aliased edges."""
    nonzero = alpha[alpha > 0]
    if nonzero.size == 0:
        return False
    m = float(np.percentile(nonzero, 95))
    mid = int(((alpha > 0.1 * m) & (alpha < 0.9 * m)).sum())
    mask = alpha >= 0.5 * m
    boundary = int((mask & ~ndimage.binary_erosion(mask)).sum())
    return mid > 3 * boundary


def _content_box(rgba: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _flattened(drawing: Drawing, roles: dict[LayerNode, LayerRole], notes: list[str], cnotes: set[str]) -> Passes:
    def include(node):
        return drawing.flattened or node not in roles or roles[node].role != IGNORE
    full = composite(drawing, include, notes=cnotes)
    box = _content_box(full)
    if box is None:
        raise DrawingError("Nothing to vectorize: every layer is empty, hidden or ignored")
    x0, y0, x1, y1 = box
    flats = full[y0:y1, x0:x1].copy()
    empty = np.zeros_like(flats)
    part = PartPasses(None, (x0, y0), flats, [], flats, empty, empty.copy(), ["fills"])
    if not drawing.flattened:
        notes.append(NO_ROLES_NOTE)
    return Passes(drawing.width, drawing.height, [part], full, True, notes + sorted(cnotes))


def _paint_color(rgba: np.ndarray) -> tuple[int, int, int] | None:
    alpha = rgba[..., 3]
    if not alpha.any():
        return None
    strong = alpha >= 0.5 * alpha.max()
    color = np.median(rgba[strong][:, :3] / alpha[strong][:, None], axis=0)
    return tuple(int(round(v)) for v in np.clip(color, 0, 1) * 255)


def _tone(drawing: Drawing, include, role: str, layers: list[LayerNode], box, gradient: bool) -> ToneCoverage | None:
    own = composite(drawing, include, force_normal=True, box=box)
    alpha = own[..., 3]
    if not alpha.any():
        return None
    return ToneCoverage(role, alpha, is_soft(alpha), tuple(n.name for n in layers), tuple(n.blend for n in layers),
                        _paint_color(own), gradient)


def extract_passes(drawing: Drawing, roles: dict[LayerNode, LayerRole],
                   gradient_layers: frozenset[str] = frozenset()) -> Passes:
    """`gradient_layers`: tone layers (by name) to draw as SWF gradients; they stay out of the fill composite."""
    tone_names = {n.name for n, r in roles.items() if r.role in TONE_ROLES}
    missing = sorted(set(gradient_layers) - tone_names)
    if missing:
        raise ValueError("No tone layer named '%s' to draw with gradients (only shadow, occlusion and light layers "
                         "can be gradients)" % missing[0])
    notes, cnotes = list(drawing.notes), set()
    for node, role in roles.items():
        if role.role in ROLES and node.kind == "pixel" and node.pixels is None:
            notes.append("Layer '%s' (%s) is empty; if it is a vector layer, rasterize it in Clip Studio Paint "
                         "(Layer > Rasterize) and save again" % (node.name, role.role))
    order = {node: i for i, (node, _) in enumerate(drawing.walk())}
    used = [n for n, r in roles.items() if r.role in ROLES and n.kind == "pixel" and n.pixels is not None]
    if drawing.flattened or not used:
        return _flattened(drawing, roles, notes, cnotes)

    parts: dict[str | None, list[LayerNode]] = {}
    for node in sorted(used, key=order.get):
        parts.setdefault(roles[node].part, []).append(node)
    result = []
    for part, nodes in parts.items():
        members = {n for n in nodes if n.name not in gradient_layers}

        def only(*wanted, members=members):
            return lambda n: n in members and roles[n].role in wanted

        x0 = max(0, min(n.left for n in nodes))
        y0 = max(0, min(n.top for n in nodes))
        x1 = min(drawing.width, max(n.left + n.pixels.shape[1] for n in nodes))
        y1 = min(drawing.height, max(n.top + n.pixels.shape[0] for n in nodes))
        if x1 <= x0 or y1 <= y0:
            continue
        box = (x0, y0, x1, y1)
        tones = []
        for role in TONE_ROLES:
            plain = [n for n in nodes if roles[n].role == role and n.name not in gradient_layers]
            if plain:
                tones.append(_tone(drawing, only(role), role, plain, box, False))
            for n in nodes:
                if roles[n].role == role and n.name in gradient_layers:
                    tones.append(_tone(drawing, lambda node, n=n: node is n, role, [n], box, True))
        tones = [t for t in tones if t is not None]
        first = {}
        for group, group_roles in GROUPS:
            indexes = [order[n] for n in nodes if roles[n].role in group_roles]
            if indexes:
                first[group] = min(indexes)
        lowest_line = first.get("line")
        above = [n for n in nodes if roles[n].role in TONE_ROLES and lowest_line is not None and order[n] > lowest_line]
        for n in above:
            notes.append("Tone layer '%s' is above the line art; it is baked under the lines" % n.name)
        result.append(PartPasses(
            part, (x0, y0),
            flats=composite(drawing, only("flat"), box=box, notes=cnotes),
            tones=tones,
            fills=composite(drawing, only(*FILL_ROLES), box=box, notes=cnotes),
            details=composite(drawing, only("details"), box=box, notes=cnotes),
            lines=composite(drawing, only("line"), box=box, notes=cnotes),
            order=sorted(first, key=first.get),
            tone_above_lines=bool(above)))
    used_set = set(used)
    full = composite(drawing, lambda n: n in used_set, notes=cnotes)
    if not result or not full[..., 3].any():
        raise DrawingError("Nothing to vectorize: the layers with a role draw nothing visible (fully transparent, "
                           "0 % opacity, or clipped to an empty layer)")
    return Passes(drawing.width, drawing.height, result, full, False, notes + sorted(cnotes), frozenset(gradient_layers))
