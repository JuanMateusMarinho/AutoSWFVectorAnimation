import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QInputDevice, QMouseEvent, QPointingDevice, QTabletEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from aqw_fakes import mini_armor_with_pieces
from app_helpers import window
from editor_fixtures import (CORRECT_EDGE, STRIP_CENTER, height_at, rect_area, strip_face_armor)
from autoswf.edit.layer import ToneRef
from autoswf.edit.regions import intersection
from autoswf.model.geometry import Point

PEN = QPointingDevice("pen", 1, QInputDevice.DeviceType.Stylus, QPointingDevice.PointerType.Pen,
                      QInputDevice.Capability.Position | QInputDevice.Capability.Pressure, 1, 3)
NONE = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


def opened(tmp_path, app_cache, data=None, path="MHead/1"):
    w = window(app_cache, tmp_path)
    f = tmp_path / "StripHero.swf"
    f.write_bytes(data or strip_face_armor())
    assert w.open_path(f) is None
    e = w.swf_editor
    e.select(path)
    e.canvas.resize(900, 800)
    e.canvas.render_image(900, 800)          # lays out the view
    return w, e


def at(canvas, x, y) -> QPointF:
    p = canvas.layer_matrix().apply(Point(x, y))
    return QPointF(p.x, p.y)


def mouse(canvas, kind, pos, modifiers=NONE):
    button = LEFT if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, canvas.mapToGlobal(pos), button, LEFT, modifiers))


def drag(canvas, points, modifiers=NONE):
    mouse(canvas, QEvent.Type.MouseButtonPress, at(canvas, *points[0]), modifiers)
    for x, y in points[1:]:
        mouse(canvas, QEvent.Type.MouseMove, at(canvas, x, y), modifiers)
    mouse(canvas, QEvent.Type.MouseButtonRelease, at(canvas, *points[-1]), modifiers)


def click(canvas, x, y, modifiers=NONE):
    drag(canvas, [(x, y)], modifiers)


def tablet(canvas, points, pressures):
    kinds = [QEvent.Type.TabletPress] + [QEvent.Type.TabletMove] * (len(points) - 2) + [QEvent.Type.TabletRelease]
    for kind, (x, y), p in zip(kinds, points, pressures):
        pos = at(canvas, x, y)
        QApplication.sendEvent(canvas, QTabletEvent(kind, PEN, pos, canvas.mapToGlobal(pos), p, 0.0, 0.0, 0.0, 0.0,
                                                    0.0, NONE, LEFT, LEFT))


def key(widget, k, modifiers=NONE):
    QTest.keyClick(widget, k, modifiers)


def pick(w, tool):
    w.edit_actions[tool].trigger()


def strip_is_transparent(e) -> bool:
    return e.edit_tools.layer.tone_at(*STRIP_CENTER) is None


