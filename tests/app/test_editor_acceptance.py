"""Plan 7 acceptance (spec §11): the user's three-step fix on a look-alike of TheSwordHero's head, end to end in the
window (brush, Magic Wand, Delete, export, save, reopen), and helm projects keeping one layer per element and their
colors and animation through edits and Trace PNG."""
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt

from app_helpers import window
from editor_fixtures import CORRECT_EDGE, STRIP_CENTER, rect_area, strip_face_armor, swf_tags
from autoswf.aqw.validate import validate_helm_swf, validate_item_swf
from autoswf.edit.project_source import project_layer
from autoswf.edit.regions import bounds_px, union
from autoswf.edit.swf_source import swf_layer
from autoswf.edit.trace_png import new_layer_tones, placement, replace_layer, trace_png
from autoswf.items.structure import read_structure
from autoswf.project.build import HelmBuilder
from autoswf.project.edits import ArtEdits, ExtraLayer
from autoswf.project.settings import HelmSettings
from autoswf.swf.decode import MovieData

from test_edit_tools import click, drag, key, opened, pick


def export(w, out) -> bytes:
    dialog = w.swf_editor.export_dialog()
    dialog.file_edit.setText(str(out))
    dialog.export()
    return out.read_bytes()


def test_the_users_fix_on_a_look_alike_of_the_sword_hero(qapp, tmp_path, app_cache):
    original = strip_face_armor()
    w, e = opened(tmp_path, app_cache, original)
    e.set_hidden("MHead/2", True)                                   # the hair, as the user hid it
    pick(w, "brush")
    e.edit_tools.set_size(3)
    drag(e.canvas, [(s.x, s.y) for s in CORRECT_EDGE])
    pick(w, "wand")
    click(e.canvas, *STRIP_CENTER)
    key(e.canvas, Qt.Key.Key_Delete)
    out = export(w, tmp_path / "out.swf")
    before, after = swf_tags(original), swf_tags(out)
    assert len(before) == len(after)
    assert {code for (code, a), (_, b) in zip(before, after) if a != b} == {83}  # only edited drawings changed
    structure = read_structure(MovieData(original))
    assert validate_item_swf(out, structure.public_classes(), original=original).ok
    movie = MovieData(out)
    layer = swf_layer(movie, read_structure(movie), "MHead/1", 0)
    assert layer.tone_at(*STRIP_CENTER) is None
    middle = CORRECT_EDGE[len(CORRECT_EDGE) // 2]
    assert layer.tone_at(middle.x, middle.y) == layer.line_tone
    assert w._save(tmp_path / "fix.aswf")
    w2 = window(app_cache, tmp_path / "again")
    assert w2.open_path(tmp_path / "fix.aswf") is None
    assert export(w2, tmp_path / "again.swf") == out


def _settings(psd) -> HelmSettings:
    return HelmSettings(source=str(psd.path), align=psd.align)


def test_one_layer_per_element_survives_edits(helm_psd):
    builder = HelmBuilder(suggest=True)
    s = _settings(helm_psd)
    first = builder.build(s)
    edits = ArtEdits()
    for part in ("Face", "Lock 1"):
        layer = project_layer(first, part)
        box = bounds_px(_all(layer))
        for name, shape in layer.paint(rect_area(box[0], box[2], box[0] + 3, box[2] + 3), layer.line_tone).shapes.items():
            edits.set_shape(part, name, shape)
    s.edits = edits
    b = builder.build(s)
    root = b.helm.item.root.frames[0].placements
    assert len({p.depth for p in root}) == len(root)
    assert b.helm.placements["Face"] in root and b.helm.placements["Lock 1"] in root
    assert b.helm.placements["Face"].depth != b.helm.placements["Lock 1"].depth
    assert validate_helm_swf(b.swf, b.link) == []


def _all(layer):
    out = []
    for area in layer.visible_areas().values():
        out = union(out, area)
    return out


def test_trace_png_on_a_helm_project_keeps_color_and_animation(helm_psd):
    builder = HelmBuilder(suggest=True)
    s = _settings(helm_psd)
    first = builder.build(s)
    lock = project_layer(first, "Lock 1")
    drawn = [d.shape.fills[0].color for d in lock.drawings]
    img = Image.new("RGBA", (80, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((5, 5, 75, 115), fill=drawn[0])
    d.ellipse((5, 5, 75, 115), outline=drawn[-1], width=3)
    traced = trace_png(np.array(img))
    matrix = placement(traced.size, target_bounds=bounds_px(_all(lock)))
    edit = replace_layer(lock, traced, matrix)
    assert edit.notes == []
    s.edits = ArtEdits()
    for name, shape in edit.shapes.items():
        s.edits.set_shape("Lock 1", name, shape)
    bound = [t for t in lock.tones if t.binding]
    tones = [(shape, b[0] if b else None, b[1] if b else "None") for shape, b in new_layer_tones(traced, matrix, bound)]
    s.edits.extras.append(ExtraLayer("Traced layer", tones))
    b = builder.build(s)
    assert b.error is None and "Lock 1" in b.timeline.clips
    assert any(c[:2] == ("Lock 1", "Hair") for c in b.helm.colorable)
    assert "Traced layer" in b.helm.wrappers and any(c[:2] == ("Traced layer", "Hair") for c in b.helm.colorable)
    assert validate_helm_swf(b.swf, b.link) == []
