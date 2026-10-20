import pytest
# tests/render/test_colors_scripts.py
from autoswf.abc.movieclip_classes import ClassSpec, build_abc, expected_setcolor_ops
from autoswf.abc.reader import ABC
from autoswf.model.document import GotoAndPlayScript, SetColorScript, StopScript
from autoswf.model.geometry import ColorTransform
from autoswf.render.colors import PlayerColors, apply, concat, player_color_transform
from autoswf.render.scripts import (CallSelf, GotoAndPlay, SetColor, Stop, analyze_frame_script, class_frame_actions)

PC = PlayerColors(skin=0xF2C9A0, hair=0x4B3621, eye=0x0099FF, base=0x123456, trim=0x654321, accessory=0xABCDEF)

def test_concat_applies_inner_first_and_apply_clamps():
    c = concat(ColorTransform((0.5, 1, 1, 1), (10, 0, 0, 0)), ColorTransform((1, 1, 1, 0.5), (20, 0, 0, 0)))
    assert c.mult == (0.5, 1, 1, 0.5) and c.add == (20, 0, 0, 0)
    assert apply(c, (100, 100, 100, 200)) == (70, 100, 100, 100)
    assert apply(ColorTransform((0, 0, 0, 1), (300, -40, 128, 0)), (5, 5, 5, 255)) == (255, 0, 128, 255)

def test_player_color_transform_matches_client_changeColor():
    assert player_color_transform("Skin", "None", PC) == ColorTransform((0.0, 0.0, 0.0, 1.0), (242, 201, 160, 0))
    assert player_color_transform("Skin", "Dark", PC).add == (217, 151, 110, 0)
    assert player_color_transform("Hair", "Dark", PC).add == (25, 4, -17, 0)
    assert player_color_transform("Hair", "dark", PC).add == (25, 4, -17, 0)
    assert player_color_transform("Hair", "Light", PC).add == (175, 154, 133, 0)
    assert apply(player_color_transform("Eye", "Darker", PC), (1, 2, 3, 77)) == (0, 28, 130, 77)
    assert player_color_transform("Cape", "None", PC).add == (0, 0, 0, 0)

# Copied from the client's disassembly of mcSkel.frame8 (Idle) and mcSkel.frame68 (end of Walk).
SKEL_IDLE = [("getlocal0", ()), ("pushscope", ()), ("getlocal0", ()), ("callpropvoid", ("showIdleFoot", "0")),
             ("getlocal0", ()), ("getproperty", ("cape",)), ("getproperty", ("cape",)), ("pushstring", ("'Idle'",)),
             ("callpropvoid", ("gotoAndStop", "1")), ("findpropstrict", ("stop",)), ("callpropvoid", ("stop", "0")), ("returnvoid", ())]
SKEL_WALK_END = [("getlocal0", ()), ("pushscope", ()), ("getlocal0", ()), ("getproperty", ("onMove",)), ("iffalse", ("->18",)),
                 ("getlocal0", ()), ("pushstring", ("'Walk'",)), ("callpropvoid", ("gotoAndPlay", "1")), ("returnvoid", ())]

def test_frame_script_patterns():
    assert analyze_frame_script(SKEL_IDLE) == [CallSelf("showIdleFoot"), Stop()]
    assert analyze_frame_script(SKEL_WALK_END) == [GotoAndPlay("Walk", conditional=True)]
    assert analyze_frame_script(expected_setcolor_ops("Demo_fla.Hair_1", "Hair", "Light")) == [SetColor("Hair", "Light")]
    goto5 = [("getlocal0", ()), ("pushscope", ()), ("findpropstrict", ("gotoAndPlay",)), ("pushbyte", ("5",)),
             ("callpropvoid", ("gotoAndPlay", "1")), ("returnvoid", ())]
    assert analyze_frame_script(goto5) == [GotoAndPlay(4)]
    assert analyze_frame_script([("getlocal0", ()), ("pushscope", ()), ("newfunction", ("3",)), ("findpropstrict", ("stop",)),
                                 ("callpropvoid", ("stop", "0"))]) == []

def test_class_frame_actions_from_generated_classes():
    abc = ABC(build_abc([ClassSpec("Demo_fla.Skin_1", ((0, SetColorScript("Skin", "Dark")),)),
                         ClassSpec("Cape", ((0, StopScript()), (36, GotoAndPlayScript("Move"))))]))
    assert class_frame_actions([abc], "Demo_fla.Skin_1") == {0: [SetColor("Skin", "Dark")]}
    assert class_frame_actions([abc], "Cape") == {0: [Stop()], 36: [GotoAndPlay("Move")]}
    assert class_frame_actions([abc], "Nope") == {}


def test_property_stores_do_not_end_the_analysis():
    # mcSkel.frame1 in the client: animLoop = 0; avtMC = null; gotoAndPlay("Idle")
    ops = [("getlocal0", ()), ("pushscope", ()), ("getlocal0", ()), ("pushbyte", ("0",)), ("initproperty", ("animLoop",)),
           ("getlocal0", ()), ("pushnull", ()), ("initproperty", ("avtMC",)), ("getlocal0", ()),
           ("pushstring", ("'Idle'",)), ("callpropvoid", ("gotoAndPlay", "1")), ("returnvoid", ())]
    assert analyze_frame_script(ops) == [GotoAndPlay("Idle")]


def test_constructor_may_reference_frame_methods_by_plain_name():
    # The client's classes call addFrameScript(0, this.frame1) through a multiname, while the trait is pkg::frame1.
    from autoswf.abc.code import Code
    from autoswf.abc.writer import PACKAGE, PACKAGE_INTERNAL, PROTECTED, AbcBuilder, MethodTrait
    b = AbcBuilder()
    name, mc = b.qname(PACKAGE, "spider_fla", "Face_1"), b.qname(PACKAGE, "flash.display", "MovieClip")
    stop = b.qname(PACKAGE, "", "stop")
    frame = b.method(1, 1, 10, 11, Code().getlocal0().pushscope().findpropstrict(stop).callpropvoid(stop, 0).returnvoid().bytes())
    add = b.qname(PACKAGE, "", "addFrameScript")
    ref = b.multiname("frame1", [(PACKAGE_INTERNAL, "spider_fla"), (PACKAGE, "")])
    ctor = Code().getlocal0().pushscope().getlocal0().constructsuper(0).findpropstrict(add).pushbyte(0)
    ctor = ctor.getlocal0().getproperty(ref).callpropvoid(add, 2).returnvoid()
    cinit = b.method(1, 1, 9, 10, Code().getlocal0().pushscope().returnvoid().bytes())
    b.add_class(name, mc, b.namespace(PROTECTED, "spider_fla:Face_1"), b.method(3, 1, 10, 11, ctor.bytes()), cinit,
                [MethodTrait(b.qname(PACKAGE_INTERNAL, "spider_fla", "frame1"), frame)])
    assert class_frame_actions([ABC(b.serialize())], "spider_fla.Face_1") == {0: [Stop()]}


@pytest.mark.parametrize("form", ["plain", "try", "activation"])
def test_color_scripts_in_every_official_form_are_found(form):
    from aqw_fakes import mini_armor_with_pieces
    from autoswf.render.scripts import SetColor, class_frame_actions
    from autoswf.swf.decode import MovieData
    movie = MovieData(mini_armor_with_pieces("M", setcolor_form=form))
    assert class_frame_actions(movie.abcs, "TestArmor_fla.Skin_1")[0] == [SetColor("Skin", "None")]
