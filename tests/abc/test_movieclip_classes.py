from autoswf.abc.disasm import disassemble, method_owners
from autoswf.abc.movieclip_classes import ClassSpec, build_abc, expected_setcolor_ops
from autoswf.abc.reader import ABC
from autoswf.model.document import GotoAndPlayScript, SetColorScript, StopScript


def ops(a, m):
    return [(i.op, i.args) for i in disassemble(a, a.bodies[m])]


def by_owner(a):
    return {v: k for k, v in method_owners(a).items()}


SCRIPT_INIT_PREFIX = [("getlocal0", ()), ("pushscope", ()), ("getscopeobject", ("0",)), ("getlex", ("Object",)), ("pushscope", ()),
    ("getlex", ("flash.events.EventDispatcher",)), ("pushscope", ()), ("getlex", ("flash.display.DisplayObject",)), ("pushscope", ()),
    ("getlex", ("flash.display.InteractiveObject",)), ("pushscope", ()), ("getlex", ("flash.display.DisplayObjectContainer",)), ("pushscope", ()),
    ("getlex", ("flash.display.Sprite",)), ("pushscope", ()), ("getlex", ("flash.display.MovieClip",)), ("pushscope", ()),
    ("getlex", ("flash.display.MovieClip",))]


def test_setcolor_class_matches_official_pattern():
    a = ABC(build_abc([ClassSpec("Demo_fla.Skin_1", ((0, SetColorScript("Skin", "None")),))]))
    m = by_owner(a)
    assert ops(a, m["Demo_fla.Skin_1.Demo_fla.frame1"]) == expected_setcolor_ops("Demo_fla.Skin_1", "Skin", "None") == [
        ("getlocal0", ()), ("pushscope", ()), ("findpropstrict", ("flash.display.MovieClip",)), ("getlocal0", ()),
        ("getproperty", ("stage",)), ("pushbyte", ("0",)), ("callproperty", ("getChildAt", "1")),
        ("callproperty", ("flash.display.MovieClip", "1")), ("getlocal0", ()), ("pushstring", ("'Skin'",)),
        ("pushstring", ("'None'",)), ("callpropvoid", ("mcSetColor", "3")), ("returnvoid", ())]
    assert ops(a, m["Demo_fla.Skin_1.<init>"]) == [("getlocal0", ()), ("pushscope", ()), ("getlocal0", ()),
        ("constructsuper", ("0",)), ("findpropstrict", ("addFrameScript",)), ("pushbyte", ("0",)),
        ("getlex", ("Demo_fla.frame1",)), ("callpropvoid", ("addFrameScript", "2")), ("returnvoid", ())]
    assert a.body_info[m["Demo_fla.Skin_1.Demo_fla.frame1"]] == (4, 1, 10, 11)
    assert a.body_info[m["Demo_fla.Skin_1.<init>"]] == (3, 1, 10, 11)
    script_init = a.scripts[0]["init"]
    assert ops(a, script_init) == SCRIPT_INIT_PREFIX + [("newclass", ("0",))] + [("popscope", ())] * 7 + [
        ("initproperty", ("Demo_fla.Skin_1",)), ("returnvoid", ())]
    assert a.body_info[script_init] == (2, 1, 1, 9)
    assert a.instances[0]["flags"] == 0x08


def test_cape_style_stop_and_goto_scripts():
    a = ABC(build_abc([ClassSpec("Cape", ((0, StopScript()), (36, GotoAndPlayScript("Move"))))]))
    m = by_owner(a)
    assert ops(a, m["Cape.frame1"]) == [("getlocal0", ()), ("pushscope", ()), ("findpropstrict", ("stop",)),
                                        ("callpropvoid", ("stop", "0")), ("returnvoid", ())]
    assert ops(a, m["Cape.frame37"]) == [("getlocal0", ()), ("pushscope", ()), ("findpropstrict", ("gotoAndPlay",)),
        ("pushstring", ("'Move'",)), ("callpropvoid", ("gotoAndPlay", "1")), ("returnvoid", ())]
    assert ops(a, m["Cape.<init>"])[4:] == [("findpropstrict", ("addFrameScript",)), ("pushbyte", ("0",)), ("getlex", ("frame1",)),
        ("pushbyte", ("36",)), ("getlex", ("frame37",)), ("callpropvoid", ("addFrameScript", "4")), ("returnvoid", ())]
    assert a.body_info[m["Cape.<init>"]] == (5, 1, 10, 11)


