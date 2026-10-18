"""Rendering helpers for exported (and animated) helms in tests: the helm on the drawing's canvas at some frame."""
import numpy as np

from autoswf.model.geometry import Matrix


def render_helm(swf: bytes, link: str, t, colors, frame: int = 0, hide=()) -> np.ndarray:
    """Straight (not premultiplied) RGBA 0-255 floats of class `link` after `frame` ticks, on t's canvas; children whose
    instance name is in `hide` are hidden."""
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions, tick
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    movie = MovieData(swf)
    obj = instantiate(movie, movie.classes[link])
    ctx = ScriptContext(colors)
    run_pending_actions(obj, ctx)
    for _ in range(frame):
        tick(obj, ctx)

    def walk(clip):
        for child in getattr(clip, "children", []):
            if child.name in hide:
                child.visible = False
            walk(child)
    walk(obj)
    view = Matrix.translate(*t.alignment.origin) @ Matrix.scale(t.alignment.scale, t.alignment.scale)
    img = qimage_to_array(Renderer(cache_bytes=0).render_image(obj, t.width, t.height, view, colors))
    a = img[..., 3:4]
    return np.dstack([np.where(a > 0, img[..., :3] / np.maximum(a, 1e-9), 0) * 255, a[..., 0] * 255])


def at(img: np.ndarray, t, x: float, y: float) -> tuple:
    """The pixel at head point (x, y)."""
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    return tuple(int(round(v)) for v in img[int(oy + y * s), int(ox + x * s)])


def near(got, want, tol: int = 3) -> bool:
    return max(abs(g - w) for g, w in zip(got[:3], want)) <= tol
