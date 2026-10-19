# tests/app/test_controller.py
from autoswf.app.controller import ProjectController
from autoswf.aqw.validate import validate_helm_swf


def test_import_builds_a_valid_helm(qapp, helm_psd, app_cache):
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    assert c.build is c.helm_build and c.build.link == "SyntheticHelm"
    assert validate_helm_swf(c.build.swf, "SyntheticHelm") == [] and c.undo_stack.count() == 0


def test_changes_are_undoable_and_rebuild(qapp, helm_psd, app_cache):
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.change("Helm color", lambda s: s.corrections.colors.__setitem__("Helm", "Base"))
    assert c.undo_stack.undoText() == "Helm color" and any(x[:2] == ("Helm", "Base") for x in c.build.helm.colorable)
    c.undo_stack.undo()
    assert "Helm" not in c.settings.corrections.colors
    assert not any(x[:2] == ("Helm", "Base") for x in c.build.helm.colorable)
    c.undo_stack.redo()
    assert c.settings.corrections.colors["Helm"] == "Base"


def test_the_latest_settings_win_while_building(qapp, helm_psd, app_cache):
    c = ProjectController(app_cache, threaded=True)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    for detail in (40, 45, 55):
        c.change("Detail", lambda s, d=detail: setattr(s, "detail", d))
    c.undo_stack.undo()
    c.undo_stack.redo()
    b = c.wait(240)
    assert b is c.build and b.settings.detail == 55 and not c.busy
    c.close()


def test_a_failed_build_keeps_showing_the_last_good_helm(qapp, helm_psd, app_cache):
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    good = c.helm_build
    c.change("Roles", lambda s: s.roles.update({n: "ignore" for n in ("Flats", "Shadow", "Occlusion", "Light",
                                                                     "Details", "Line")}))
    assert c.build.error and c.helm_build is good


def test_accept_skip_and_fix(qapp, helm_psd, app_cache):
    from autoswf.project.suggest import suggestions
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    blink, sway, twitch = suggestions(c.build, c.settings)
    c.accept(blink)
    assert set(c.build.timeline.clips) == {"Eye L", "Eye R"} and c.undo_stack.undoText() == "Accept suggestion"
    c.skip(twitch)
    assert c.settings.animation.parts["Ear L"] == (None, {})
    stages = []
    c.stage_requested.connect(stages.append)
    c.fix(sway)
    assert stages == ["Parts"] and c.selected_part == "Lock 1"


def test_rerunning_a_preset_asks_before_replacing_hand_made_keys(qapp, helm_psd, app_cache):
    import pytest
    from autoswf.anim.settings import ManualKey
    from autoswf.anim.timeline import ManualEditsError
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.set_animation("Lock 2", "Sway")
    c.add_key("Lock 2", "Lock 2", 5)
    with pytest.raises(ManualEditsError):
        c.set_preset_value("Lock 2", "amplitude", 20)
    c.set_preset_value("Lock 2", "amplitude", 20, edits="keep")
    assert c.settings.animation.parts["Lock 2"] == ("Sway", {"amplitude": 20})
    assert len([k for k in c.settings.animation.keys if k.part == "Lock 2"]) == 1
    c.set_animation("Lock 2", "Twitch", edits="replace")
    assert [k for k in c.settings.animation.keys if k.part == "Lock 2"] == []
