from autoswf.edit.project_source import extra_layer, project_layer
from autoswf.project.build import HelmBuilder
from autoswf.project.edits import ExtraLayer
from autoswf.project.settings import HelmSettings

from editor_fixtures import rect_area, shape_of


def test_project_layer_matches_the_built_part(helm_psd):
    b = HelmBuilder().build(HelmSettings(source=str(helm_psd.path), align=helm_psd.align))
    layer = project_layer(b, "Face")
    assert [d.key for d in layer.drawings] == [t.name for t in b.art.layers if t.part == "Face"]
    assert not any(d.colorable for d in layer.drawings)
    bindings = {t.binding for t in layer.tones}
    assert ("Skin", "None") in bindings and ("Skin", "Dark") in bindings
    assert layer.line_tone is not None and layer.line_tone.drawing == "Face: Line"
    assert 1.0 <= layer.line_width <= 8.0


def test_an_eye_layer_holds_its_ball_and_lid(helm_psd):
    b = HelmBuilder().build(HelmSettings(source=str(helm_psd.path), align=helm_psd.align))
    keys = [d.key for d in project_layer(b, "Eye L").drawings]
    assert keys == [t.name for t in b.art.layers if t.part in ("Eye L ball", "Eye L lid")]


def test_extra_layer_is_editable(helm_psd):
    s = HelmSettings(source=str(helm_psd.path), align=helm_psd.align)
    s.edits.extras.append(ExtraLayer("Scar", [(shape_of({0: rect_area(0, 0, 10, 2)}, [(9, 9, 9, 255)]), None, "None")]))
    layer = extra_layer(HelmBuilder().build(s), "Scar")
    assert [t.binding for t in layer.tones] == [None] and layer.tone_at(5, 1) is not None
