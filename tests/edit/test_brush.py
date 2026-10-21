import math

import pytest

from editor_fixtures import height_at
from autoswf.edit.brush import Sample, stroke_area
from autoswf.edit.regions import area_px


def test_full_pressure_stroke_is_as_wide_as_the_size():
    a = stroke_area([Sample(0, 0), Sample(100, 0)], 10)
    assert area_px(a) == pytest.approx(100 * 10 + math.pi * 25, rel=0.02)


def test_pressure_tapers_the_ends():
    samples = [Sample(x, 0, p) for x, p in ((0, 0.0), (50, 1.0), (100, 0.0))]
    a = stroke_area(samples, 10)
    assert height_at(a, 0) == pytest.approx(10 * 0.15, abs=0.3) and height_at(a, 50) == pytest.approx(10, abs=0.3)


def test_mouse_stroke_ignores_pressure():
    a = stroke_area([Sample(0, 0, 0.0), Sample(100, 0, 0.0)], 10, use_pressure=False)
    assert height_at(a, 50) == pytest.approx(10, abs=0.3)


def test_a_click_without_drag_paints_a_dot():
    assert area_px(stroke_area([Sample(5, 5, 1.0)], 8)) == pytest.approx(math.pi * 16, rel=0.03)
