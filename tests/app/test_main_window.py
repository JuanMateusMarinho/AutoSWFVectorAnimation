# tests/app/test_main_window.py
from PySide6.QtGui import QPalette

from app_helpers import window
from autoswf.app.theme import apply_dark_theme
from autoswf.aqw.assets import AqwCache


def test_shortcuts_follow_animate(qapp, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    keys = {name: a.shortcut().toString() for name, a in w.actions.items()}
    assert keys["play"] == "Return" and keys["preview"] == "Ctrl+Return" and keys["insert_frame"] == "F5"
    assert keys["insert_keyframe"] == "F6" and keys["undo"] == "Ctrl+Z" and keys["redo"] == "Ctrl+Y"
    assert keys["export"] == "Ctrl+Alt+Shift+S" and keys["import"] == "Ctrl+R" and keys["timeline"] == "Ctrl+Alt+T"
    w.close()


def test_opening_a_drawing_fills_the_stage_bar(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    states = w.stage_bar.states
    assert w.stage_bar.current == "Import" and states["Vectorize"][0] == "done"
    assert states["Animate"][0] == "attention" and states["Export"][0] == "todo"
    assert w.windowTitle() == "AutoSWF — Synthetic Helm.psd"
    w.close()


def test_without_aqw_files_the_app_still_builds_and_says_how_to_get_them(qapp, helm_psd, tmp_path):
    empty = AqwCache(tmp_path / "nothing")
    w = window(empty, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    assert w.controller.helm_build.swf and "not downloaded" in w.canvas.banner_text
    image = w.canvas.render_image(200, 200)
    assert any(image.pixelColor(x, y) != image.pixelColor(0, 0) for x in range(60, 140, 4) for y in range(60, 140, 4))
    w.close()


def test_first_run_asks_once_to_download(qapp, tmp_path, monkeypatch):
    from autoswf.app import window as win
    asked = []
    monkeypatch.setattr(win.QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or win.QMessageBox.StandardButton.No)
    for _ in range(2):
        w = window(AqwCache(tmp_path / "nothing"), tmp_path)
        w.first_run()
        w.close()
    assert len(asked) == 1 and "never shared" in asked[0]


def test_canvas_draws_the_guide_head_for_the_chosen_gender(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    assert w.canvas.guide_class == "mcHeadM"
    w.actions["toggle_gender"].trigger()
    assert w.canvas.guide_class == "mcHeadF" and w.canvas.gender == "F"
    w.close()


def test_dark_theme(qapp):
    apply_dark_theme(qapp)
    assert qapp.palette().color(QPalette.ColorRole.Window).lightness() < 80
