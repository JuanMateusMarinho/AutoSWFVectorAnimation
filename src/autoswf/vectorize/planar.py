"""A label image traced into one vector Shape: one path per boundary chain, with the fill on each side (SWF
FillStyle0/1), so neighboring regions share their edges exactly."""
import numpy as np

from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import Fill, LineTo, Path, QuadTo, Shape
from autoswf.vectorize.fit import FitSettings, fit_chain
from autoswf.vectorize.trace import boundary_chains


def trace_shape(labels: np.ndarray, fills: list[Fill], settings: FitSettings, matrix: Matrix) -> Shape:
    """`fills[i]` is the fill of label i; -1 is empty. Points go through `matrix` (image px -> output px); a point
    shared by several chains is mapped once, so their ends stay identical after twips rounding."""
    mapped: dict[tuple[float, float], Point] = {}

    def place(x: float, y: float) -> Point:
        key = (x, y)
        if key not in mapped:
            mapped[key] = matrix.apply(Point(x, y))
        return mapped[key]

    paths = []
    for chain in boundary_chains(labels):
        start, segments = fit_chain(chain.points, chain.closed, settings)
        out = []
        for seg in segments:
            if seg[0] == "L":
                end = place(seg[1], seg[2])
                out.append(LineTo(end.x, end.y))
            else:
                control, end = matrix.apply(Point(seg[1], seg[2])), place(seg[3], seg[4])
                out.append(QuadTo(control.x, control.y, end.x, end.y))
        first = place(*start)
        paths.append(Path(first, out, fill_left=chain.left if chain.left >= 0 else None,
                          fill_right=chain.right if chain.right >= 0 else None))
    return Shape(list(fills), paths)
