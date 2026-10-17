"""Layered test drawings: small canvas helpers and in-memory drawings built from LayerSpecs."""
import numpy as np

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
