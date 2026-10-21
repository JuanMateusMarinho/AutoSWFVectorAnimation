from PIL import Image

from app_helpers import window
from editor_fixtures import (face_like_png, part_by_key, rect_area, setcolor_of, strip_face_armor)
from autoswf.edit.layer import ToneRef
from autoswf.items.structure import read_structure
from autoswf.model.geometry import Point
from autoswf.swf.decode import MovieData

from test_edit_tools import at, drag, opened, pick


def test_rows_show_color_tags_and_notes(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache, strip_face_armor(hair_drawings=3))
    rows = e.layer_rows()
    assert "Skin Color" in [r.color_tag for r in rows] and "3 frames" in [r.note for r in rows]
    assert [r.key for r in rows][:2] == ["MHead/1", "MHead/1/1"]


def test_eye_hides_only_in_the_editor(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    p = e.canvas.layer_matrix().apply(Point(300, 40))
    before = e.canvas.render_image(900, 800).pixelColor(int(p.x), int(p.y))
    e.set_hidden("MHead/2", True)
    after = e.canvas.render_image(900, 800).pixelColor(int(p.x), int(p.y))
    assert before != after
    assert any(piece.path == "MHead/2" for piece in read_structure(MovieData(e.current_data())).walk())


def test_delete_layer_removes_the_piece_from_the_item(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    e.delete_layer("MHead/2")
    assert not any(p.path == "MHead/2" for p in read_structure(MovieData(e.current_data())).walk())
    e.undo_stack.undo()
    assert any(p.path == "MHead/2" for p in read_structure(MovieData(e.current_data())).walk())


def test_color_menu_rebinds_a_swf_layer_and_a_helm_part(qapp, tmp_path, app_cache, helm_psd):
    w, e = opened(tmp_path, app_cache, path="MHead/1/2")
    e.layers_panel.color_requested.emit("MHead/1/2", "Hair")
    abc = next(iter(MovieData(e.current_data())._abc_blocks))
    assert setcolor_of(abc, "StripHero_fla.Shadow_2") == ("Hair", "Dark") and e.undo_stack.count() == 1
    assert e.structure.piece("MHead/1/2").color == ("Hair", "Dark")
    w2 = window(app_cache, tmp_path / "helm")
    w2.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w2.helm_layers.color_requested.emit("Face", "Base")
    assert w2.controller.settings.corrections.colors["Face"] == "Base"


def test_trace_png_replace_and_new_from_the_panel(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    png = tmp_path / "face.png"
    Image.fromarray(face_like_png()).save(png)
    e.ask_png_path = lambda: png
    e.ask_trace_target = lambda name: "replace"
    e.place_png = lambda size, layer_bounds: __import__("autoswf.model.geometry", fromlist=["Matrix"]).Matrix()
    e.layers_panel.trace_requested.emit()
    assert e.undo_stack.count() == 1 and e.edit_tools.layer.tone_at(285, 100) is None
    e.ask_trace_target = lambda name: "new"
    e.layers_panel.trace_requested.emit()
    assert e.undo_stack.count() == 2 and len(e.edits.layers) == 1
    assert len(part_by_key(e.structure, "MHead").pieces) == 3


def test_frame_strip_marks_frames_with_the_same_drawing(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache, strip_face_armor(hair_drawings=3), path="MHead/2")
    assert e.frame_strip.count == 3 and e.frame_strip.marks == [0]
    first = e.edit_tools.layer.drawings[0].key
    e.frame_strip.frame_changed.emit(2)
    assert e.layer_frame == 2 and e.edit_tools.layer.drawings[0].key != first and e.frame_strip.marks == [2]


def test_part_selector_switches_armor_parts(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    e.layers_panel.part_selected.emit("MChest")
    assert e.current_part().key == "MChest"


def test_new_layer_then_brush_paints_a_fixed_color(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    e.layers_panel.new_layer_requested.emit()
    assert e.edit_tools.layer.name == "New layer"
    pick(w, "brush")
    e.edit_tools.set_color((0, 200, 0, 255))
    e.edit_tools.set_size(6)
    drag(e.canvas, [(120, 220), (160, 220)])
    assert len(e.edits.layers) == 1 and e.undo_stack.count() == 1
    assert e.edit_tools.layer.tone_at(140, 220) is not None
