from autoswf.model.geometry import Point
from autoswf.model.shape import LineTo, closed_contour, ellipse

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
