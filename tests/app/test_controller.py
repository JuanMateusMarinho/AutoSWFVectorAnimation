# tests/app/test_controller.py
import pytest

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


def _lock_project(helm_psd, app_cache, tmp_path, threaded):
    """A saved project whose Lock 2 sways with amplitude 20, then a lock drawn on the left (Lock 2 becomes Lock 3)."""
    from drawings import add_lock_on_the_left
    from autoswf.drawing.writers import write_psd
    drawing = tmp_path / "Helm.psd"
    drawing.write_bytes(helm_psd.path.read_bytes())
    c = ProjectController(app_cache, threaded=threaded)
    c.import_drawing(drawing, align=helm_psd.align)
    c.wait()
    c.set_animation("Lock 2", "Sway", {"amplitude": 20})
    c.wait()
    c.save(tmp_path / "p.aswf")
    return c, drawing, lambda: write_psd(drawing, helm_psd.t.width, helm_psd.t.height, add_lock_on_the_left(helm_psd.t))


@pytest.mark.parametrize("threaded", [False, True])
def test_reopening_a_changed_drawing_moves_the_work_onto_the_renamed_parts(qapp, helm_psd, app_cache, tmp_path,
                                                                           threaded):
    c, drawing, change_drawing = _lock_project(helm_psd, app_cache, tmp_path, threaded)
    c.close()
    change_drawing()
    c2 = ProjectController(app_cache, threaded=threaded)
    assert c2.open_project(tmp_path / "p.aswf").source_changed
    c2.wait()                                       # the build of the changed drawing ends before the user answers
    reports = []
    c2.reimport_drawing(reports.append)
    c2.wait()
    assert reports[0].renamed["Lock 2"] == "Lock 3"
    assert c2.settings.animation.parts["Lock 3"] == ("Sway", {"amplitude": 20})
    c2.close()


def test_a_drawing_changed_while_open_is_matched_with_the_parts_before_the_change(qapp, helm_psd, app_cache, tmp_path):
    c, drawing, change_drawing = _lock_project(helm_psd, app_cache, tmp_path, False)
    change_drawing()
    c._on_source_changed(str(drawing))              # what the file watcher does
    c.set_color_slot("Eye L", "Eye")                # an edit rebuilds from the changed drawing
    reports = []
    c.reimport_drawing(reports.append)
    assert reports[0].renamed["Lock 2"] == "Lock 3"
    assert c.settings.animation.parts["Lock 3"] == ("Sway", {"amplitude": 20}) and "Lock 7" not in reports[0].kept


def test_saving_before_the_re_import_still_offers_it_on_reopening(qapp, helm_psd, app_cache, tmp_path):
    c, drawing, change_drawing = _lock_project(helm_psd, app_cache, tmp_path, False)
    change_drawing()
    c._on_source_changed(str(drawing))
    c.set_color_slot("Eye L", "Eye")
    c.save()                                        # the work still names the parts of the drawing before the change
    c2 = ProjectController(app_cache, threaded=False)
    assert c2.open_project(tmp_path / "p.aswf").source_changed
    reports = []
    c2.reimport_drawing(reports.append)
    assert reports[0].renamed["Lock 2"] == "Lock 3"


def test_the_window_asks_before_retracing_edited_parts(qapp, helm_psd, app_cache, tmp_path):
    from app_helpers import window
    from editor_fixtures import rect_area
    from autoswf.edit.project_source import project_layer
    from autoswf.project.edits import ArtEdits
    w = window(app_cache, tmp_path)
    c = w.controller
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    layer = project_layer(c.build, "Face")
    edits = ArtEdits()
    for name, shape in layer.paint(rect_area(240, 150, 250, 160), layer.line_tone).shapes.items():
        edits.set_shape("Face", name, shape)
    c.change("Brush", lambda s: setattr(s, "edits", edits))
    asked = []
    w.ask_edits_policy = lambda parts: asked.append(parts)
    c.change("Detail", lambda s: setattr(s, "detail", 70))
    assert asked == [["Face"]] and c.settings.detail == 50
    w.ask_edits_policy = lambda parts: "keep"
    c.change("Detail", lambda s: setattr(s, "detail", 70))
    assert c.settings.detail == 70 and "Face" in c.settings.edits.parts()
