"""Composite a layer tree the way painting apps do: blend modes (W3C separable formulas), opacity, clipping to the
layer below, isolated and pass-through folders. Works in float32 premultiplied RGBA."""
from dataclasses import dataclass
from typing import Callable

import numpy as np

from autoswf.drawing.layers import BLEND_MODES, Drawing, LayerNode


def _hard_light(cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    return np.where(cs <= 0.5, cb * 2 * cs, 1 - (1 - cb) * (1 - (2 * cs - 1)))


def _soft_light(cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    d = np.where(cb <= 0.25, ((16 * cb - 12) * cb + 4) * cb, np.sqrt(cb))
    return np.where(cs <= 0.5, cb - (1 - 2 * cs) * cb * (1 - cb), cb + (2 * cs - 1) * (d - cb))


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a / np.where(b == 0, 1, b)


def blend(mode: str, cb: np.ndarray, cs: np.ndarray) -> np.ndarray:
    """B(Cb, Cs) for straight colors in 0..1."""
    cb, cs = np.asarray(cb, np.float64), np.asarray(cs, np.float64)
    if mode == "multiply":
        return cb * cs
    if mode == "screen":
        return cb + cs - cb * cs
    if mode == "overlay":
        return _hard_light(cs, cb)
    if mode == "darken":
        return np.minimum(cb, cs)
    if mode == "lighten":
        return np.maximum(cb, cs)
    if mode == "color_dodge":
        return np.where(cb == 0, 0, np.where(cs >= 1, 1, np.minimum(1, _safe_div(cb, 1 - cs))))
    if mode == "color_burn":
        return np.where(cb >= 1, 1, np.where(cs <= 0, 0, 1 - np.minimum(1, _safe_div(1 - cb, cs))))
    if mode == "hard_light":
        return _hard_light(cb, cs)
    if mode == "soft_light":
        return _soft_light(cb, cs)
    if mode == "difference":
        return np.abs(cb - cs)
    if mode == "exclusion":
        return cb + cs - 2 * cb * cs
    if mode == "add":
        return np.minimum(1, cb + cs)
    if mode == "linear_burn":
        return np.maximum(0, cb + cs - 1)
    if mode == "subtract":
        return np.maximum(0, cb - cs)
    if mode == "divide":
        return np.where(cs == 0, np.where(cb > 0, 1, 0), np.minimum(1, _safe_div(cb, cs)))
    return cs


def _straight(premult: np.ndarray) -> np.ndarray:
    a = premult[..., 3:4]
    return np.where(a > 0, premult[..., :3] / np.maximum(a, 1e-12), 0)


def _draw(dst: np.ndarray, color: np.ndarray, alpha: np.ndarray, mode: str) -> None:
    """Source-over with a blend mode: straight `color` (H x W x 3) at `alpha` (H x W) onto premultiplied `dst`."""
    a_s = alpha[..., None]
    a_b = dst[..., 3:4]
    if mode == "normal":
        mixed = color
    else:
        mixed = (1 - a_b) * color + a_b * blend(mode, _straight(dst), color)
    dst[..., :3] = a_s * mixed + (1 - a_s) * dst[..., :3]
    dst[..., 3:4] = a_s + a_b * (1 - a_s)


@dataclass
class _Context:
    x0: int
    y0: int
    include: Callable[[LayerNode], bool] | None
    force_normal: bool
    notes: set[str] | None

    def mode(self, node: LayerNode) -> str:
        if self.force_normal:
            return "normal"
        if node.blend in BLEND_MODES:
            return node.blend
        if self.notes is not None:
            self.notes.add("Blend mode '%s' of layer '%s' is drawn as normal" % (node.blend, node.name))
        return "normal"


def _place(node: LayerNode, dst: np.ndarray, ctx: _Context):
    """(slice of dst, the layer's straight RGBA 0..1 over that slice) or None when they do not overlap."""
    h, w = dst.shape[:2]
    lx, ly = node.left - ctx.x0, node.top - ctx.y0
    ph, pw = node.pixels.shape[:2]
    x0, y0, x1, y1 = max(0, lx), max(0, ly), min(w, lx + pw), min(h, ly + ph)
    if x1 <= x0 or y1 <= y0:
        return None
    region = (slice(y0, y1), slice(x0, x1))
    return region, node.pixels[y0 - ly:y1 - ly, x0 - lx:x1 - lx].astype(np.float32) / 255


def _draw_nodes(nodes: list[LayerNode], dst: np.ndarray, ctx: _Context) -> None:
    base_alpha = None              # pixel alpha of the current clipping base over dst (mask applied, no opacity)
    for node in nodes:
        if node.kind == "group":
            base_alpha = None
            if not node.visible:
                continue
            if node.blend == "pass_through":
                before = dst.copy() if node.opacity < 1 else None
                _draw_nodes(node.children, dst, ctx)
                if before is not None:
                    dst[:] = before + (dst - before) * node.opacity
            else:
                layer = np.zeros_like(dst)
                _draw_nodes(node.children, layer, ctx)
                _draw(dst, _straight(layer), layer[..., 3] * node.opacity, ctx.mode(node))
                base_alpha = layer[..., 3]
            continue
        if node.kind != "pixel":
            continue
        placed = _place(node, dst, ctx) if node.pixels is not None else None
        if not node.clipping:
            base_alpha = np.zeros(dst.shape[:2], np.float32)
            if placed is not None and node.visible:
                base_alpha[placed[0]] = placed[1][..., 3]
        if placed is None or not node.visible or (ctx.include is not None and not ctx.include(node)):
            continue
        region, rgba = placed
        alpha = rgba[..., 3] * node.opacity
        if node.clipping and base_alpha is not None:
            alpha = alpha * base_alpha[region]
        sub = dst[region]
        _draw(sub, rgba[..., :3], alpha, ctx.mode(node))
        dst[region] = sub


def composite(drawing: Drawing, include: Callable[[LayerNode], bool] | None = None, *, force_normal: bool = False,
              box: tuple[int, int, int, int] | None = None, notes: set[str] | None = None) -> np.ndarray:
    """The visible drawing (or the canvas rectangle `box` = (x0, y0, x1, y1)) as float32 premultiplied RGBA. Only pixel
    layers for which `include` is true draw; a clipping base that is left out still masks the layers clipped to it."""
    x0, y0, x1, y1 = box or (0, 0, drawing.width, drawing.height)
    out = np.zeros((max(0, y1 - y0), max(0, x1 - x0), 4), np.float32)
    _draw_nodes(drawing.layers, out, _Context(x0, y0, include, force_normal, notes))
    return out
