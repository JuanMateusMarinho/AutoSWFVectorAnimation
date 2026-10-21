import math
import time

import pytest

from editor_fixtures import (CORRECT_EDGE, CORRECT_EDGE_SHORT_BY_2PX, CORRECT_EDGE_SHORT_BY_8PX, LINE_RGBA,
                             RIGHT_OF_EDGE_BOX, SHADOW_BOX, STRIP_CENTER, busy_layer, face_with_strip, long_stroke,
                             polygon_area, rect_area, shape_of, strip_constants)
from autoswf.edit.brush import stroke_area
from autoswf.edit.layer import (NEW_FIXED_COLOR, ONLY_COLORED, Drawing, EditLayer, Selection, Tone, ToneRef)
from autoswf.edit.regions import area_px, fill_areas, intersection
from autoswf.model.geometry import Matrix

SKIN_BASE, SHADOW, LINE = ToneRef("skin", 0), ToneRef("shadow", 0), ToneRef("line", 0)
STRIP_AREA, FACE_AREA = strip_constants()


def brushed(edge=CORRECT_EDGE):
    layer = face_with_strip()
    return layer.applied(layer.paint(stroke_area(edge, 3), layer.line_tone))


def test_the_three_step_fix_removes_the_strip_and_its_outline():
    layer = brushed()
    sel = layer.wand(*STRIP_CENTER)
    assert area_px(sel.area) == pytest.approx(STRIP_AREA, rel=0.05)
    after = layer.applied(layer.delete(sel))
    right = rect_area(*RIGHT_OF_EDGE_BOX)            # beyond the new line, out to the old outline
    leftovers = sum(area_px(intersection(a, right)) for a in after.visible_areas().values())
    assert leftovers <= layer.line_width * 6         # at most the two corner stubs where the lines meet
    assert area_px(after.visible_areas()[SKIN_BASE]) == pytest.approx(FACE_AREA - STRIP_AREA, rel=0.005)


def test_close_gap_closes_a_line_that_stops_short():
    layer = brushed(CORRECT_EDGE_SHORT_BY_2PX)
    assert area_px(layer.wand(*STRIP_CENTER).area) == pytest.approx(STRIP_AREA, rel=0.05)
    assert area_px(layer.wand(*STRIP_CENTER, close_gap=0).area) > FACE_AREA * 0.9


def test_wand_leaks_through_a_gap_wider_than_close_gap():
    layer = brushed(CORRECT_EDGE_SHORT_BY_8PX)
    assert area_px(layer.wand(*STRIP_CENTER).area) > FACE_AREA * 0.9


def test_wand_on_transparency_selects_nothing():
    assert face_with_strip().wand(-50, -50) is None


def test_shift_adds_and_alt_subtracts():
    layer = brushed()
    strip, shadow = layer.wand(*STRIP_CENTER), layer.wand(60, 140)
    both = strip.combined(shadow)
    assert area_px(both.area) == pytest.approx(area_px(strip.area) + area_px(shadow.area), rel=0.001)
    assert area_px(both.combined(strip, subtract=True).area) == pytest.approx(area_px(shadow.area), rel=0.001)


def test_delete_removes_every_tone_under_the_selection():
    layer = face_with_strip()
    box = rect_area(30, 110, 90, 170)
    after = layer.applied(layer.delete(Selection(box, [])))
    assert all(area_px(intersection(a, box)) < 0.01 for a in after.visible_areas().values())
    skin = fill_areas(after.drawings[0].shape)[0]
    assert area_px(intersection(skin, box)) < 0.01                  # the base hidden under the shadow too


def test_paint_in_the_base_tone_shows_above_the_shadow():
    layer = face_with_strip()
    patch = rect_area(40, 120, 60, 160)
    after = layer.applied(layer.paint(patch, SKIN_BASE))
    assert after.tone_at(50, 140) == SKIN_BASE and after.tone_at(70, 140) == SHADOW
    assert area_px(after.visible_areas()[SHADOW]) == pytest.approx(40 * 40 - 20 * 40, rel=0.01)