def test_tool_shortcuts_pick_tools(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    for k, tool in ((Qt.Key.Key_V, "move"), (Qt.Key.Key_B, "brush"), (Qt.Key.Key_W, "wand"), (Qt.Key.Key_E, "eraser"),
                    (Qt.Key.Key_I, "eyedropper")):
        w.edit_actions[tool].trigger()
        assert e.edit_tools.tool == tool and e.edit_tools.active
    assert [w.edit_actions[t].shortcut().toString() for t in ("move", "brush", "wand", "eraser", "eyedropper")] == \
        ["V", "B", "W", "E", "I"]


def test_a_tablet_stroke_tapers_and_a_mouse_stroke_does_not(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    e.edit_tools.set_size(6)
    line = e.edit_tools.layer.line_tone
    tablet(e.canvas, [(100 + 5 * k, 100) for k in range(21)], [k / 10 if k <= 10 else (20 - k) / 10 for k in range(21)])
    drawn = intersection(e.edit_tools.layer.visible_areas()[line], rect_area(0, 90, 400, 110))   # the stroke only
    assert height_at(drawn, 150) > 4 * height_at(drawn, 101)
    drag(e.canvas, [(100 + 5 * k, 200) for k in range(21)])
    drawn = intersection(e.edit_tools.layer.visible_areas()[line], rect_area(0, 190, 400, 210))
    assert height_at(drawn, 101) == pytest.approx(height_at(drawn, 150), abs=0.5)


def test_the_three_step_fix_in_the_swf_workspace_is_three_undo_steps(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    e.edit_tools.set_size(3)
    drag(e.canvas, [(s.x, s.y) for s in CORRECT_EDGE])
    pick(w, "wand")
    click(e.canvas, *STRIP_CENTER)
    key(e.canvas, Qt.Key.Key_Delete)
    assert e.undo_stack.count() == 3 and strip_is_transparent(e)
    for _ in range(3):
        e.undo_stack.undo()
    assert e.edits.shapes == {} and not strip_is_transparent(e)
    for _ in range(3):
        e.undo_stack.redo()
    assert strip_is_transparent(e)


def test_move_drags_the_selection_or_the_whole_layer(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "wand")
    click(e.canvas, 60, 140)
    pick(w, "move")
    drag(e.canvas, [(60, 140), (75, 140), (90, 140)])
    shadow = e.edit_tools.layer.tone_at(100, 140)
    assert shadow is not None and e.edit_tools.layer.tone_at(45, 140) is None
    key(e.canvas, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert e.edit_tools.selection is None
    before = set(e.edits.shapes)
    drag(e.canvas, [(150, 150), (155, 150)])
    assert len(set(e.edits.shapes) - before) >= 1 and len(e.edits.shapes) == len(e.edit_tools.layer.drawings)


def test_a_no_op_stroke_adds_no_undo_step(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "eraser")
    drag(e.canvas, [(-200, -200), (-150, -200)])
    assert e.undo_stack.count() == 0


def test_alt_click_picks_the_tone_under_the_cursor(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    click(e.canvas, 60, 140, Qt.KeyboardModifier.AltModifier)
    assert e.edit_tools.color == e.edit_tools.layer.tone_at(60, 140) and e.undo_stack.count() == 0


def test_space_drag_pans_and_ctrl_0_fits(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    before = e.canvas.layer_matrix()
    QTest.keyPress(e.canvas, Qt.Key.Key_Space)
    mouse(e.canvas, QEvent.Type.MouseButtonPress, QPointF(100, 100))
    mouse(e.canvas, QEvent.Type.MouseMove, QPointF(160, 130))
    mouse(e.canvas, QEvent.Type.MouseButtonRelease, QPointF(160, 130))
    QTest.keyRelease(e.canvas, Qt.Key.Key_Space)
    e.canvas.render_image(900, 800)
    moved = e.canvas.layer_matrix()
    assert (moved.tx - before.tx, moved.ty - before.ty) == pytest.approx((60, 30)) and e.undo_stack.count() == 0
    key(e.canvas, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    e.canvas.render_image(900, 800)
    assert e.canvas.layer_matrix() == before


def test_bracket_keys_change_the_brush_size(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "brush")
    e.edit_tools.set_size(10)
    key(e.canvas, Qt.Key.Key_BracketRight)
    assert e.edit_tools.size == pytest.approx(11)
    key(e.canvas, Qt.Key.Key_BracketLeft)
    assert e.edit_tools.size == pytest.approx(10)


def test_editing_a_shared_drawing_asks_once(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache, mini_armor_with_pieces(), "MChest/3")
    asked = []
    e.ask_shared_edit = lambda places: asked.append(places) or True
    gem = str(e.structure.piece("MShoulder/3/1").char_id)
    pick(w, "brush")
    e.edit_tools.set_color(ToneRef(gem, 0))
    e.edit_tools.set_size(2)
    drag(e.canvas, [(3, 2), (4, 3)])
    drag(e.canvas, [(3, 4), (4, 5)])
    assert len(asked) == 1 and any(p.startswith("MShoulder") for p in asked[0])
    assert int(gem) in e.edits.shapes


def test_ctrl_t_scales_the_selection_and_esc_cancels(qapp, tmp_path, app_cache):
    w, e = opened(tmp_path, app_cache)
    pick(w, "wand")
    click(e.canvas, 60, 140)
    key(e.canvas, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert e.edit_tools.transforming
    drag(e.canvas, [(80, 160), (90, 170), (100, 180)])
    key(e.canvas, Qt.Key.Key_Escape)
    assert not e.edit_tools.transforming and e.undo_stack.count() == 1          # only the wand click
    key(e.canvas, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    drag(e.canvas, [(80, 160), (90, 170), (100, 180)])
    key(e.canvas, Qt.Key.Key_Return)
    assert e.undo_stack.count() == 2 and e.edit_tools.layer.tone_at(95, 175) is not None


def test_a_helm_edit_shows_at_once_and_lands_after_the_build(qapp, tmp_path, helm_psd, app_cache):
    w = window(app_cache, tmp_path, threaded=True)
    c = w.controller
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.wait(240)
    c.select_part("Face")
    canvas = w.canvas
    canvas.resize(900, 800)
    canvas.render_image(900, 800)
    pick(w, "brush")
    assert canvas.edit_tools.layer is not None and canvas.edit_tools.layer.name == "Face"
    drag(canvas, [(0, 0), (2, 1), (4, 2)])
    assert canvas.pending_layer is not None
    c.wait(240)
    assert canvas.pending_layer is None and "Face" in c.settings.edits.parts()
    c.close()
