# tests/app/test_timeline_view.py
from app_helpers import window


def test_f6_makes_a_hand_made_key_and_shift_f6_clears_it(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Eye L", "Blink")
    w.timeline.select_cell("Eye L", "Eye L lid", 11)
    w.actions["insert_keyframe"].trigger()
    [key] = w.controller.settings.animation.keys
    assert (key.part, key.target, key.frame) == ("Eye L", "Eye L lid", 12) and "bend" not in key.fields
    assert w.timeline.selected_key == ("Eye L", "Eye L lid", 11) and not w.properties.groups["Keyframe"].isHidden()
    w.properties.key_widgets["y"].setValue(9.0)
    w.properties.key_widgets["y"].editingFinished.emit()
    assert w.controller.settings.animation.keys[0].fields["y"] == 9.0
    w.actions["clear_keyframe"].trigger()
    assert w.controller.settings.animation.keys == []
    w.close()


def test_f5_lengthens_the_selected_loop(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Lock 1", "Sway", {"length": 240})
    w.timeline.select_cell("Lock 1", "Lock 1", 0)
    w.actions["insert_frame"].trigger()                                          # already at the maximum
    assert w.controller.settings.animation.parts["Lock 1"][1]["length"] == 240
    w.actions["remove_frame"].trigger()
    assert w.controller.settings.animation.parts["Lock 1"][1]["length"] == 239
    w.close()


def test_enter_plays_at_24_fps_and_loops(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Lock 1", "Sway", {"length": 12})
    w.actions["play"].trigger()
    assert w.timeline.playing and w.timeline.timer.interval() == round(1000 / 24)
    for _ in range(13):
        w.timeline.advance()
    assert w.timeline.playhead == 1 and w.canvas.frame == 1
    w.actions["play"].trigger()
    assert not w.timeline.playing
    w.close()


def test_onion_skin_draws_neighbouring_frames(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.controller.set_animation("Eye L", "Blink")
    w.set_stage("Animate")
    w.timeline.select_cell("Eye L", "Eye L ball", 11)
    plain = w.canvas.render_image(400, 400)
    w.timeline.onion_box.setChecked(True)
    assert w.canvas.onion and w.canvas.render_image(400, 400) != plain
    assert w.canvas.onion_frames(0, 87) == (86, 1)
    w.close()
