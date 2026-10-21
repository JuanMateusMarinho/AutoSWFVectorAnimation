import pytest

from editor_fixtures import rect_area, shape_of
from autoswf.app.controller import EditedArtError, ProjectController
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.edit.project_source import project_layer
from autoswf.model.shape import GradientFill, GradientStop, Shape, SolidFill, ellipse
from autoswf.model.geometry import Matrix
from autoswf.parts.assemble import with_extra_layers
from autoswf.project.aswf import load_project, save_project
from autoswf.project.build import HelmBuilder
from autoswf.project.edits import EDIT_GONE, ArtEdits, ExtraLayer, shape_from_json, shape_to_json
from autoswf.project.settings import HelmSettings

SCAR = shape_of({0: rect_area(200, 200, 230, 204)}, [(200, 60, 60, 255)])


def settings_for(psd) -> HelmSettings:
    return HelmSettings(source=str(psd.path), align=psd.align)


def same_shape(a: Shape, b: Shape) -> bool:
    return a.fills == b.fills and [(p.start, p.segments, p.fill_left, p.fill_right) for p in a.paths] == \
        [(p.start, p.segments, p.fill_left, p.fill_right) for p in b.paths]


def edit_of(build, part: str, area=None) -> ArtEdits:
    """An ArtEdits that paints a small line-colored patch on the part."""
    layer = project_layer(build, part)
    edit = layer.paint(area or rect_area(240, 150, 250, 160), layer.line_tone)
    edits = ArtEdits()
    for name, shape in edit.shapes.items():
        edits.set_shape(part, name, shape)
    return edits


def test_shape_json_round_trip():
    s = Shape([SolidFill((1, 2, 3, 255)), GradientFill("linear", (GradientStop(0, (0, 0, 0, 255)),
                                                                   GradientStop(255, (9, 8, 7, 128))), Matrix(2, 0, 0, 3, 4, 5))],
              [ellipse(0, 10, 10, 5, 4), ellipse(1, 30, 10, 5, 4)])
    assert same_shape(shape_from_json(shape_to_json(s)), s)


def test_settings_with_edits_round_trip_through_the_project_file(tmp_path, helm_psd):
    b = HelmBuilder().build(settings_for(helm_psd))
    s = settings_for(helm_psd)
    s.edits = edit_of(b, "Face")
    s.edits.extras.append(ExtraLayer("Scar", [(SCAR, "Skin", "Dark")]))
    save_project(tmp_path / "p.aswf", s, None)
    loaded = load_project(tmp_path / "p.aswf", tmp_path / "cache").settings
    assert loaded.edits.to_dict() == s.edits.to_dict()


def test_an_edited_part_keeps_its_vectors_after_a_color_change(helm_psd):
    builder = HelmBuilder()
    s = settings_for(helm_psd)
    s.edits = edit_of(builder.build(s), "Face")
    s.corrections.colors["Face"] = "Base"
    b = builder.build(s)
    assert b.error is None
    for key, shape in s.edits.shapes.items():
        traced = next(t for t in b.art.layers if "%s/%s" % (t.part, t.name) == key)
        assert same_shape(traced.shape, shape)
    assert any(c[:2] == ("Face", "Base") for c in b.helm.colorable)


def test_blink_and_sway_are_rebuilt_from_edited_art(helm_psd):
    builder = HelmBuilder(suggest=True)
    s = settings_for(helm_psd)
    first = builder.build(s)
    edits = edit_of(first, "Lock 1", rect_area(0, 0, 1, 1))
    lock = project_layer(first, "Lock 1")
    grown = lock.paint(rect_area(*_box_near(first, "Lock 1")), lock.tones[0].ref)
    for name, shape in grown.shapes.items():
        edits.set_shape("Lock 1", name, shape)
    eye = project_layer(first, "Eye L ball")
    for name, shape in eye.erase(rect_area(*_box_near(first, "Eye L ball", inside=True))).shapes.items():
        edits.set_shape("Eye L ball", name, shape)
    s.edits = edits
    b = builder.build(s)
    assert b.error is None and {"Eye L", "Lock 1"} <= set(b.timeline.clips)
    assert validate_helm_swf(b.swf, b.link) == []


def _box_near(build, part: str, inside: bool = False):
    from autoswf.edit.regions import bounds_px, fill_areas, union
    total = []
    for t in build.art.layers:
        if t.part == part:
            for a in fill_areas(t.shape).values():
                total = union(total, a)
    x0, x1, y0, y1 = bounds_px(total)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if inside:
        return cx - 1, cy - 1, cx + 1, cy + 1
    return x1 - 2, cy - 2, x1 + 4, cy + 2


def test_changing_the_detail_asks_before_replacing_edits(qapp, helm_psd, app_cache):
    controller = ProjectController(app_cache, threaded=False)
    controller.import_drawing(helm_psd.path, align=helm_psd.align)
    edits = edit_of(controller.build, "Face")
    controller.change("Brush", lambda s: setattr(s, "edits", edits))
    with pytest.raises(EditedArtError) as e:
        controller.change("Detail", lambda s: setattr(s, "detail", 70))
    assert e.value.parts == ["Face"] and controller.settings.detail == 50
    controller.change("Detail", lambda s: setattr(s, "detail", 70), edits_policy="keep")
    assert "Face" in controller.settings.edits.parts() and controller.settings.detail == 70
    controller.change("Detail", lambda s: setattr(s, "detail", 60), edits_policy="replace")
    assert controller.settings.edits.parts() == set() and controller.undo_stack.undoText() == "Detail"
    controller.undo_stack.undo()
    assert "Face" in controller.settings.edits.parts()


def test_color_changes_never_ask(qapp, helm_psd, app_cache):
    controller = ProjectController(app_cache, threaded=False)
    controller.import_drawing(helm_psd.path, align=helm_psd.align)
    edits = edit_of(controller.build, "Face")
    controller.change("Brush", lambda s: setattr(s, "edits", edits))
    controller.change("Face color", lambda s: s.corrections.colors.__setitem__("Face", "Base"))
    assert controller.settings.corrections.colors["Face"] == "Base"


def test_edits_for_a_part_that_is_gone_become_notes(helm_psd):
    s = settings_for(helm_psd)
    s.edits.set_shape("Lock 9", "Lock 9: Fills", SCAR)
    b = HelmBuilder().build(s)
    assert b.error is None and EDIT_GONE % "Lock 9" in b.notes


def test_extra_layers_get_their_own_wrapper_on_top(helm_psd):
    b = HelmBuilder().build(settings_for(helm_psd))
    helm = with_extra_layers(b.helm, [ExtraLayer("Scar", [(SCAR, "Skin", "Dark")])])
    root = helm.item.root.frames[0].placements
    top = max(root, key=lambda p: p.depth)
    assert top.item is helm.wrappers["Scar"] and ("Scar", "Skin", "Dark") in helm.colorable
    assert validate_helm_swf(export_helm(helm.item), b.link) == []


def test_extra_layers_come_out_of_the_build(helm_psd):
    s = settings_for(helm_psd)
    s.edits.extras.append(ExtraLayer("Scar", [(SCAR, None, "None")]))
    b = HelmBuilder().build(s)
    assert "Scar" in b.helm.wrappers and validate_helm_swf(b.swf, b.link) == []
