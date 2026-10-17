"""What the preview shows: the helm on the AQW male and female bodies, the game's labels, player colors and the
morph check (base-head pixels the helm leaves uncovered). Independent of any window, so it renders headless."""
import math
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor, QImage, QPainter

from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache
from autoswf.aqw.rig import AvatarRig
from autoswf.model.geometry import Matrix
from autoswf.render.colors import PlayerColors
from autoswf.render.effects import array_to_qimage, qimage_to_array
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import MorphShapeDef, MovieData, ShapeDef, SpriteDef

RGBA = tuple[int, int, int, int]
GENDERS = ("M", "F")
AVATAR_HEIGHT = 150.0           # skeleton units from the feet to above the head, used to fit the view
UNCOVERED_TINT = (255, 0, 0, 160)
MORPH_CHECK_SCALE, MORPH_CHECK_SIZE = 4.0, 600
MORPH_TOLERANCE_PX = 40         # uncovered base-head pixels (at the check's scale) still counted as covered


class MissingReferenceFiles(Exception):
    pass


def find_helm_link(movie: MovieData, file_name: str = "the file") -> str:
    """The only exported class that could be the helm: no package, not the back hair, and drawable."""
    candidates = [n for n, cid in movie.classes.items() if "." not in n and not n.endswith("_backhair")
                  and isinstance(movie.character(cid), (SpriteDef, ShapeDef, MorphShapeDef))]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError("Could not find the helm class in %s; pass --link NAME" % file_name)


