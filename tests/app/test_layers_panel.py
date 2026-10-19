# tests/app/test_layers_panel.py
from app_helpers import window


def test_layers_show_roles_and_changing_one_rebuilds(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    rows = w.layers.rows()
    assert rows["Line"][0] == "Auto (line)" and rows["Line"][1] == "name"
    w.layers.set_role("Details", "Not used")
    assert w.controller.settings.roles == {"Details": "ignore"} and w.controller.undo_stack.undoText() == "Layer role"
    assert w.layers.rows()["Details"][0] == "Not used"
    w.layers.set_role("Details", "Auto (details)")
    assert w.controller.settings.roles == {}
    w.close()


def test_soft_tone_layers_can_become_gradients(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.layers.set_gradient("Light", True)
    assert w.controller.settings.gradient == ["Light"] and w.controller.undo_stack.undoText() == "Gradient"
    w.close()