def test_new_color_becomes_a_fixed_tone_with_a_note():
    layer = face_with_strip()
    edit = layer.paint(rect_area(100, 100, 120, 120), (0, 255, 0, 255))
    assert set(edit.shapes) == {"line"} and len(edit.shapes["line"].fills) == 2
    assert edit.notes == [NEW_FIXED_COLOR % "#00FF00"]
    after = layer.applied(edit)
    assert after.tone_at(110, 110) == ToneRef("line", 1)
    assert next(t for t in after.tones if t.ref == ToneRef("line", 1)).binding is None


def test_a_layer_with_only_colored_drawings_refuses_new_colors():
    layer = face_with_strip(colored_only=True)
    edit = layer.paint(rect_area(100, 100, 120, 120), (0, 255, 0, 255))
    assert edit.empty and edit.notes == [ONLY_COLORED]


def test_erase_cuts_all_tones():
    layer = face_with_strip()
    box = rect_area(30, 110, 60, 140)
    after = layer.applied(layer.erase(box))
    assert after.tone_at(45, 125) is None and after.tone_at(70, 150) == SHADOW
    assert area_px(intersection(fill_areas(after.drawings[0].shape)[0], box)) < 0.01


def test_transform_moves_the_selection_and_leaves_a_hole():
    layer = face_with_strip()
    sel = layer.wand(60, 140)
    after = layer.applied(layer.transform(sel, Matrix.translate(30, 0)))
    assert after.tone_at(105, 140) == SHADOW and after.tone_at(50, 140) is None
    assert area_px(after.visible_areas()[SHADOW]) == pytest.approx(40 * 40, rel=0.01)


def test_transform_without_a_selection_moves_the_whole_layer_exactly():
    layer = face_with_strip()
    edit = layer.transform(None, Matrix.translate(10, 5))
    assert set(edit.shapes) == {"skin", "shadow", "line"}
    first = layer.drawings[0].shape.paths[0]
    moved = edit.shapes["skin"].paths[0]
    assert (moved.start.x, moved.start.y) == (first.start.x + 10, first.start.y + 5)


def test_an_edit_that_changes_nothing_is_empty():
    layer = face_with_strip()
    covered = intersection(layer.visible_areas()[LINE], rect_area(150, 0, 170, 20))
    assert layer.paint(covered, LINE).empty
    assert layer.erase(rect_area(-500, -500, -400, -400)).empty
    assert layer.delete(Selection(rect_area(-500, -500, -400, -400), [])).empty


def test_edits_on_scaled_and_rotated_drawings_land_where_clicked():
    a = math.radians(30)
    m = Matrix(math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 200, 100) @ Matrix.scale(-0.553, 1)
    art = Drawing("eye", shape_of({0: polygon_area([(0, 0), (40, 0), (40, 20), (0, 20)])}, [LINE_RGBA]), m, False)
    layer = EditLayer("Eye", [art], [Tone(ToneRef("eye", 0), LINE_RGBA, None)], ToneRef("eye", 0), 2.0)
    edit = layer.paint(rect_area(150, 150, 160, 160), ToneRef("eye", 0))
    after = layer.applied(edit)
    assert after.tone_at(155, 155) == ToneRef("eye", 0) and after.tone_at(165, 165) is None


def test_untouched_drawings_are_not_in_the_edit():
    layer = face_with_strip()
    assert set(layer.paint(rect_area(300, 200, 320, 220), LINE).shapes) == {"line"}


def test_a_stroke_on_a_layer_of_typical_size_takes_well_under_a_second():
    layer = busy_layer(drawings=4, edges_each=360)               # like TheSwordHero's pieces
    t = time.perf_counter()
    layer.paint(stroke_area(long_stroke(), 4), layer.line_tone)
    assert time.perf_counter() - t < 0.5                         # guard; the target is ~0.15 s (spec §9)
