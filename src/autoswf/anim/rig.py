"""What the animation presets need to know about each part (spec §11): the layers its clip moves, the point it turns
about, its shape in head units (for Sway's chain) and, for an eye, its ball/lid/lash layers and how far its lid closes."""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from autoswf.model.document import Symbol
from autoswf.model.geometry import Point
from autoswf.model.shape import QuadTo, Shape

RIG_SCALE = 4.0                  # px per head unit of part masks
BLINK_CLOSE = 0.766              # official default head: the lid closes 7.2 of the 9.4 units of eye visible below it
LID_SPAN = 0.2                   # the lid's lowest point is measured within this fraction of the ball's width each side
TOP_ROWS = 0.1                   # back hair turns about the middle of the top tenth of its rows
CORNERS = ((0.0, 0.0), (-0.45, -0.45), (0.45, -0.45), (-0.45, 0.45), (0.45, 0.45))


@dataclass(eq=False)
class RigMask:
    pixels: np.ndarray           # bool, rows = y
    origin: Point                # head point of the top-left corner of pixel (0, 0)
    scale: float                 # px per head unit


@dataclass(frozen=True)
class EyeRig:
    ball: str                    # layer names: "Eye L ball", "Eye L lid", "Eye L lash"
    lid: str | None
    lash: str | None
    drop: float                  # head units the lid moves down to close the eye


@dataclass(eq=False)
class PartRig:
    name: str
    kind: str
    layers: list[str]            # what its clip moves: an eye's parent wrapper, else its top-level layers
    pivot: Point                 # head units: the point the part turns about
    tip: Point | None = None
    mask: RigMask | None = None
    eye: EyeRig | None = None


def part_of_layer(layer) -> str:
    """The part a layer belongs to: an eye's sub-layer belongs to its eye, "Lock 3 (Bangs)" to "Lock 3"."""
    if layer.parent:
        return layer.parent
    return layer.name.split(" (")[0]


def _mask(parts, name: str) -> RigMask | None:
    ys, xs = np.nonzero(parts.part_mask(name))
    if not len(xs):
        return None
    hx, hy = [], []
    for dx, dy in CORNERS:                       # pixel corners too, so drawings coarser than RIG_SCALE leave no gaps
        x, y = parts.graph.head(xs + dx, ys + dy)
        hx.append(x)
        hy.append(y)
    hx, hy = np.concatenate(hx), np.concatenate(hy)
    x0, y0 = np.floor(hx.min()) - 1, np.floor(hy.min()) - 1
    cols = ((hx - x0) * RIG_SCALE).astype(int)
    rows = ((hy - y0) * RIG_SCALE).astype(int)
    pixels = np.zeros((rows.max() + 3, cols.max() + 3), bool)
    pixels[rows, cols] = True
    pixels = ndimage.binary_fill_holes(ndimage.binary_closing(pixels, iterations=1))
    return RigMask(pixels, Point(float(x0), float(y0)), RIG_SCALE)


def _top(mask: RigMask) -> Point:
    rows = np.nonzero(mask.pixels.any(axis=1))[0]
    top = rows[0]
    band = mask.pixels[top:top + max(1, int(round(TOP_ROWS * (rows[-1] - top + 1))))]
    cols = np.nonzero(band.any(axis=0))[0]
    return Point(mask.origin.x + (cols.mean() + 0.5) / mask.scale, mask.origin.y + top / mask.scale)


def _points(symbol: Symbol) -> np.ndarray:
    """Every path point and curve control of a wrapper's shapes (its colorable clips' too), wrapper coordinates."""
    out = []

    def walk(s: Symbol) -> None:
        for p in s.frames[0].placements:
            if isinstance(p.item, Symbol):
                walk(p.item)
            elif isinstance(p.item, Shape):
                for path in p.item.paths:
                    out.append((path.start.x, path.start.y))
                    for seg in path.segments:
                        if isinstance(seg, QuadTo):
                            out.append((seg.cx, seg.cy))
                        out.append((seg.x, seg.y))
    walk(symbol)
    return np.array(out, float).reshape(-1, 2)


def _eye(name: str, layers: dict, helm) -> EyeRig | None:
    names = {piece: "%s %s" % (name, piece) for piece in ("ball", "lid", "lash")}
    found = {piece: n if n in helm.wrappers and n in layers else None for piece, n in names.items()}
    if found["ball"] is None:
        return None
    drop = 0.0
    ball = _points(helm.wrappers[found["ball"]]) + (layers[found["ball"]].pivot.x, layers[found["ball"]].pivot.y)
    if found["lid"] is not None and len(ball):
        lid = _points(helm.wrappers[found["lid"]]) + (layers[found["lid"]].pivot.x, layers[found["lid"]].pivot.y)
        if len(lid):
            cx, width = (ball[:, 0].min() + ball[:, 0].max()) / 2, ball[:, 0].max() - ball[:, 0].min()
            near = lid[np.abs(lid[:, 0] - cx) <= LID_SPAN * width]
            bottom = (near if len(near) else lid)[:, 1].max()
            drop = BLINK_CLOSE * max(0.0, float(ball[:, 1].max() - bottom))
    return EyeRig(found["ball"], found["lid"], found["lash"], drop)


def rig_parts(parts, helm, layers) -> dict:
    """PartRig per part that has a wrapper, in z order (`parts` a PartMap, `helm` an AssembledHelm, `layers` the
    PartLayers it was assembled from)."""
    by_part: dict[str, dict] = {}
    for layer in layers:
        by_part.setdefault(part_of_layer(layer), {})[layer.name] = layer
    out = {}
    for name, part in parts.parts.items():
        mine = by_part.get(name, {})
        if part.kind == "eye":
            if name not in helm.wrappers:
                continue
            m = helm.placements[name].matrix
            out[name] = PartRig(name, part.kind, [name], Point(m.tx, m.ty), mask=_mask(parts, name),
                                eye=_eye(name, mine, helm))
            continue
        tops = [n for n, layer in mine.items() if layer.parent is None and n in helm.wrappers]
        if not tops:
            continue
        main = mine[name] if name in mine else mine[tops[0]]
        mask = _mask(parts, name)
        pivot = _top(mask) if part.kind == "back_hair" and mask is not None else main.pivot
        out[name] = PartRig(name, part.kind, tops, pivot, part.tip, mask)
    return out
