"""A layered drawing as one tree of layers, whatever file it came from (CLIP, PSD or PNG)."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal

import numpy as np

BLEND_MODES = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "color_dodge", "color_burn",
               "linear_burn", "hard_light", "soft_light", "difference", "exclusion", "add", "subtract", "divide",
               "pass_through")
APPROXIMATED_BLENDS = ("hue", "saturation", "color", "luminosity", "vivid_light", "linear_light", "pin_light",
                       "hard_mix", "darker_color", "lighter_color", "glow_dodge")

# Clip Studio Paint's LayerComposite codes (identified by clipparse, docs/CLIP_FORMAT.md §9)
CLIP_BLEND = {0: "normal", 1: "darken", 2: "multiply", 3: "color_burn", 4: "linear_burn", 5: "subtract",
              6: "darker_color", 7: "lighten", 8: "screen", 9: "color_dodge", 10: "glow_dodge", 11: "add", 12: "add",
              13: "lighter_color", 14: "overlay", 15: "soft_light", 16: "hard_light", 17: "vivid_light",
              18: "linear_light", 19: "pin_light", 20: "hard_mix", 21: "difference", 22: "exclusion", 23: "hue",
              24: "saturation", 25: "color", 26: "luminosity", 30: "pass_through", 36: "divide"}

# psd-tools BlendMode member names
PSD_BLEND = {"PASS_THROUGH": "pass_through", "NORMAL": "normal", "DISSOLVE": "normal", "DARKEN": "darken",
             "MULTIPLY": "multiply", "COLOR_BURN": "color_burn", "LINEAR_BURN": "linear_burn",
             "DARKER_COLOR": "darker_color", "LIGHTEN": "lighten", "SCREEN": "screen", "COLOR_DODGE": "color_dodge",
             "LINEAR_DODGE": "add", "LIGHTER_COLOR": "lighter_color", "OVERLAY": "overlay", "SOFT_LIGHT": "soft_light",
             "HARD_LIGHT": "hard_light", "VIVID_LIGHT": "vivid_light", "LINEAR_LIGHT": "linear_light",
             "PIN_LIGHT": "pin_light", "HARD_MIX": "hard_mix", "DIFFERENCE": "difference", "EXCLUSION": "exclusion",
             "SUBTRACT": "subtract", "DIVIDE": "divide", "HUE": "hue", "SATURATION": "saturation", "COLOR": "color",
             "LUMINOSITY": "luminosity"}


class DrawingError(Exception):
    pass


@dataclass(eq=False)
class LayerNode:
    name: str
    kind: Literal["pixel", "group", "other"]
    visible: bool = True
    opacity: float = 1.0                 # 0..1
    blend: str = "normal"
    clipping: bool = False               # clipped to the nearest non-clipped layer below it
    left: int = 0
    top: int = 0
    pixels: np.ndarray | None = None     # H x W x 4 uint8 straight RGBA of the layer's non-transparent box
    children: list["LayerNode"] = field(default_factory=list)     # bottom to top

    @classmethod
    def from_canvas(cls, name: str, rgba: np.ndarray | None, left: int = 0, top: int = 0, **fields) -> "LayerNode":
        """A pixel layer from an RGBA array placed at (left, top), cropped to its non-transparent pixels."""
        node = cls(name, "pixel", **fields)
        if rgba is None:
            return node
        ys, xs = np.nonzero(rgba[..., 3])
        if len(xs):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            node.left, node.top = left + int(x0), top + int(y0)
            node.pixels = np.ascontiguousarray(rgba[y0:y1, x0:x1], dtype=np.uint8)
        return node


@dataclass(eq=False)
class Drawing:
    path: Path | None
    width: int
    height: int
    layers: list[LayerNode]              # top level, bottom to top
    notes: list[str] = field(default_factory=list)
    flattened: bool = False

    def walk(self) -> Iterator[tuple[LayerNode, tuple[LayerNode, ...]]]:
        """Every node, depth first and bottom to top (a folder before its contents), with its ancestor folders."""
        def visit(nodes, ancestors):
            for node in nodes:
                yield node, ancestors
                if node.kind == "group":
                    yield from visit(node.children, ancestors + (node,))
        yield from visit(self.layers, ())
