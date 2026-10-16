import math

from autoswf.model.geometry import Matrix, Point


def test_compose_applies_right_then_left():
    m = Matrix.translate(10, 0) @ Matrix.scale(2, 3)
    assert m.apply(Point(1, 1)) == Point(12, 3)


def test_rotate_quarter_turn():
    p = Matrix.rotate(math.pi / 2).apply(Point(1, 0))
    assert abs(p.x) < 1e-9 and abs(p.y - 1) < 1e-9
