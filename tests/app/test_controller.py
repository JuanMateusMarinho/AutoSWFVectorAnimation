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
