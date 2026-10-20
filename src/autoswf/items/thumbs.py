"""Thumbnails of an item's pieces for the Open SWF tree: each character rendered alone, fitted and centered."""
from PySide6.QtGui import QImage, QPainter

from autoswf.model.geometry import Matrix
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import MovieData

PADDING = 2


def piece_image(movie: MovieData, char_id: int, size: int = 48, colors: PlayerColors | None = None,
                renderer: Renderer | None = None) -> QImage:
    """`size` x `size`, transparent, the character fitted inside (colorable clips in the player's colors)."""
    colors = colors or PlayerColors()
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    obj = instantiate(movie, char_id)
    if obj is None:
        return image
    run_pending_actions(obj, ScriptContext(colors))
    bounds = object_bounds(obj, Matrix())
    if bounds is None:
        return image
    x0, x1, y0, y1 = bounds
    w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    scale = min((size - 2 * PADDING) / w, (size - 2 * PADDING) / h)
    matrix = (Matrix.translate(size / 2, size / 2) @ Matrix.scale(scale, scale)
              @ Matrix.translate(-(x0 + x1) / 2, -(y0 + y1) / 2))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    (renderer or Renderer()).draw(painter, obj, matrix, colors, filter_scale=scale)
    painter.end()
    return image
