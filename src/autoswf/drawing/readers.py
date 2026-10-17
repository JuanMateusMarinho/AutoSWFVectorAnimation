"""Open a drawing file as a layer tree: Clip Studio Paint (.clip, via clipparse), Photoshop (.psd, via psd-tools) or a
flattened PNG."""
from pathlib import Path

import numpy as np

from autoswf.drawing.layers import CLIP_BLEND, PSD_BLEND, Drawing, DrawingError, LayerNode

SUFFIXES = {".clip": "clip", ".psd": "psd", ".psb": "psd", ".png": "png"}


def _no_pixels_note(name: str) -> str:
    return "Layer '%s' has no pixels AutoSWF can use (text, adjustment or vector layer); it is skipped" % name


def read_drawing(path: str | Path) -> Drawing:
    path = Path(path)
    kind = SUFFIXES.get(path.suffix.lower())
    if kind is None:
        raise DrawingError("Unsupported file type '%s'; AutoSWF opens .clip, .psd and .png files" % path.suffix)
    try:
        return {"clip": _read_clip, "psd": _read_psd, "png": _read_png}[kind](path)
    except DrawingError:
        raise
    except Exception as e:      # the libraries raise many kinds of errors on damaged files
        raise DrawingError("Could not read %s: %s" % (path.name, e or type(e).__name__)) from e


# ---------------------------------------------------------------- PSD

def _psd_mask(layer, width: int, height: int) -> np.ndarray | None:
    """The layer mask over the layer's own box (0..1), or None when there is no active mask."""
    mask = getattr(layer, "mask", None)
    if mask is None or getattr(mask, "disabled", False):
        return None
    image = mask.topil()
    out = np.full((height, width), mask.background_color / 255.0, np.float32)
    if image is None:
        return out
    m = np.asarray(image.convert("L"), np.float32) / 255
    mx0, my0 = mask.left - layer.left, mask.top - layer.top
    x0, y0 = max(0, mx0), max(0, my0)
    x1, y1 = min(width, mx0 + m.shape[1]), min(height, my0 + m.shape[0])
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = m[y0 - my0:y1 - my0, x0 - mx0:x1 - mx0]
    return out


def _psd_node(layer, notes: list[str]) -> LayerNode:
    common = dict(visible=bool(layer.visible), opacity=layer.opacity / 255,
                  blend=PSD_BLEND.get(layer.blend_mode.name, "normal"))
    if layer.is_group():
        node = LayerNode(layer.name, "group", **common)
        node.children = [_psd_node(child, notes) for child in layer]
        return node
    image = layer.topil() if layer.kind != "adjustment" and layer.has_pixels() else None
    if image is None:
        notes.append(_no_pixels_note(layer.name))
        return LayerNode(layer.name, "other", **common)
    rgba = np.asarray(image.convert("RGBA")).copy()
    mask = _psd_mask(layer, rgba.shape[1], rgba.shape[0])
    if mask is not None:
        rgba[..., 3] = np.round(rgba[..., 3] * mask).astype(np.uint8)
    common["opacity"] *= getattr(layer, "fill_opacity", 255) / 255
    return LayerNode.from_canvas(layer.name, rgba, layer.left, layer.top, clipping=bool(layer.clipping), **common)


def _read_psd(path: Path) -> Drawing:
    from psd_tools import PSDImage
    psd = PSDImage.open(path)
    notes: list[str] = []
    layers = [_psd_node(layer, notes) for layer in psd]
    return Drawing(path, psd.width, psd.height, layers, notes)


# ---------------------------------------------------------------- CLIP

def _clip_node(clip, index: int, notes: list[str]) -> LayerNode:
    info = clip.layers[index]
    common = dict(visible=bool(info.visible), opacity=info.opacity / 255,
                  blend=CLIP_BLEND.get(info.composite_raw, "normal"))
    if info.is_group:
        node = LayerNode(info.name, "group", **common)
        node.children = [_clip_node(clip, i, notes) for i in info.children]
        return node
    if info.is_filter or info.is_text:
        notes.append(_no_pixels_note(info.name))
        return LayerNode(info.name, "other", **common)
    raw = clip.layer_image(index, "masked")
    rgba = None
    if raw and info.width > 0 and info.height > 0:
        rgba = np.frombuffer(raw, np.uint8).reshape(info.height, info.width, 4)[..., [2, 1, 0, 3]]
    return LayerNode.from_canvas(info.name, rgba, info.left, info.top, clipping=bool(info.clipping), **common)


def _read_clip(path: Path) -> Drawing:
    import clipparse
    clip = clipparse.ClipFile()
    if not clip.load(str(path)):
        raise DrawingError("Could not read %s: %s" % (path.name, clip.error or "not a Clip Studio Paint file"))
    notes: list[str] = []
    layers = [_clip_node(clip, i, notes) for i in clip.roots]
    return Drawing(path, clip.width, clip.height, layers, notes)


# ---------------------------------------------------------------- PNG

def _read_png(path: Path) -> Drawing:
    from PIL import Image
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"))
    return Drawing(path, rgba.shape[1], rgba.shape[0], [LayerNode.from_canvas(path.stem, rgba)], flattened=True)
