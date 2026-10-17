"""An overview image of the parts found in a drawing, to check the detection and to pick points for corrections."""
import colorsys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from autoswf.drawing.passes import Passes
from autoswf.parts.detect import PartMap

BACKGROUND = (40, 40, 40)
DRAWING_WEIGHT = 0.35


def _tint(k: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((k * 0.618034) % 1.0, 0.65, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def parts_image(passes: Passes, parts: PartMap) -> Image.Image:
    """Drawing-sized RGBA: the drawing faded over dark gray, each part tinted, its name at its label point."""
    full = passes.full.astype(np.float32)
    a = full[..., 3:4]
    straight = np.where(a > 0, full[..., :3] / np.maximum(a, 1e-9), 0) * 255
    base = np.asarray(BACKGROUND, np.float32) * (1 - a) + straight * a
    out = base * DRAWING_WEIGHT + np.asarray(BACKGROUND, np.float32) * (1 - DRAWING_WEIGHT)
    for k, name in enumerate(parts.parts):
        mask = parts.part_mask(name)
        out[mask] = out[mask] * 0.45 + np.asarray(_tint(k), np.float32) * 0.55
    image = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for name in parts.parts:
        x, y = parts.label_point(name)
        box = draw.textbbox((x, y), name, font=font, anchor="mm")
        draw.rectangle(box, fill=(0, 0, 0, 200))
        draw.text((x, y), name, fill=(255, 255, 255, 255), font=font, anchor="mm")
    return image
