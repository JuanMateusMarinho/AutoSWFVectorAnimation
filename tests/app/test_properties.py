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
