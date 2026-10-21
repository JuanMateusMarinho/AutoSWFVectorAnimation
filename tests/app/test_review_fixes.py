"""Regression tests for the Plan 7 final review's findings (C1, I1-I7, I9)."""
from PIL import Image
from PySide6.QtWidgets import QFileDialog

from aqw_fakes import _disc, _holder
from app_helpers import window
from editor_fixtures import (CORRECT_EDGE, LINE_RGBA, SKIN_RGBA, face_like_png, part_by_key, polygon_area,
                             rect_area, shape_of, strip_face_armor)
from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.edit.layer import Drawing, EditLayer, Tone, ToneRef
from autoswf.edit.regions import bounds_px, union
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.swf.movie import build_swf

from test_edit_tools import click, drag, opened, pick


def _two_frame_armor() -> bytes:
    """Head: frame 1 places a clip, frame 2 the same clip 100 px to the right; inside it a 2-frame clip shows
    drawing A then drawing B at one depth."""
    a = shape_of({0: rect_area(0, 0, 40, 40)}, [SKIN_RGBA])
    b = shape_of({0: rect_area(0, 0, 40, 20)}, [LINE_RGBA])
    flip = Symbol("Flip", [Frame([Placement(a, 1)]), Frame([Placement(b, 1)])])
    inner = Symbol("Inner", [Frame([Placement(flip, 1)])])
    head = Symbol("Head", [Frame([Placement(inner, 1)], "Portrait"), Frame([Placement(inner, 1, Matrix.translate(100, 0))], "Idle")])
    parts = {"Head": head}
    for part in ("Chest", "Hip", "Shoulder", "Hand", "Thigh", "Shin", "Foot", "FootIdle", "Robe", "RobeBack"):
        parts[part] = _holder(part, _disc((90, 110, 140, 255), 6, 9))
    names = {id(s): "TwoM%s" % part for part, s in parts.items()}
    return build_swf(list(parts.values()), names, build_abc([ClassSpec(n) for n in names.values()]))


def _all(layer):
    out = []
    for area in layer.visible_areas().values():
        out = union(out, area)
    return out


# ---------------------------------------------------------------- C1


def test_two_quick_helm_strokes_both_land(qapp, tmp_path, helm_psd, app_cache):
    w = window(app_cache, tmp_path, threaded=True)
    c = w.controller
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.wait(240)
    c.select_part("Face")
    w.canvas.resize(900, 800)
    w.canvas.render_image(900, 800)
    pick(w, "eraser")
    x0, x1, y0, y1 = bounds_px(_all(w.helm_tools.layer))
    cy = (y0 + y1) / 2
    first, second = (x0 + (x1 - x0) * 0.35, cy), (x0 + (x1 - x0) * 0.65, cy)
    assert w.helm_tools.layer.tone_at(*first) is not None and w.helm_tools.layer.tone_at(*second) is not None
    w.helm_tools.set_size(3)
    drag(w.canvas, [first, (first[0] + 0.5, first[1])])
    drag(w.canvas, [second, (second[0] + 0.5, second[1])])
    c.wait(240)
    layer = w.helm_tools.layer
    assert layer.tone_at(*first) is None and layer.tone_at(*second) is None
    c.close()


# ---------------------------------------------------------------- I1


