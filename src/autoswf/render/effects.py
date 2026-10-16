"""Filters (on premultiplied RGBA float arrays) and blend modes for offscreen layers. Approximations of Flash:
box blurs repeated `passes` times, glows and shadows built from the blurred alpha, a 4x5 color matrix."""
import math

import numpy as np
from PySide6.QtGui import QImage, QPainter

from autoswf.swf.decode import BlurFilter, ColorMatrixFilter, DropShadowFilter, Filter, GlowFilter, UnsupportedFilter

ARGB = QImage.Format.Format_ARGB32_Premultiplied
_CM = QPainter.CompositionMode
BLEND_MODES = {
    "normal": _CM.CompositionMode_SourceOver, "layer": _CM.CompositionMode_SourceOver,
    "multiply": _CM.CompositionMode_Multiply, "screen": _CM.CompositionMode_Screen,
    "lighten": _CM.CompositionMode_Lighten, "darken": _CM.CompositionMode_Darken,
    "difference": _CM.CompositionMode_Difference, "overlay": _CM.CompositionMode_Overlay,
    "hardlight": _CM.CompositionMode_HardLight, "add": _CM.CompositionMode_Plus,
    "subtract": _CM.CompositionMode_Difference, "invert": _CM.CompositionMode_Difference,
    "alpha": _CM.CompositionMode_DestinationIn, "erase": _CM.CompositionMode_DestinationOut,
}
APPROXIMATED_BLENDS = {"subtract", "invert", "alpha", "erase"}


def blend_note(name: str | None) -> str | None:
    return "Blend mode '%s' is approximated" % name if name in APPROXIMATED_BLENDS else None


def qimage_to_array(img: QImage) -> np.ndarray:
    """H x W x 4 float32 premultiplied RGBA in 0..1."""
    if img.format() != ARGB:
        img = img.convertToFormat(ARGB)
    h, w = img.height(), img.width()
    raw = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine())
    bgra = raw[:, :w * 4].reshape(h, w, 4)
    return bgra[..., [2, 1, 0, 3]].astype(np.float32) / 255


def array_to_qimage(arr: np.ndarray) -> QImage:
    data = np.ascontiguousarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8)[..., [2, 1, 0, 3]])
    h, w = data.shape[:2]
    return QImage(data.data, w, h, w * 4, ARGB).copy()


def _box(a: np.ndarray, width: int, axis: int) -> np.ndarray:
    """Moving average over `width` samples centered on each sample (zeros outside)."""
    if width <= 1:
        return a
    before = width // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (before + 1, width - 1 - before)
    c = np.cumsum(np.pad(a, pad), axis=axis, dtype=np.float32)
    n = a.shape[axis]
    return (np.take(c, np.arange(width, width + n), axis=axis) - np.take(c, np.arange(n), axis=axis)) / width


def blur(a: np.ndarray, blur_x: float, blur_y: float, passes: int, scale: float) -> np.ndarray:
    wx, wy = round(blur_x * scale), round(blur_y * scale)
    for _ in range(passes):
        a = _box(_box(a, wx, 1), wy, 0)
    return a


def _shift(a: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    if abs(dx) >= w or abs(dy) >= h:
        return out
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = a[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def _glow(arr: np.ndarray, color, blur_x: float, blur_y: float, strength: float, inner: bool, knockout: bool,
          passes: int, scale: float, offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    alpha = arr[..., 3]
    amount = blur((1 - alpha if inner else alpha)[..., None], blur_x, blur_y, passes, scale)[..., 0]
    amount = _shift(np.clip(amount * strength, 0, 1), *offset)
    rgb = np.array(color[:3], np.float32) / 255
    glow_alpha = amount * (color[3] / 255)
    if inner:
        glow_alpha = glow_alpha * alpha
        if knockout:
            return np.concatenate([rgb * glow_alpha[..., None], glow_alpha[..., None]], axis=-1)
        out = arr.copy()
        out[..., :3] = arr[..., :3] * (1 - glow_alpha[..., None]) + rgb * glow_alpha[..., None]
        return out
    glow = np.concatenate([rgb * glow_alpha[..., None], glow_alpha[..., None]], axis=-1)
    if knockout:
        return glow * (1 - alpha[..., None])
    return arr + glow * (1 - alpha[..., None])


def _color_matrix(arr: np.ndarray, matrix: tuple[float, ...]) -> np.ndarray:
    m = np.array(matrix, np.float32).reshape(4, 5)
    alpha = arr[..., 3:4]
    straight = np.concatenate([np.divide(arr[..., :3], alpha, out=np.zeros_like(arr[..., :3]), where=alpha > 0), alpha], -1)
    out = np.clip(straight @ m[:, :4].T + m[:, 4] / 255, 0, 1)
    out[..., :3] *= out[..., 3:4]
    return out


def filter_padding(filters: tuple[Filter, ...], scale: float) -> float:
    """How far (device px) the filters can spread beyond the object's bounds."""
    pad = 0.0
    for f in filters:
        if isinstance(f, (BlurFilter, GlowFilter, DropShadowFilter)):
            pad = max(pad, (max(f.blur_x, f.blur_y) * 2 + getattr(f, "distance", 0)) * scale)
    return pad + 2


def apply_filters(arr: np.ndarray, filters: tuple[Filter, ...], scale: float) -> tuple[np.ndarray, list[str]]:
    notes = []
    for f in filters:
        if isinstance(f, BlurFilter):
            arr = blur(arr, f.blur_x, f.blur_y, f.passes, scale)
        elif isinstance(f, GlowFilter):
            arr = _glow(arr, f.color, f.blur_x, f.blur_y, f.strength, f.inner, f.knockout, f.passes, scale)
        elif isinstance(f, DropShadowFilter):
            offset = (round(f.distance * math.cos(f.angle) * scale), round(f.distance * math.sin(f.angle) * scale))
            arr = _glow(arr, f.color, f.blur_x, f.blur_y, f.strength, f.inner, f.knockout, f.passes, scale, offset)
        elif isinstance(f, ColorMatrixFilter):
            arr = _color_matrix(arr, f.matrix)
        elif isinstance(f, UnsupportedFilter):
            notes.append("%s filter is not rendered" % f.name)
    return arr, notes
