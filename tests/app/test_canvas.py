# tests/app/test_canvas.py
import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app_helpers import find_action, window
from autoswf.aqw.template import Alignment
from autoswf.model.geometry import Point


def aligned_window(helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.canvas.resize(600, 600)
    w.canvas.set_stage("Import")
    return w


def drag(canvas, start: QPointF, end: QPointF, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, modifier, start.toPoint())
    QTest.mouseMove(canvas, end.toPoint())
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, modifier, end.toPoint())


def test_dragging_the_drawing_moves_its_alignment_in_one_step(qapp, helm_psd, app_cache, tmp_path):
    w = aligned_window(helm_psd, app_cache, tmp_path)
    before = Alignment.parse(w.controller.settings.align)
    start = QPointF(w.canvas.widget_point(Point(0, 0)).toPoint())
    end = start + QPointF(round(10 * w.canvas.current_zoom()), 0)
    drag(w.canvas, start, end)
    moved = (end.x() - start.x()) / w.canvas.current_zoom()                       # head units, whole pixels
    after = Alignment.parse(w.controller.settings.align)
    assert w.controller.undo_stack.count() == 1 and w.controller.undo_stack.undoText() == "Alignment"
    assert after.origin[0] == pytest.approx(before.origin[0] - moved * before.scale, abs=0.01)
    assert after.scale == pytest.approx(before.scale)
    w.close()


def test_alt_drag_scales_and_shift_drag_rotates(qapp, helm_psd, app_cache, tmp_path):
    w = aligned_window(helm_psd, app_cache, tmp_path)
    before = Alignment.parse(w.controller.settings.align)
    start = w.canvas.widget_point(Point(0, 0)) + QPointF(0, -50)
    drag(w.canvas, start, start + QPointF(0, 100), Qt.KeyboardModifier.AltModifier)
    scaled = Alignment.parse(w.controller.settings.align)
    assert scaled.scale == pytest.approx(before.scale / math.exp(0.5), rel=0.02)     # down = bigger on the head
    origin = w.canvas.widget_point(Point(0, 0))
    drag(w.canvas, origin + QPointF(100, 0), origin + QPointF(0, 100), Qt.KeyboardModifier.ShiftModifier)
    turned = Alignment.parse(w.controller.settings.align)
    assert turned.rotation == pytest.approx(before.rotation + 90, abs=3)               # a quarter turn clockwise
    assert w.controller.undo_stack.count() == 2
    w.close()


def test_fit_to_head_returns_to_automatic_alignment(qapp, helm_psd, app_cache, tmp_path):
    w = aligned_window(helm_psd, app_cache, tmp_path)
    w.properties.show_stage("Import", w.controller.build, w.controller.settings)
    w.properties.fit_button.click()
    assert w.controller.settings.align is None and "fitted to the AQW head" in w.controller.build.alignment_reason
    w.close()


def parts_window(helm_psd, app_cache, tmp_path, threaded=False):
    w = window(app_cache, tmp_path, threaded=threaded)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.wait(240)
    w.canvas.resize(700, 700)
    w.canvas.set_stage("Parts")
    return w


def pick(monkeypatch, label, picked):
    def fake_exec(canvas, menu, pos):
        action = find_action(menu, label)
        picked.append(action.text())
        return action
    monkeypatch.setattr("autoswf.app.canvas.HelmCanvas.exec_menu", fake_exec)


def test_a_wrong_part_is_fixed_with_a_click_and_a_pick(qapp, helm_psd, app_cache, tmp_path, monkeypatch):
    w = parts_window(helm_psd, app_cache, tmp_path)
    parts = w.controller.build.parts
    x, y = parts.label_point("Lock 2")
    picked = []
    pick(monkeypatch, "Accessory 1", picked)
    QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=w.canvas.widget_point_of_drawing(x, y).toPoint())
    assert picked == ["Accessory 1"]                                         # action 1: click, action 2: pick
    [fix] = w.controller.settings.corrections.assign
    assert fix.part == "Accessory 1" and abs(fix.at[0] - x) <= 1 and abs(fix.at[1] - y) <= 1
    rid = parts.region_at(x, y).id
    assert w.controller.build.parts.part_of[rid] == "Accessory 1"
    w.close()


def test_the_fix_shows_at_once_while_the_build_runs(qapp, helm_psd, app_cache, tmp_path, monkeypatch):
    w = parts_window(helm_psd, app_cache, tmp_path, threaded=True)
    x, y = w.controller.build.parts.label_point("Lock 2")
    pick(monkeypatch, "Helm", [])
    QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=w.canvas.widget_point_of_drawing(x, y).toPoint())
    assert w.canvas.pending is not None and w.controller.busy
    w.controller.wait(240)
    assert w.canvas.pending is None
    w.close()


def test_cut_tool_adds_one_cut(qapp, helm_psd, app_cache, tmp_path):
    w = parts_window(helm_psd, app_cache, tmp_path)
    w.canvas.set_tool("cut")
    x, y = w.controller.build.parts.label_point("Face")
    points = [w.canvas.widget_point_of_drawing(x + dx, y).toPoint() for dx in (-30, 0, 30)]
    QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, points[0])
    for p in points[1:]:
        QTest.mouseMove(w.canvas, p)
    QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, points[-1])
    [cut] = w.controller.settings.corrections.cuts
    assert len(cut) >= 3 and abs(cut[0][0] - (x - 30)) <= 1 and w.controller.undo_stack.undoText() == "Cut region"
    w.controller.undo_stack.undo()
    assert w.controller.settings.corrections.cuts == []
    w.close()
