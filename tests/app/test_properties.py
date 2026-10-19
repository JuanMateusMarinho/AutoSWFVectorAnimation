# tests/app/test_properties.py
from app_helpers import window


def test_detail_applies_on_release_as_one_step(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.properties.show_stage("Vectorize", w.controller.build, w.controller.settings)
    s = w.properties.detail_slider
    s.setSliderDown(True)
    s.setValue(60)
    s.setValue(70)
    s.setSliderDown(False)
    assert w.controller.settings.detail == 70 and w.controller.undo_stack.count() == 1
    w.close()


def test_alignment_fields_set_the_alignment(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.properties.show_stage("Import", w.controller.build, w.controller.settings)
    w.properties.rotation_spin.setValue(5.0)
    w.properties.rotation_spin.editingFinished.emit()
    assert w.controller.settings.align.split(",")[3] == "5" and w.controller.undo_stack.undoText() == "Alignment"
    w.close()


def test_preset_sliders_use_the_preset_ranges(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Lock 1", "Sway")
    w.controller.select_part("Lock 1")
    w.properties.show_stage("Animate")
    amp = w.properties.param_widgets["amplitude"]
    assert (amp.spin.minimum(), amp.spin.maximum()) == (0, 45)
    amp.spin.setValue(30)
    amp.spin.editingFinished.emit()
    assert w.controller.settings.animation.parts["Lock 1"] == ("Sway", {"amplitude": 30.0})
    box = w.properties.preset_box
    assert [box.itemText(i) for i in range(box.count())] == ["None", "Sway", "Twitch", "Pulse"]
    w.close()


def test_color_slot_and_player_colors(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.select_part("Helm")
    w.properties.show_stage("Colors")
    w.properties.color_box.setCurrentText("Base")
    assert w.controller.settings.corrections.colors == {"Helm": "Base"}
    w.properties.set_player_color("Base", 0x00FF00)
    assert w.controller.settings.colors == {"Base": 0x00FF00} and w.canvas.colors.base == 0x00FF00
    w.close()


def test_dragging_the_pivot_sets_it_in_one_step(qapp, helm_psd, app_cache, tmp_path):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from autoswf.model.geometry import Point
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Lock 1", "Sway")
    w.controller.select_part("Lock 1")
    w.canvas.resize(700, 700)
    w.set_stage("Animate")
    before = w.controller.build.rigs["Lock 1"].pivot
    count = w.controller.undo_stack.count()
    start = QPointF(w.canvas.widget_point(before).toPoint())
    end = start + QPointF(round(4 * w.canvas.current_zoom()), 0)
    QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start.toPoint())
    QTest.mouseMove(w.canvas, end.toPoint())
    QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end.toPoint())
    x, y = w.controller.settings.pivots["Lock 1"]
    moved = (end.x() - start.x()) / w.canvas.current_zoom()
    assert abs(x - (before.x + moved)) < 0.3 and abs(y - before.y) < 0.3
    assert w.controller.undo_stack.count() == count + 1 and w.controller.undo_stack.undoText() == "Pivot"
    w.close()


def test_gender_adjustments_show_on_the_canvas(qapp, helm_psd, app_cache, tmp_path):
    from autoswf.project.settings import Adjust
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.canvas.set_stage("Colors")
    plain = w.canvas.render_image(300, 300)
    w.controller.set_adjust("F", None, Adjust(x=6))
    assert w.controller.settings.export.variants
    w.canvas.set_gender("F")
    w.canvas.guide_opacity = 0
    shifted = w.canvas.render_image(300, 300)
    w.canvas.set_gender("M")
    unshifted = w.canvas.render_image(300, 300)
    w.canvas.guide_opacity = 1
    assert shifted != unshifted and w.canvas.render_image(300, 300) == plain
    w.close()
