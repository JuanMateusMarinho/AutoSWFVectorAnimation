# tests/app/test_parts_panel.py
from app_helpers import window


def test_part_tree_and_canvas_share_the_selection(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    w.parts_tree.select("Lock 3")
    assert w.controller.selected_part == "Lock 3" and w.canvas.selected == "Lock 3"
    assert [w.parts_tree.topLevelItem(i).text(0) for i in range(3)] == ["Face", "Ears", "Eyes"]
    w.controller.select_part("Eye R")
    assert w.parts_tree.currentItem().text(0) == "Eye R"
    w.close()


def test_a_fix_can_be_removed_from_the_list(qapp, helm_psd, app_cache, tmp_path):
    w = window(app_cache, tmp_path)
    w.controller.import_drawing(helm_psd.path, align=helm_psd.align)
    x, y = w.controller.build.parts.label_point("Lock 2")
    w.controller.assign_region((x, y), "Helm")
    w.properties.show_stage("Parts")
    assert len(w.properties.fix_rows) == 1 and "Helm" in w.properties.fix_rows[0].text
    w.properties.fix_rows[0].remove_button.click()
    assert w.controller.settings.corrections.assign == [] and w.controller.undo_stack.count() == 2
    w.close()