class PreviewScene:
    def __init__(self, client: MovieData, armors: dict[str, MovieData | None], armor_link: str, *,
                 helm: MovieData | None = None, helm_link: str | None = None, colors: PlayerColors | None = None):
        self.client, self.armors, self.armor_link = client, armors, armor_link
        self.helm, self.helm_link = helm, helm_link
        self.colors = colors or PlayerColors()
        self.renderer = Renderer()
        self.label = "Idle"
        self._build()

    @classmethod
    def from_cache(cls, cache: AqwCache, helm_path: Path | None, *, link: str | None = None,
                   armor: str = DEFAULT_ARMOR) -> "PreviewScene":
        missing = cache.missing(armor)
        if missing:
            command = "python -m autoswf download-aqw" + ("" if armor == DEFAULT_ARMOR else " --armor %s" % armor)
            raise MissingReferenceFiles("AQW reference files are missing: %s. Run: %s" % (", ".join(missing), command))
        helm = MovieData(helm_path) if helm_path else None
        if helm is not None and link is None:
            link = find_helm_link(helm, Path(helm_path).name)
        armors = {g: MovieData(cache.armor_path(g, armor)) for g in GENDERS}
        return cls(MovieData(cache.client_path()), armors, armor, helm=helm, helm_link=link)

    def _build(self) -> None:
        wanted = self.label
        self.rigs = {g: AvatarRig(self.client, g, armor=self.armors.get(g), armor_link=self.armor_link,
                                  helm=self.helm, helm_link=self.helm_link, colors=self.colors) for g in GENDERS}
        self.labels = self.rigs["M"].labels
        self.label = self.rigs["M"].label
        if wanted != self.label and wanted in self.labels:
            self.set_label(wanted)

    def set_label(self, label: str) -> None:
        for rig in self.rigs.values():
            rig.set_label(label)
        self.label = label

    def set_color(self, location: str, rgb: int) -> None:
        self.colors = self.colors.replace(location, rgb)
        for rig in self.rigs.values():
            rig.colors = self.colors

    def set_helm(self, helm: MovieData | None, link: str | None) -> None:
        """Swap the helm; on failure the scene keeps showing the previous one."""
        previous = self.helm, self.helm_link
        self.helm, self.helm_link = helm, link
        try:
            self._build()
        except Exception:
            self.helm, self.helm_link = previous
            raise

    def tick(self) -> None:
        for rig in self.rigs.values():
            rig.tick()

    # ------------------------------------------------------------ drawing

    @staticmethod
    def default_zoom(height: int) -> float:
        return 0.8 * height / AVATAR_HEIGHT

    def view_matrix(self, gender: str, width: int, height: int, zoom: float, mirror: bool = False) -> Matrix:
        center = width / 4 + (width / 2 if gender == "F" else 0)
        return Matrix.translate(center, 0.88 * height) @ Matrix.scale(-zoom if mirror else zoom, zoom)

    def paint(self, painter: QPainter, width: int, height: int, *, zoom: float | None = None, mirror: bool = False,
              morph_check: bool = False, background: RGBA = (51, 51, 51, 255)) -> None:
        zoom = zoom or self.default_zoom(height)
        painter.fillRect(0, 0, width, height, QColor(*background))
        for g in GENDERS:
            view = self.view_matrix(g, width, height, zoom, mirror)
            self.renderer.draw(painter, self.rigs[g].skel, view, self.colors, filter_scale=zoom)
            if morph_check:
                mask, x0, y0 = self._uncovered(g, view @ self.rigs[g].skel.matrix, width, height)
                if mask.any():
                    tint = np.zeros(mask.shape + (4,), np.float32)
                    a = UNCOVERED_TINT[3] / 255
                    tint[mask] = (UNCOVERED_TINT[0] / 255 * a, UNCOVERED_TINT[1] / 255 * a, UNCOVERED_TINT[2] / 255 * a, a)
                    painter.drawImage(x0, y0, array_to_qimage(tint))

    def snapshot(self, width: int, height: int, **paint_options) -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(p, width, height, **paint_options)
        p.end()
        return image

    # ------------------------------------------------------------ morph check

    def _uncovered(self, gender: str, parent: Matrix, width: int, height: int) -> tuple[np.ndarray, int, int]:
        """Pixels where the base head is drawn and the helm is not, inside the base head's box: (mask, x, y).
        `parent` maps the skeleton's space to the image."""
        head = self.rigs[gender].head()
        matrix = parent @ head.matrix
        face, helm = head.child_by_name("face"), head.child_by_name("helm")
        bounds = object_bounds(face, matrix) if face is not None else None
        if bounds is None:
            return np.zeros((0, 0), bool), 0, 0
        x0, y0 = max(0, math.floor(bounds[0]) - 1), max(0, math.floor(bounds[2]) - 1)
        x1, y1 = min(width, math.ceil(bounds[1]) + 1), min(height, math.ceil(bounds[3]) + 1)
        if x1 <= x0 or y1 <= y0:
            return np.zeros((0, 0), bool), 0, 0
        shifted = Matrix.translate(-x0, -y0) @ matrix
        alphas = [qimage_to_array(self.renderer.render_image(part, x1 - x0, y1 - y0, shifted, None))[..., 3]
                  if part is not None else np.zeros((y1 - y0, x1 - x0), np.float32) for part in (face, helm)]
        return (alphas[0] >= 0.5) & (alphas[1] < 0.5), x0, y0

    def morph_check(self) -> dict[str, int]:
        """Base-head pixels the helm leaves uncovered, per gender (more than MORPH_TOLERANCE_PX means visible)."""
        return {g: self.uncovered_head_pixels(g) for g in GENDERS}

    def uncovered_head_pixels(self, gender: str) -> int:
        size, head = MORPH_CHECK_SIZE, self.rigs[gender].head()
        # the head's own placement is undone so the count does not depend on the pose
        a, b, c, d, tx, ty = head.matrix.a, head.matrix.b, head.matrix.c, head.matrix.d, head.matrix.tx, head.matrix.ty
        det = a * d - b * c or 1.0
        undo = Matrix(d / det, -b / det, -c / det, a / det, (c * ty - d * tx) / det, (b * tx - a * ty) / det)
        view = Matrix.translate(size / 2, size / 2) @ Matrix.scale(MORPH_CHECK_SCALE, MORPH_CHECK_SCALE) @ undo
        return int(self._uncovered(gender, view, size, size)[0].sum())
