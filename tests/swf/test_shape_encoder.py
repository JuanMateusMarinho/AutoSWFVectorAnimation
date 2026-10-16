from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import GradientFill, GradientStop, LineTo, Shape, SolidFill, closed_contour
from autoswf.swf.reader import parse_shape
from autoswf.swf.shape_encoder import encode_define_shape4


def square(size, fill=0):
    return closed_contour(fill, Point(0, 0), [LineTo(size, 0), LineTo(size, size), LineTo(0, size), LineTo(0, 0)])


def test_red_square_roundtrip():
    body = encode_define_shape4(Shape([SolidFill((255, 0, 0, 255))], [square(10)]), char_id=7)
    s = parse_shape(body, 0, len(body), 4)
    assert s["id"] == 7 and s["bounds"] == (0.0, 10.0, 0.0, 10.0)
    assert s["fills"] == [("solid", "#ff0000")] and s["edges"] == 4 and s["curves"] == 0


def test_huge_edge_is_split_and_bounds_kept():
    body = encode_define_shape4(Shape([SolidFill((0, 0, 0, 255))], [square(9000)]), char_id=1)
    s = parse_shape(body, 0, len(body), 4)
    assert s["bounds"] == (0.0, 9000.0, 0.0, 9000.0) and s["edges"] > 4


def test_empty_shape_is_valid():
    body = encode_define_shape4(Shape([], []), char_id=3)
    s = parse_shape(body, 0, len(body), 4)
    assert s["id"] == 3 and s["edges"] == 0 and s["bounds"] == (0.0, 0.0, 0.0, 0.0)


def test_gradient_fill_roundtrip():
    g = GradientFill("radial", (GradientStop(0, (255, 255, 255, 255)), GradientStop(255, (0, 238, 245, 0))),
                     Matrix.scale(0.05, 0.05))
    body = encode_define_shape4(Shape([g], [square(40)]), char_id=2)
    assert parse_shape(body, 0, len(body), 4)["fills"] == [("radial", [(0, "#ffffff"), (255, "#00eef5/a0")])]
