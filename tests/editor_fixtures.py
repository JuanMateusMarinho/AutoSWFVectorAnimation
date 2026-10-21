"""Shapes, layers and files the editor tests share (Plan 7)."""
from autoswf.model.geometry import Point
from autoswf.model.shape import LineTo, Path, Shape, SolidFill


def square(x: float, y: float, size: float, fill: int, hole: bool = False) -> Path:
    """A square path, clockwise on screen; filled inside (or, as a hole, filled on its outside)."""
    segments = [LineTo(x + size, y), LineTo(x + size, y + size), LineTo(x, y + size), LineTo(x, y)]
    if hole:
        return Path(Point(x, y), segments, fill_left=fill)
    return Path(Point(x, y), segments, fill_right=fill)


def rect_path(x0: float, y0: float, x1: float, y1: float, fill: int) -> Path:
    return Path(Point(x0, y0), [LineTo(x1, y0), LineTo(x1, y1), LineTo(x0, y1), LineTo(x0, y0)], fill_right=fill)


def rect_area(x0: float, y0: float, x1: float, y1: float):
    """An Area (twips) of the rectangle x0..x1, y0..y1 (px)."""
    from autoswf.edit.regions import TWIPS
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [[(round(x * TWIPS), round(y * TWIPS)) for x, y in pts]]


BASE, SHADE = (230, 180, 140, 255), (40, 90, 200, 255)


def two_fills() -> Shape:
    """Fill 0 on 0..100 x 0..100 and fill 1 on 100..200 x 0..100, sharing the edge x = 100."""
    shared = Path(Point(100, 0), [LineTo(100, 100)], fill_left=1, fill_right=0)
    left = Path(Point(100, 100), [LineTo(0, 100), LineTo(0, 0), LineTo(100, 0)], fill_right=0)
    right = Path(Point(100, 0), [LineTo(200, 0), LineTo(200, 100), LineTo(100, 100)], fill_right=1)
    return Shape([SolidFill(BASE), SolidFill(SHADE)], [shared, left, right])


def painted_two_fills():
    """two_fills() with fill 1 painted into a notch of fill 0 (60..100 x 20..80): (shape, {0: shrunk, 1: grown})."""
    from autoswf.edit.regions import difference, fill_areas, union
    shape = two_fills()
    areas = fill_areas(shape)
    notch = rect_area(60, 20, 100, 80)
    return shape, {0: difference(areas[0], notch), 1: union(areas[1], notch)}


def background_pixels_inside(shape: Shape, scale: float) -> int:
    """Background pixels inside the union of the shape's fills, rendered at `scale` (a 1 px rim excluded)."""
    import numpy as np
    from PySide6.QtGui import QImage

    from swf_builders import swf
    from autoswf.edit.regions import bounds_px, fill_areas, offset, union
    from autoswf.model.geometry import Matrix
    from autoswf.render.display import instantiate
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    from autoswf.swf.shape_encoder import encode_define_shape4
    from autoswf.swf.sprite_encoder import tag

    obj = instantiate(MovieData(swf([tag(83, encode_define_shape4(shape, 1))])), 1)
    total = []
    for a in fill_areas(shape).values():
        total = union(total, a)
    x0, x1, y0, y1 = bounds_px(total)
    w, h = int((x1 - x0) * scale) + 4, int((y1 - y0) * scale) + 4
    view = Matrix.translate(2, 2) @ Matrix.scale(scale, scale) @ Matrix.translate(-x0, -y0)
    img = Renderer().render_image(obj, w, h, view, None).convertToFormat(QImage.Format.Format_RGBA8888)
    alpha = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(h, w, 4)[:, :, 3]
    inner = offset(total, -1.0 / scale)
    count = 0
    for yy in range(h):
        for xx in range(w):
            px, py = (xx + 0.5 - 2) / scale + x0, (yy + 0.5 - 2) / scale + y0
            if alpha[yy, xx] < 250 and _inside(inner, px, py):
                count += 1
    return count


def _inside(area, x: float, y: float) -> bool:
    from autoswf.edit.regions import contains
    return contains(area, x, y)