def test_deleting_a_new_layer_drops_it(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    e.layers_panel.new_layer_requested.emit()
    pick(w, "brush")
    e.edit_tools.set_color((0, 200, 0, 255))
    e.edit_tools.set_size(6)
    drag(e.canvas, [(120, 220), (160, 220)])
    new_path = part_by_key(e.structure, "MHead").pieces[-1].path
    e.delete_layer(new_path)
    assert e.edits.layers == [] and len(part_by_key(e.structure, "MHead").pieces) == 2
    assert e.current_data() == e.original
    e.undo_stack.undo()
    assert len(e.edits.layers) == 1


# ---------------------------------------------------------------- I2


def test_strokes_follow_the_part_frame(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache, _two_frame_armor(), "MHead/1")
    assert e.frame_strip.count == 2
    e.frame_strip.frame_changed.emit(1)
    assert e.frame == 1 and e.edit_tools.layer.drawings[0].matrix.tx == 100


def test_the_canvas_shows_the_drawing_being_edited(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache, _two_frame_armor(), "MHead/1/1/1.2")
    edited = e.edit_tools.layer.drawings[0].key
    assert e.displayed_char("MHead/1/1/1.2") == int(edited)


# ---------------------------------------------------------------- I3


def test_stage_tools_work_after_an_edit_tool(qapp, tmp_path, helm_psd, app_cache):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    pick(w, "brush")
    assert w.helm_tools.active
    w.set_stage("Parts")
    assert not w.helm_tools.active and not w.edit_actions["brush"].isChecked()


# ---------------------------------------------------------------- I4


def test_a_stroke_does_not_rebuild_the_options_bar(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    count = []
    e.edit_tools.changed.connect(lambda: count.append(1))
    drag(e.canvas, [(100 + k, 200) for k in range(20)])
    assert len(count) <= 3


def test_the_options_bar_shows_few_swatches_for_many_tones(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    tones = [Tone(ToneRef("d", k), (k % 7, 0, 0, 255) if k % 2 else (k, k, k, 255), None) for k in range(120)]
    e.edit_tools.set_layer(EditLayer("Many", [Drawing("d", shape_of({}, []), Matrix(), False)], tones, None, 1.0))
    w.tool_options.attach(e.edit_tools)
    assert 1 <= w.tool_options.swatches.count() <= 24


# ---------------------------------------------------------------- I5


def test_structure_edits_refresh_only_what_changed(qapp, tmp_path, app_cache, monkeypatch):
    import autoswf.app.swf_editor as swf_editor
    w, e = opened(tmp_path, app_cache, path="MHead/1/2")
    chest = e.tree_item("MChest")
    monkeypatch.setattr(swf_editor, "read_structure", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-read")))
    e.layers_panel.color_requested.emit("MHead/1/2", "Hair")
    assert e.structure.piece("MHead/1/2").color == ("Hair", "Dark")
    e.layers_panel.new_layer_requested.emit()
    pick(w, "brush")
    e.edit_tools.set_color((0, 200, 0, 255))
    drag(e.canvas, [(120, 220), (160, 220)])
    assert len(part_by_key(e.structure, "MHead").pieces) == 3 and e.tree_item("MChest") is chest


# ---------------------------------------------------------------- I6


def test_helm_trace_cancel_adds_nothing_and_names_are_unique(qapp, tmp_path, helm_psd, app_cache, monkeypatch):
    w = window(app_cache, tmp_path)
    c = w.controller
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.select_part("Face")
    png = tmp_path / "piece.png"
    Image.fromarray(face_like_png()).save(png)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(png), "")))
    w.swf_editor.ask_trace_target = lambda name: None
    w.helm_layers.trace_requested.emit()
    assert c.settings.edits.extras == []
    w.swf_editor.ask_trace_target = lambda name: "new"
    w.helm_layers.trace_requested.emit()
    w.helm_layers.trace_requested.emit()
    assert [x.name for x in c.settings.edits.extras] == ["Traced layer 1", "Traced layer 2"]


# ---------------------------------------------------------------- I7


def test_a_png_of_the_drawings_canvas_lands_where_the_drawing_is(qapp, tmp_path, helm_psd, app_cache):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    build = w.controller.helm_build
    size = (build.passes.width, build.passes.height)
    assert w.helm_trace_matrix(size, (10, 20, 10, 20), None) == build.alignment.matrix()


# ---------------------------------------------------------------- I9


def test_saving_clears_the_swf_dirty_flag_and_the_question_names_edits(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    drag(e.canvas, [(100, 100), (120, 100)])
    assert e.dirty
    text = w.discard_question()
    assert "0 removed" not in text and "changes" in text
    assert w._save(tmp_path / "work.aswf") and not e.dirty
