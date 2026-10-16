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
