from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import (GradientFill, GradientStop, LineTo, Path, QuadTo, Shape, SolidFill, closed_contour,
                                 ellipse, translated)

SQUARE = [LineTo(10, 0), LineTo(10, 10), LineTo(0, 10), LineTo(0, 0)]


def test_clockwise_square_fills_right():
    p = closed_contour(0, Point(0, 0), SQUARE)
    assert (p.fill_left, p.fill_right) == (None, 0)


def test_counter_clockwise_square_fills_left():
    p = closed_contour(0, Point(0, 0), [LineTo(0, 10), LineTo(10, 10), LineTo(10, 0), LineTo(0, 0)])
    assert (p.fill_left, p.fill_right) == (0, None)


def test_ellipse_has_eight_quads_and_closes():
    p = ellipse(0, 50, 40, 20, 10)
    assert len(p.segments) == 8 and p.start == Point(70, 40)
    assert (round(p.segments[-1].x, 6), round(p.segments[-1].y, 6)) == (70, 40)


def test_translated_moves_points_controls_and_gradients():
    grad = GradientFill("linear", (GradientStop(0, (0, 0, 0, 255)), GradientStop(255, (255, 255, 255, 255))),
                        Matrix.scale(0.01, 0.01))
    s = Shape([SolidFill((1, 2, 3, 255)), grad], [Path(Point(1, 2), [LineTo(3, 4), QuadTo(5, 6, 7, 8)], 0, 1)])
    t = translated(s, -1, 10)
    assert t.paths[0].start == Point(0, 12) and t.paths[0].segments == [LineTo(2, 14), QuadTo(4, 16, 6, 18)]
    assert (t.paths[0].fill_left, t.paths[0].fill_right) == (0, 1)
    assert t.fills[0] is s.fills[0] and t.fills[1].matrix == Matrix(0.01, 0, 0, 0.01, -1, 10)
    assert s.paths[0].start == Point(1, 2)
