# tests/swf/test_decode.py
import struct

import pytest
from swf_builders import swf, shape_tag, morph_tag, sprite_tag, place2, place3, remove2, frame_label, symbol_class
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.swf.decode import (MovieData, ShapeDef, MorphShapeDef, SpriteDef, RemoveCommand, SolidStyle, GradientStyle,
                                BlurFilter, GlowFilter, ColorMatrixFilter, UnsupportedFilter)

RED, BLUE = (255, 0, 0, 255), (0, 0, 255, 255)
SQUARE = {"fill1": 1, "start": (0, 0), "edges": [(10, 0), (10, 10), (0, 10), (0, 0)]}
GRAY = (0.3086, 0.6094, 0.082, 0, 0) * 3 + (0, 0, 0, 1, 0)

def red_square(cid=1, version=1):
    return shape_tag(cid, version, fills=[("solid", RED)], lines=[], paths=[SQUARE])

def test_shape1_square_with_line_style():
    s = MovieData(swf([shape_tag(1, 1, fills=[("solid", RED)], lines=[(1.0, BLUE)], paths=[dict(SQUARE, line=1)])])).character(1)
    assert isinstance(s, ShapeDef) and s.fills == (SolidStyle(RED),) and s.bounds == (0.0, 10.0, 0.0, 10.0)
    assert s.lines[0].width == 1.0 and s.lines[0].fill == SolidStyle(BLUE) and not s.nonzero
    assert [(e.start, e.end, e.fill0, e.fill1, e.line, e.layer) for e in s.edges[:2]] == [
        ((0, 0), (200, 0), None, 0, 0, 0), ((200, 0), (200, 200), None, 0, 0, 0)]

def test_new_styles_start_a_layer_with_global_indexes():
    second = {"fill1": 1, "start": (20, 0), "edges": [(30, 0), (30, 10), (20, 0)], "new_styles": ([("solid", BLUE)], [])}
    s = MovieData(swf([shape_tag(1, 2, fills=[("solid", RED)], lines=[], paths=[SQUARE, second])])).character(1)
    assert s.fills == (SolidStyle(RED), SolidStyle(BLUE))
    assert {(e.fill1, e.layer) for e in s.edges} == {(0, 0), (1, 1)}

def test_curved_edge_and_shape4_winding_flag():
    path = {"fill1": 1, "start": (0, 0), "edges": [(10, 0, 10, 10), (0, 0)]}
    s = MovieData(swf([shape_tag(1, 4, fills=[("solid", RED)], lines=[], paths=[path], nonzero=True)])).character(1)
    assert (s.edges[0].start, s.edges[0].control, s.edges[0].end) == ((0, 0), (200, 0), (200, 200))
    assert s.edges[1].control is None and s.nonzero

def test_gradient_fill_style():
    g = ("linear", Matrix(a=0.01, d=0.01, tx=5, ty=5), [(0, (0, 0, 0, 255)), (255, (255, 255, 255, 255))])
    st = MovieData(swf([shape_tag(1, 3, fills=[g], lines=[], paths=[SQUARE])])).character(1).fills[0]
    assert isinstance(st, GradientStyle) and (st.kind, st.spread, st.interpolation) == ("linear", 0, 0)
    assert st.stops == ((0, (0, 0, 0, 255)), (255, (255, 255, 255, 255)))
    assert st.matrix.a == pytest.approx(0.01, abs=1e-4) and (st.matrix.tx, st.matrix.ty) == (5.0, 5.0)

def test_morph_shape_pairs_end_edges_with_start_styles():
    m = MovieData(swf([morph_tag(2, RED, BLUE, start=[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
                                 end=[(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])])).character(2)
    assert isinstance(m, MorphShapeDef)
    assert m.start.fills == (SolidStyle(RED),) and m.end.fills == (SolidStyle(BLUE),)
    assert [e.end for e in m.end.edges] == [(400, 0), (400, 400), (0, 400), (0, 0)]
    assert [e.fill1 for e in m.end.edges] == [0, 0, 0, 0]

def test_sprite_timeline_labels_and_classes():
    frames = [[place2(1, cid=1, matrix=Matrix.translate(5, 6), name="dot"), frame_label("Idle")],
              [place2(1, move=True, matrix=Matrix.translate(7, 6), cx=ColorTransform((1.0, 1.0, 1.0, 0.5)))],
              [remove2(1)]]
    md = MovieData(swf([red_square(), sprite_tag(3, frames), symbol_class({3: "Thing"})]))
    sp = md.character(3)
    assert isinstance(sp, SpriteDef) and md.classes == {"Thing": 3} and md.class_name(3) == "Thing"
    assert sp.frame_count == 3 and sp.labels == {"Idle": 0}
    p = sp.frames[0][0]
    assert (p.depth, p.char_id, p.name, p.move, p.matrix.tx, p.matrix.ty) == (1, 1, "dot", False, 5.0, 6.0)
    m = sp.frames[1][0]
    assert m.move and m.char_id is None and m.color == ColorTransform((1.0, 1.0, 1.0, 0.5), (0, 0, 0, 0))
    assert sp.frames[2] == (RemoveCommand(1),)

def test_place3_filters_blend_and_clip_depth():
    bevel = b"\x03" + bytes(4 + 4 + 16 + 2 + 1)
    filters = [BlurFilter(4.0, 2.0, 2), GlowFilter((255, 255, 0, 255), 6.0, 6.0, 2.0, False, False, 1), ColorMatrixFilter(GRAY), bevel]
    frames = [[place2(1, cid=1, clip_depth=3), place3(2, cid=1, filters=filters, blend=13)]]
    cmds = MovieData(swf([red_square(), sprite_tag(4, frames)])).character(4).frames[0]
    assert cmds[0].clip_depth == 3 and cmds[1].blend == "overlay"
    f = cmds[1].filters
    assert f[0] == BlurFilter(4.0, 2.0, 2) and f[1] == GlowFilter((255, 255, 0, 255), 6.0, 6.0, 2.0, False, False, 1)
    assert f[2].matrix[0] == pytest.approx(0.3086, abs=1e-4) and f[3] == UnsupportedFilter("Bevel")

def test_unknown_characters_and_root_timeline():
    md = MovieData(swf([red_square(), place2(1, cid=1)]))
    assert md.character(99) is None and md.root.frame_count == 1 and md.root.frames[0][0].char_id == 1


def test_corrupt_files_raise_a_clear_error(tmp_path):
    bad = tmp_path / "bad.swf"
    bad.write_bytes(b"CWS\x0f" + struct.pack("<I", 500) + b"not zlib data")
    with pytest.raises(ValueError, match="bad.swf is not a valid SWF file"):
        MovieData(bad)
    with pytest.raises(ValueError, match="not a valid SWF file"):
        MovieData(swf([red_square()])[:20])


def test_class_bound_to_the_root_timeline_is_drawable():
    md = MovieData(swf([red_square(), place2(1, cid=1), symbol_class({0: "Kit"})]))
    assert md.character(0) is md.root and md.class_name(0) == "Kit"
