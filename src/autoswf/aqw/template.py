"""Head-local alignment of a drawing (spec §8) and the drawing template: a canvas with the AQW male and female heads,
rendered on the user's machine from the downloaded client, on locked guide layers, plus empty layers named after the
painting passes. Art drawn on the template aligns exactly; anything else is fitted to the head."""
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from autoswf.drawing.layers import Drawing
from autoswf.drawing.roles import GUIDE_PREFIX
from autoswf.drawing.writers import LayerSpec, write_clip, write_psd
from autoswf.model.geometry import Matrix, Point

TEMPLATE_SIZE = (2000, 2000)
TEMPLATE_SCALE = 10.0                          # px per head unit
TEMPLATE_ORIGIN = (1110.0, 1115.0)             # pixel of the head origin
HEAD_BOX = (-46.9, 29.4, -46.2, 43.3)          # xmin, xmax, ymin, ymax of mcHeadM ∪ mcHeadF (head units, 2026-10-16)
TEMPLATE_LAYERS = ("Flats", "Shadow", "Occlusion", "Light", "Details", "Line")
PASS_STYLES = {"Shadow": ("multiply", True), "Occlusion": ("multiply", True), "Light": ("screen", True)}


@dataclass(frozen=True)
class Alignment:
    scale: float                               # source px per head unit
    origin: tuple[float, float]                # source pixel of the head origin
    rotation: float = 0.0                      # degrees to turn the drawing clockwise onto the head (a drawing that
                                               # is itself turned clockwise needs a negative value)

    def matrix(self) -> Matrix:
        """Source px -> head-local px."""
        ox, oy = self.origin
        return (Matrix.rotate(math.radians(self.rotation)) @ Matrix.scale(1 / self.scale, 1 / self.scale)
                @ Matrix.translate(-ox, -oy))

    @classmethod
    def parse(cls, text: str) -> "Alignment":
        try:
            values = [float(v) for v in text.split(",")]
        except ValueError:
            values = []
        if len(values) not in (3, 4) or not all(map(math.isfinite, values)) or values[0] <= 0:
            raise ValueError("Alignment must look like SCALE,X,Y or SCALE,X,Y,DEGREES")
        return cls(values[0], (values[1], values[2]), values[3] if len(values) == 4 else 0.0)

    def __str__(self) -> str:
        return ",".join("%g" % v for v in (self.scale, *self.origin, self.rotation))


def alignment_from_matrix(m: Matrix) -> Alignment:
    """The alignment whose matrix (drawing px -> head units) is `m` (the inverse of Alignment.matrix)."""
    scale = 1 / math.hypot(m.a, m.b)
    origin = m.inverse().apply(Point(0, 0))
    return Alignment(scale, (origin.x, origin.y), math.degrees(math.atan2(m.b, m.a)))


def alignment_text(alignment: Alignment) -> str:
    """SCALE,X,Y,DEGREES at full precision (str() rounds to 6 digits)."""
    return ",".join(format(float(v), ".17g") for v in (alignment.scale, *alignment.origin, alignment.rotation))


def template_alignment() -> Alignment:
    return Alignment(TEMPLATE_SCALE, TEMPLATE_ORIGIN)


def is_template(drawing: Drawing) -> bool:
    guide = GUIDE_PREFIX.casefold()
    return ((drawing.width, drawing.height) == TEMPLATE_SIZE
            and any(n.name.strip().casefold().startswith(guide) for n, _ in drawing.walk()))


def fit_alignment(bbox: tuple[float, float, float, float]) -> Alignment:
    """The art's box (x0, x1, y0, y1 in source px) onto the head box: centers together, heights equal."""
    x0, x1, y0, y1 = bbox
    hx0, hx1, hy0, hy1 = HEAD_BOX
    scale = (y1 - y0) / (hy1 - hy0) if y1 > y0 else (x1 - x0) / (hx1 - hx0) if x1 > x0 else 1.0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return Alignment(scale, (cx - (hx0 + hx1) / 2 * scale, cy - (hy0 + hy1) / 2 * scale))


def choose_alignment(drawing: Drawing, content_bbox: tuple[float, float, float, float],
                     override: Alignment | None) -> tuple[Alignment, str]:
    if override is not None:
        return override, "set with --align"
    if is_template(drawing):
        return template_alignment(), "AutoSWF template"
    return fit_alignment(content_bbox), "fitted to the AQW head (not drawn on the AutoSWF template)"


def _guide(client, gender: str) -> np.ndarray:
    from PySide6.QtGui import QGuiApplication
    from autoswf.render.colors import PlayerColors
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    QGuiApplication.instance() or QGuiApplication([])
    char_id = client.classes.get("mcHead" + gender)
    head = instantiate(client, char_id) if char_id is not None else None
    if head is None:
        raise ValueError("The AQW client has no mcHead%s class" % gender)
    colors = PlayerColors()
    run_pending_actions(head, ScriptContext(colors))
    view = Matrix.translate(*TEMPLATE_ORIGIN) @ Matrix.scale(TEMPLATE_SCALE, TEMPLATE_SCALE)
    image = qimage_to_array(Renderer(cache_bytes=0).render_image(head, *TEMPLATE_SIZE, view, colors))
    a = image[..., 3:4]
    straight = np.where(a > 0, image[..., :3] / np.maximum(a, 1e-12), 0)
    return np.round(np.dstack([straight, a]) * 255).astype(np.uint8)


def write_template(client, out: Path, *, clip: Path | None = None) -> None:
    """`client` is the AQW client MovieData (from the local cache). Writes the PSD template and, when asked, a .clip."""
    w, h = TEMPLATE_SIZE
    empty = np.zeros((h, w, 4), np.uint8)
    layers = [LayerSpec("AQW Guide Head F", _guide(client, "F"), visible=False, locked=True),
              LayerSpec("AQW Guide Head M", _guide(client, "M"), locked=True)]
    for name in TEMPLATE_LAYERS:
        blend, clipping = PASS_STYLES.get(name, ("normal", False))
        layers.append(LayerSpec(name, empty, blend=blend, clipping=clipping))
    write_psd(out, w, h, layers)
    if clip is not None:
        write_clip(clip, w, h, layers)
