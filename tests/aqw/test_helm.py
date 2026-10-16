import pytest

from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import ColorCustom, Frame, Placement, Symbol
from autoswf.model.shape import Shape, SolidFill, ellipse
from autoswf.swf.reader import SWF


def cc(name, loc, shade, rx):
    return Symbol(name, [Frame([Placement(Shape([SolidFill((200, 160, 120, 255))], [ellipse(0, 0, 0, rx, rx)]), 1)])],
                  color_custom=ColorCustom(loc, shade))


def demo_item():
    skin, iris, hair = cc("Skin", "Skin", "None", 40), cc("Iris", "Eye", "None", 6), cc("Hair", "Hair", "Dark", 30)
    root = Symbol("Root", [Frame([Placement(skin, 1), Placement(iris, 3), Placement(iris, 5), Placement(hair, 7)])])
    back = Symbol("Back", [Frame([Placement(cc("BackHair", "Hair", "None", 50), 1)])])
    return HelmItem("KitsuneMorph", root, back)


def test_export_classes_and_validation():
    data = export_helm(demo_item())
    names = set(SWF(data).symbols.values())
    assert {"KitsuneMorph", "KitsuneMorph_backhair"} <= names
    assert {"KitsuneMorph_fla.Skin_1", "KitsuneMorph_fla.Iris_2", "KitsuneMorph_fla.Hair_3"} <= names
    assert validate_helm_swf(data, "KitsuneMorph") == []


def test_invalid_location_is_rejected_on_export():
    item = demo_item(); item.root.frames[0].placements[0].item.color_custom = ColorCustom("Cape", "None")
    with pytest.raises(ValueError, match="Cape"):
        export_helm(item)


def test_validator_reports_missing_link_class():
    problems = validate_helm_swf(export_helm(demo_item()), "OtherName")
    assert problems == ["Class 'OtherName' is missing; AQW loads the helm by this name."]


def test_validator_flags_setcolor_with_wrong_multiname_kind():
    from autoswf.abc.code import Code
    from autoswf.abc.writer import PACKAGE, PACKAGE_INTERNAL, PROTECTED, AbcBuilder, MethodTrait
    from autoswf.swf.movie import build_swf
    b = AbcBuilder()
    mc = b.qname(PACKAGE, "flash.display", "MovieClip")
    body = Code().getlocal0().pushscope().findpropstrict(mc).getlocal0().getproperty(b.qname(PACKAGE, "", "stage"))
    body.pushbyte(0).callproperty(b.qname(PACKAGE, "", "getChildAt"), 1).callproperty(mc, 1).getlocal0()
    body.pushstring(b.string("Skin")).pushstring(b.string("None"))
    body.callpropvoid(b.qname(PACKAGE, "", "mcSetColor"), 3).returnvoid()          # public QName, not Flash's Multiname
    frame = b.method(4, 1, 10, 11, body.bytes())
    trait = b.qname(PACKAGE_INTERNAL, "X_fla", "frame1")
    ctor = Code().getlocal0().pushscope().getlocal0().constructsuper(0).findpropstrict(b.qname(PACKAGE, "", "addFrameScript"))
    ctor.pushbyte(0).getlex(trait).callpropvoid(b.qname(PACKAGE, "", "addFrameScript"), 2).returnvoid()
    name = b.qname(PACKAGE, "X_fla", "Skin_1")
    ci = b.add_class(name, mc, b.namespace(PROTECTED, "X_fla:Skin_1"), b.method(3, 1, 10, 11, ctor.bytes()),
                     b.method(1, 1, 9, 10, Code().getlocal0().pushscope().returnvoid().bytes()), [MethodTrait(trait, frame)])
    b.add_script(b.method(2, 1, 1, 9, Code().getlocal0().pushscope().returnvoid().bytes()), name, ci)
    skin = Symbol("Skin", [Frame()]); root = Symbol("Root", [Frame([Placement(skin, 1)])])
    data = build_swf([root], {id(root): "X", id(skin): "X_fla.Skin_1"}, b.serialize())
    assert "Color-custom script in 'X_fla.Skin_1' is not in the format AQW expects." in validate_helm_swf(data, "X")
