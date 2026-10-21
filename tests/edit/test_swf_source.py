import re

import pytest

from aqw_fakes import mini_armor_with_pieces
from editor_fixtures import (LINE_RGBA, edges_in_twips, rect_area, strip_face_armor)
from swf_builders import doabc_tag, morph_tag, place2, remove2, shape_tag, sprite_tag, symbol_class, swf
from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.edit.layer import ToneRef
from autoswf.edit.regions import area_px, fill_areas
from autoswf.edit.swf_source import (UneditableDrawing, drawing_frames, drawing_uses, shape_def_of, shape_from_def,
                                     swf_layer)
from autoswf.items.edit import edit_swf
from autoswf.items.structure import read_structure
from autoswf.model.geometry import Matrix
from autoswf.render.colors import PlayerColors
from autoswf.swf.decode import (BitmapStyle, Edge, GradientStyle, MovieData, ShapeDef, SolidStyle, parse_shape)

SQUARE = [{"start": (0, 0), "edges": [(10, 0), (10, 10), (0, 10), (0, 0)], "fill1": 1}]


def doabc(names):
    return doabc_tag(build_abc([ClassSpec(n) for n in names]))


def test_shape_from_def_round_trips_through_define_shape4():
    paths = [{"start": (0, 0), "edges": [(20, 0), (30, 10, 20, 20), (0, 20), (0, 0)], "fill1": 1},
             {"start": (5, 5), "edges": [(10, 5), (10, 10), (5, 10), (5, 5)], "fill0": 1, "fill1": 2}]
    raw = shape_tag(5, 4, [("solid", (200, 10, 10, 255)), ("solid", (10, 200, 10, 255))], [], paths)
    d = parse_shape(raw, 6 if raw[0] & 0x3F == 0x3F else 2, 4)
    again = shape_def_of(shape_from_def(d), 5)
    assert edges_in_twips(again) == edges_in_twips(d)
    assert again.fills == d.fills


def test_strokes_become_filled_areas_of_the_stroke_color():
    raw = shape_tag(6, 4, [], [(4, (255, 0, 0, 255))], [{"start": (0, 0), "edges": [(100, 0)], "line": 1}])
    d = parse_shape(raw, 6 if raw[0] & 0x3F == 0x3F else 2, 4)
    shape = shape_from_def(d)
    assert [f.color for f in shape.fills] == [(255, 0, 0, 255)]
    assert area_px(fill_areas(shape)[0]) == pytest.approx(100 * 4 + 3.1416 * 4, rel=0.03)


def test_uneditable_drawings_say_why_and_change_nothing():
    movie = MovieData(swf([morph_tag(1, (255, 0, 0, 255), (0, 0, 255, 255), [(0, 0), (10, 0), (10, 10), (0, 0)],
                                     [(0, 0), (20, 0), (20, 20), (0, 0)]),
                           sprite_tag(2, [[place2(1, 1, ratio=0)]]), sprite_tag(3, [[place2(1, 2)]]),
                           symbol_class({3: "Tween"}), doabc(["Tween"])]))
    with pytest.raises(UneditableDrawing, match=re.escape("This piece is a shape tween; editing it is not supported yet.")):
        swf_layer(movie, read_structure(movie), "Item/1", 0)
    edge = Edge((0, 0), None, (200, 0), None, 0, None, 0)
    bitmap = ShapeDef(7, (0, 10, 0, 10), (BitmapStyle(1, Matrix()),), (), (edge,), False)
    with pytest.raises(UneditableDrawing, match=re.escape("This drawing uses a bitmap fill; the editor cannot keep it yet.")):
        shape_from_def(bitmap)
    focal = ShapeDef(8, (0, 10, 0, 10), (GradientStyle("focal", Matrix(), ((0, (0, 0, 0, 255)), (255, (9, 9, 9, 255))),
                                                       focal=0.5),), (), (edge,), False)
    with pytest.raises(UneditableDrawing, match=re.escape("This drawing uses a gradient the editor cannot keep yet.")):
        shape_from_def(focal)


def test_swf_layer_lists_the_tones_of_a_colorable_skin():
    movie = MovieData(strip_face_armor())
    layer = swf_layer(movie, read_structure(movie), "MHead/1", 0, PlayerColors())
    assert [d.colorable for d in layer.drawings] == [True, True, False]
    bindings = {t.binding for t in layer.tones}
    assert bindings == {("Skin", "None"), ("Skin", "Dark"), None}
    skin = 0xF2C9A0
    base = next(t for t in layer.tones if t.binding == ("Skin", "None"))
    shadow = next(t for t in layer.tones if t.binding == ("Skin", "Dark"))
    assert base.color == (skin >> 16, (skin >> 8) & 255, skin & 255, 255)
    assert shadow.color == ((skin >> 16) - 25, ((skin >> 8) & 255) - 50, (skin & 255) - 50, 255)
    line = next(t for t in layer.tones if t.binding is None)
    assert layer.line_tone == line.ref and line.color == LINE_RGBA
    assert layer.line_width == pytest.approx(3.0, rel=0.1)


def test_drawing_frames_marks_frames_showing_the_same_drawing():
    movie = MovieData(swf([shape_tag(10, 1, [("solid", (1, 1, 1, 255))], [], SQUARE),
                           shape_tag(11, 1, [("solid", (2, 2, 2, 255))], [], SQUARE),
                           sprite_tag(20, [[place2(1, 10)], [], [remove2(1), place2(1, 11)]]),
                           sprite_tag(30, [[place2(1, 20)]]), symbol_class({30: "Blinky"}), doabc(["Blinky"])]))
    structure = read_structure(movie)
    assert drawing_frames(movie, structure, "Item/1", 10) == [0, 1]
    assert drawing_frames(movie, structure, "Item/1", 11) == [2]
    assert [d.key for d in swf_layer(movie, structure, "Item/1", 2).drawings] == ["11"]


def test_editing_a_shared_drawing_changes_every_use_and_says_where():
    data = mini_armor_with_pieces()
    movie = MovieData(data)
    structure = read_structure(movie)
    vest = swf_layer(movie, structure, "MChest/3", 0)
    gem = next(d for d in vest.drawings if d.key == str(structure.piece("MShoulder/3/1").char_id))
    uses = drawing_uses(movie, structure, "MChest/3", int(gem.key))
    assert any(u.startswith("MShoulder/") for u in uses) and any(u.startswith("MChest/5") for u in uses)
    assert not any(u.startswith("MChest/3/") for u in uses)
    bigger = vest.paint(rect_area(-20, -20, 20, 20), ToneRef(gem.key, 0)).shapes[gem.key]
    out = MovieData(edit_swf(data, replace_shapes={int(gem.key): bigger}).data)
    assert out.character(int(gem.key)).bounds != movie.character(int(gem.key)).bounds
