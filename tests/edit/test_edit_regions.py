import pytest

from editor_fixtures import background_pixels_inside, painted_two_fills, rect_area, square
from autoswf.edit.regions import area_px, difference, fill_areas, rebuild_shape
from autoswf.model.shape import QuadTo, Shape, SolidFill, ellipse


def test_fill_areas_of_a_square_with_a_hole():
    shape = Shape([SolidFill((200, 150, 120, 255))], [square(0, 0, 100, fill=0), square(25, 25, 50, fill=0, hole=True)])
    assert area_px(fill_areas(shape)[0]) == pytest.approx(100 * 100 - 50 * 50)


def test_rebuild_without_changes_returns_the_same_segments():
    shape = Shape([SolidFill((1, 2, 3, 255))], [ellipse(0, 50, 50, 40, 30)])
    again = rebuild_shape(shape, fill_areas(shape))
    assert [p.segments for p in again.paths] == [p.segments for p in shape.paths]


def test_rebuild_after_a_cut_keeps_untouched_curves_exactly():
    shape = Shape([SolidFill((1, 2, 3, 255))], [ellipse(0, 0, 0, 100, 100)])
    cut = difference(fill_areas(shape)[0], rect_area(40, -200, 200, 400))      # keep x < 40
    out = rebuild_shape(shape, {0: cut})
    left = [s for s in shape.paths[0].segments if max(s.x, getattr(s, "cx", s.x)) < 35]
    kept = [s for p in out.paths for s in p.segments]
    assert len(left) == 4 and all(isinstance(s, QuadTo) for s in left)
    assert all(s in kept for s in left)                                        # identical QuadTo values
    assert area_px(fill_areas(out)[0]) == pytest.approx(area_px(cut), rel=0.002)


def test_neighbor_fills_share_their_edges_after_an_edit(qapp):
    shape, areas = painted_two_fills()
    out = rebuild_shape(shape, areas)
    edges = [(p.fill_left, p.fill_right) for p in out.paths]
    assert (0, 1) in edges or (1, 0) in edges                       # one shared edge, not two one-sided ones
    assert area_px(fill_areas(out)[1]) == pytest.approx(100 * 100 + 40 * 60)
    assert background_pixels_inside(out, scale=1) == 0 and background_pixels_inside(out, scale=2) == 0
