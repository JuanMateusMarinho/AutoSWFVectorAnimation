import pytest

from editor_fixtures import setcolor_of
from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.abc.rebind import rebind_setcolor
from autoswf.model.document import SetColorScript


@pytest.mark.parametrize("form", ["plain", "try", "activation"])
def test_rebinding_changes_the_location_in_every_official_form(form):
    abc = build_abc([ClassSpec("Kit_fla.Skin_1", ((0, SetColorScript("Skin", "Dark")),))], setcolor_form=form)
    out = rebind_setcolor(abc, "Kit_fla.Skin_1", "Hair", "Dark")
    assert setcolor_of(out, "Kit_fla.Skin_1") == ("Hair", "Dark")


def test_rebinding_keeps_the_other_classes_as_they_were():
    abc = build_abc([ClassSpec("Kit_fla.Skin_1", ((0, SetColorScript("Skin", "None")),)),
                     ClassSpec("Kit_fla.Eye_2", ((0, SetColorScript("Eye", "Light")),))])
    out = rebind_setcolor(abc, "Kit_fla.Skin_1", "Accessory", "Darker")
    assert setcolor_of(out, "Kit_fla.Skin_1") == ("Accessory", "Darker")
    assert setcolor_of(out, "Kit_fla.Eye_2") == ("Eye", "Light")


def test_a_class_without_a_color_script_is_refused():
    abc = build_abc([ClassSpec("Kit_fla.Plain_1")])
    with pytest.raises(ValueError, match="Kit_fla.Plain_1 has no AQW color script"):
        rebind_setcolor(abc, "Kit_fla.Plain_1", "Hair", "None")
