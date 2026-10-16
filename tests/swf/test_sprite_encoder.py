from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.model.shape import Shape
from autoswf.swf.reader import iter_tags, parse_place
from autoswf.swf.sprite_encoder import encode_define_sprite


def tags(body):
    return [(code, body[p:p + ln]) for code, p, ln in iter_tags(body, 4, len(body))]


def _place(tag):
    code, data = tag
    return data, 0, len(data), code == 70


def test_three_frames_place_move_remove_and_label():
    dot = Shape([], [])
    f1 = Frame([Placement(dot, 1, Matrix.translate(5, 5), name="Face")], label="Idle")
    f2 = Frame([Placement(dot, 1, Matrix.translate(5, 9), color=ColorTransform((1, 1, 1, 0.5)))])
    f3 = Frame([])
    s = Symbol("S", [f1, f2, f3])
    body = encode_define_sprite(s, {id(dot): 4, id(s): 5})
    assert body[:4] == bytes([5, 0, 3, 0])                     # id 5, 3 frames
    seq = [code for code, _ in tags(body)]
    assert seq == [26, 43, 1, 26, 1, 28, 1, 0]                 # Place, FrameLabel, Show, Move, Show, Remove, Show, End
    first = parse_place(*_place(tags(body)[0]))
    assert first["char"] == 4 and first["name"] == "Face" and first["matrix"][4:] == (5.0, 5.0)
    second = parse_place(*_place(tags(body)[3]))
    assert second["move"] and "char" not in second and second["matrix"][4:] == (5.0, 9.0)
    assert second["cx"] == {"mult": (1.0, 1.0, 1.0, 0.5), "add": None}


def test_symbol_without_frames_encodes_one_empty_frame():
    s = Symbol("Empty", [])
    body = encode_define_sprite(s, {id(s): 9})
    assert body[:4] == bytes([9, 0, 1, 0]) and [c for c, _ in tags(body)] == [1, 0]


def test_swapping_symbols_at_a_depth_removes_then_places_fresh():
    a = Symbol("A", [Frame()]); b = Symbol("B", [Frame()])
    s = Symbol("S", [Frame([Placement(a, 1, color=ColorTransform((1, 1, 1, 0.5)))]),
                     Frame([Placement(b, 1, Matrix.translate(3, 4), name="Face")])])
    body = encode_define_sprite(s, {id(a): 1, id(b): 2, id(s): 3})
    t = tags(body)
    assert [code for code, _ in t] == [26, 1, 28, 26, 1, 0]
    fresh = parse_place(*_place(t[3]))
    assert fresh["char"] == 2 and not fresh["move"] and fresh["name"] == "Face" and "cx" not in fresh


def test_swapping_shapes_resets_a_cleared_color():
    s1, s2 = Shape([], []), Shape([], [])
    s = Symbol("S", [Frame([Placement(s1, 1, color=ColorTransform((1, 1, 1, 0.5)))]), Frame([Placement(s2, 1)])])
    t = tags(encode_define_sprite(s, {id(s1): 1, id(s2): 2, id(s): 3}))
    swap = parse_place(*_place(t[2]))
    assert swap["move"] and swap["char"] == 2 and swap["cx"] == {"mult": None, "add": None}
