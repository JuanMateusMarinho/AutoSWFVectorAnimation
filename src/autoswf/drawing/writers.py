"""Write layered drawings: PSD (psd-tools) and Clip Studio Paint .clip (clipparse, experimental: clipparse checks the
file's structure, but files it writes are not yet confirmed to open in Clip Studio Paint). Used for drawing templates
and test drawings."""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from autoswf.drawing.layers import CLIP_BLEND, PSD_BLEND, DrawingError

CLIP_TEMPLATE_LAYER, CLIP_TEMPLATE_PAPER = 3, 4      # main ids in clipparse's bundled emptyimage.clip


@dataclass
class LayerSpec:
    name: str
    pixels: np.ndarray | None = None     # canvas-sized uint8 straight RGBA; None = folder
    blend: str = "normal"
    opacity: float = 1.0
    clipping: bool = False
    visible: bool = True
    locked: bool = False
    children: list["LayerSpec"] = field(default_factory=list)


def _psd_blend_name(blend: str) -> str:
    names = {ours: theirs for theirs, ours in PSD_BLEND.items() if theirs != "DISSOLVE"}
    names["glow_dodge"] = "COLOR_DODGE"
    return names.get(blend, "NORMAL")


def write_psd(path, width: int, height: int, layers: list[LayerSpec]) -> None:
    from PIL import Image
    from psd_tools import PSDImage
    from psd_tools.api.layers import Group, PixelLayer
    from psd_tools.constants import BlendMode, ProtectedFlags, Tag
    from psd_tools.psd.tagged_blocks import ProtectedSetting

    def add(parent, spec: LayerSpec) -> None:
        if spec.pixels is None:
            layer = Group.new(parent, name=spec.name)
        else:
            layer = PixelLayer.frompil(Image.fromarray(np.ascontiguousarray(spec.pixels, np.uint8), "RGBA"), parent,
                                       name=spec.name)
            layer.clipping = spec.clipping
        layer.blend_mode = BlendMode[_psd_blend_name(spec.blend)]
        layer.opacity = round(spec.opacity * 255)
        layer.visible = spec.visible
        if spec.locked:
            layer.tagged_blocks.set_data(Tag.PROTECTED_SETTING, ProtectedSetting(int(ProtectedFlags.COMPLETE)))
        for child in spec.children:
            add(layer, child)

    psd = PSDImage.new("RGBA", (width, height))
    for spec in layers:
        add(psd, spec)
    psd.save(str(path))


def _clip_template() -> str:
    import clipparse_tools
    return str(Path(clipparse_tools.__file__).parent / "data" / "emptyimage.clip")


def _preview(width: int, height: int, layers: list[LayerSpec]) -> np.ndarray:
    """A plain normal-blend flattening on white (BGRA), shown by Clip Studio Paint until the canvas is redrawn."""
    out = np.ones((height, width, 3), np.float32)

    def paint(specs):
        for spec in specs:
            if not spec.visible:
                continue
            if spec.pixels is None:
                paint(spec.children)
            elif spec.blend == "normal" and not spec.clipping:
                a = spec.pixels[..., 3:4].astype(np.float32) / 255 * spec.opacity
                out[:] = spec.pixels[..., :3] / 255 * a + out * (1 - a)

    paint(layers)
    rgb = np.round(out * 255).astype(np.uint8)
    return np.ascontiguousarray(np.dstack([rgb[..., ::-1], np.full((height, width), 255, np.uint8)]))


def write_clip(path, width: int, height: int, layers: list[LayerSpec]) -> None:
    import clipparse
    codes = {}
    for code, name in CLIP_BLEND.items():
        codes.setdefault(name, code)
    writer = clipparse.ClipWriter()
    writer.set_external_id_seed(20261016)
    if not writer.load(_clip_template()) or not writer.resize_canvas(width, height, 0.0):
        raise DrawingError("Could not start a Clip Studio Paint file from clipparse's template")

    def add(spec: LayerSpec, after: int, parent: int) -> int:
        if spec.pixels is None:
            main_id = writer.add_layer(CLIP_TEMPLATE_LAYER, spec.name, None, 0, 0, after, parent)
            writer.set_layer_attr(main_id, folder=1)
            child_after = -1
            for child in spec.children:
                child_after = add(child, child_after, main_id)
        else:
            bgra = np.ascontiguousarray(spec.pixels[..., [2, 1, 0, 3]], np.uint8)
            main_id = writer.add_layer(CLIP_TEMPLATE_LAYER, spec.name, bgra, width, height, after, parent)
        writer.set_layer_attr(main_id, opacity=round(spec.opacity * 256), visible=int(spec.visible),
                              composite=codes.get(spec.blend, 0), clipping=int(spec.clipping))
        return main_id

    after = -1
    for spec in layers:
        after = add(spec, after, 0)
    writer.set_layer_attr(CLIP_TEMPLATE_PAPER, name="Paper")
    writer.delete_layer(CLIP_TEMPLATE_LAYER)
    writer.set_canvas_preview(_preview(width, height, layers), width, height)
    writer.save(str(path))
    problems = clipparse.validate(str(path))
    if problems:
        raise DrawingError("The Clip Studio Paint file %s failed clipparse's check: %s" % (Path(path).name, "; ".join(problems)))
