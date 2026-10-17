import math

import pytest

from autoswf.model.geometry import Matrix, Point


def test_compose_applies_right_then_left():
    m = Matrix.translate(10, 0) @ Matrix.scale(2, 3)
    assert m.apply(Point(1, 1)) == Point(12, 3)


def test_rotate_quarter_turn():
    p = Matrix.rotate(math.pi / 2).apply(Point(1, 0))
    assert abs(p.x) < 1e-9 and abs(p.y - 1) < 1e-9


def test_inverse_undoes_a_matrix():
    m = Matrix(0.9, 0.1, -0.1, 0.9, 4.0, -114.0)
    p = (m.inverse() @ m).apply(Point(3, -7))
    assert abs(p.x - 3) < 1e-9 and abs(p.y + 7) < 1e-9
    with pytest.raises(ValueError, match="not invertible"):
        Matrix(0, 0, 0, 0).inverse()