def test_frame_index_over_127_uses_pushshort():
    a = ABC(build_abc([ClassSpec("Long", ((200, StopScript()),))]))
    assert ("pushshort", ("200",)) in ops(a, by_owner(a)["Long.<init>"])


def test_plain_class_has_no_frame_scripts():
    a = ABC(build_abc([ClassSpec("Helm")]))
    assert ops(a, by_owner(a)["Helm.<init>"]) == [("getlocal0", ()), ("pushscope", ()), ("getlocal0", ()),
                                                   ("constructsuper", ("0",)), ("returnvoid", ())]


SETCOLOR_MULTINAME = ("Multiname(mcSetColor,[Private:'',Package:'flash.display',Package:'',Package:'Demo_fla',"
    "PackageInternal:'Demo_fla',Namespace:'http://adobe.com/AS3/2006/builtin',Protected:'Demo_fla:Skin_1',"
    "StaticProtected:'Demo_fla:Skin_1',StaticProtected:'flash.display:MovieClip',StaticProtected:'flash.display:Sprite',"
    "StaticProtected:'flash.display:DisplayObjectContainer',StaticProtected:'flash.display:InteractiveObject',"
    "StaticProtected:'flash.display:DisplayObject',StaticProtected:'flash.events:EventDispatcher'])")


def test_setcolor_call_is_a_flash_style_multiname():
    # Official items (Normal.swf, CrystallisOnsenMMorph4.swf) call mcSetColor through a Multiname
    # over the open namespaces, not through a public QName.
    a = ABC(build_abc([ClassSpec("Demo_fla.Skin_1", ((0, SetColorScript("Skin", "None")),))]))
    frame1 = by_owner(a)["Demo_fla.Skin_1.Demo_fla.frame1"]
    raw = [(i.op, i.args) for i in disassemble(a, a.bodies[frame1], raw=True)]
    assert raw[-2] == ("callpropvoid", (SETCOLOR_MULTINAME, "3"))
    assert raw == expected_setcolor_ops("Demo_fla.Skin_1", "Skin", "None", raw=True)
    assert raw[4] == ("getproperty", ("QName(Package:'',stage)",))


import pytest


@pytest.mark.parametrize("form, header", [("plain", (4, 1, 10, 11)), ("try", (4, 2, 10, 13)), ("activation", (4, 3, 11, 16))])
def test_every_official_setcolor_form_is_recognized(form, header):
    from autoswf.aqw.validate import setcolor_form
    abc = ABC(build_abc([ClassSpec("P_fla.Skin_1", ((0, SetColorScript("Skin", "Dark")),))], setcolor_form=form))
    method = next(t["method"] for t in abc.instances[0]["traits"] if "method" in t)
    assert abc.body_info[method] == header
    assert setcolor_form(abc, method, "P_fla.Skin_1") == (form, "Skin", "Dark")


def test_a_changed_call_is_not_an_official_form():
    from autoswf.aqw.validate import setcolor_form
    data = bytearray(build_abc([ClassSpec("P_fla.Skin_1", ((0, SetColorScript("Skin", "Dark")),))], setcolor_form="try"))
    abc = ABC(bytes(data))
    method = next(t["method"] for t in abc.instances[0]["traits"] if "method" in t)
    code = abc.bodies[method]
    start = bytes(data).index(code)
    k = code.index(b"\x24\x00")                    # pushbyte 0 (the stage's first child)
    data[start + k + 1] = 1
    abc = ABC(bytes(data))
    assert setcolor_form(abc, method, "P_fla.Skin_1") is None
