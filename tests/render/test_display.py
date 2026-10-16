# tests/render/test_display.py
from swf_builders import doabc_tag, place2, remove2, shape_tag, sprite_tag, swf, symbol_class
from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.model.document import SetColorScript, StopScript
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ScriptContext, effective_color, instantiate, run_pending_actions, tick
from autoswf.swf.decode import MovieData

DOT = shape_tag(1, 1, fills=[("solid", (255, 0, 0, 255))], lines=[], paths=[{"fill1": 1, "start": (0, 0), "edges": [(4, 0), (4, 4), (0, 0)]}])
KID = sprite_tag(11, [[place2(1, cid=1)], [], []])

def movie(*tags, classes=None, abc=None):
    return MovieData(swf([DOT, *tags, *([doabc_tag(abc)] if abc else []), symbol_class(classes or {})]))

def test_timeline_moves_removes_and_loops():
    clip = instantiate(movie(sprite_tag(10, [[place2(1, cid=1)], [place2(1, move=True, matrix=Matrix.translate(5, 0))], [remove2(1)]])), 10)
    ctx = ScriptContext()
    assert clip.frame == 0 and clip.child_at_depth(1).matrix.tx == 0
    tick(clip, ctx); assert clip.frame == 1 and clip.child_at_depth(1).matrix.tx == 5
    tick(clip, ctx); assert clip.frame == 2 and clip.child_at_depth(1) is None
    tick(clip, ctx); assert clip.frame == 0 and clip.child_at_depth(1).matrix.tx == 0

def test_child_from_frame_0_survives_the_parent_loop_with_its_playhead():
    root = instantiate(movie(KID, sprite_tag(12, [[place2(1, cid=11)], [place2(1, move=True, matrix=Matrix.translate(3, 0))]])), 12)
    kid, ctx = root.child_at_depth(1), ScriptContext()
    tick(root, ctx); tick(root, ctx)
    assert root.frame == 0 and root.child_at_depth(1) is kid and kid.frame == 2 and kid.matrix.tx == 0

def test_child_placed_later_is_recreated_and_children_never_pile_up():
    root = instantiate(movie(KID, sprite_tag(13, [[], [place2(1, cid=11)]])), 13)
    ctx = ScriptContext()
    tick(root, ctx); first = root.child_at_depth(1)
    tick(root, ctx); assert root.child_at_depth(1) is None
    tick(root, ctx); assert root.child_at_depth(1) is not first
    for _ in range(1000):
        tick(root, ctx)
        assert len(root.children) <= 1
    assert len(root.sprite._states) <= 2

def test_stop_script_holds_its_frame():
    abc = build_abc([ClassSpec("Holder", ((1, StopScript()),))])
    clip = instantiate(movie(sprite_tag(14, [[place2(1, cid=1)], [], []]), classes={14: "Holder"}, abc=abc), 14)
    for _ in range(4):
        tick(clip, ScriptContext())
    assert clip.frame == 1 and not clip.playing

def test_set_color_uses_player_color_and_freezes_the_timeline_transform():
    abc = build_abc([ClassSpec("Demo_fla.Skin_1", ((0, SetColorScript("Skin", "None")),))])
    parent = sprite_tag(16, [[place2(1, cid=15, cx=ColorTransform((1.0, 1.0, 1.0, 0.5)))], [place2(1, move=True, matrix=Matrix.translate(9, 0))]])
    md = movie(sprite_tag(15, [[place2(1, cid=1)]]), parent, classes={15: "Demo_fla.Skin_1"}, abc=abc)
    colors = PlayerColors(skin=0x112233); ctx = ScriptContext(colors=colors)
    root = instantiate(md, 16); run_pending_actions(root, ctx)
    s = root.child_at_depth(1)
    assert s.color_custom == ("Skin", "None") and s.script_transformed
    assert effective_color(s, colors) == ColorTransform((0.0, 0.0, 0.0, 1.0), (0x11, 0x22, 0x33, 0))
    assert effective_color(s, None) == ColorTransform((1.0, 1.0, 1.0, 0.5), (0, 0, 0, 0))
    tick(root, ctx)
    assert root.child_at_depth(1) is s and s.matrix.tx == 0

def test_script_children_api():
    md = movie(sprite_tag(17, [[place2(1, cid=1, name="dot")]]))
    root, a, b = instantiate(md, 17), instantiate(md, 1), instantiate(md, 1)
    root.add_child(a); root.add_child(b, index=0)
    assert root.children[0] is b and root.children[-1] is a and a.depth is None
    assert root.child_by_name("dot").depth == 1 and root.remove_child_at(0) is b
