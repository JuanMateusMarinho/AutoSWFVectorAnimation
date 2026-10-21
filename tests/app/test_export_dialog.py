# tests/app/test_export_dialog.py
import zlib

from autoswf.app.controller import ProjectController
from autoswf.app.export_dialog import ExportDialog


def test_dialog_checks_names_live_and_fills_gender_defaults(qapp, helm_psd, app_cache, tmp_path):
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    d = ExportDialog(c)
    d.file_edit.setText(str(tmp_path / "Crown.swf"))
    assert d.link_edit.text() == "Crown" and d.export_button.isEnabled()
    d.link_edit.setText("class")
    assert not d.export_button.isEnabled() and "reserved word" in d.link_message.text()
    d.link_edit.setText("Crown")
    d.variants_box.setChecked(True)
    (mf, ml), (ff, fl) = d.gender_rows["M"], d.gender_rows["F"]
    assert (ml.text(), fl.text()) == ("CrownM", "CrownF") and mf.text().endswith("CrownM.swf")


def test_export_waits_for_the_current_settings(qapp, helm_psd, app_cache, tmp_path):
    c = ProjectController(app_cache, threaded=True)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    c.change("Helm color", lambda s: s.corrections.colors.__setitem__("Helm", "Trim"))
    c.change("File", lambda s: setattr(s.export, "file", str(tmp_path / "Now.swf")))
    results = []
    c.export(results.extend)
    c.wait(240)
    assert results and results[0].ok and b"Trim" in zlib.decompress(results[0].path.read_bytes()[8:])
    c.close()


def test_saved_version_names_are_kept_when_the_dialog_opens_again(qapp, helm_psd, app_cache, tmp_path):
    from autoswf.project.settings import Variant
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)

    def versions(s):
        s.export.file, s.export.variants = str(tmp_path / "Hat.swf"), True
        s.export.genders["M"] = Variant(str(tmp_path / "HatMale.swf"), "HatMale")
    c.change("Versions", versions)
    d = ExportDialog(c)
    (mf, ml), (ff, fl) = d.gender_rows["M"], d.gender_rows["F"]
    assert (mf.text(), ml.text()) == (str(tmp_path / "HatMale.swf"), "HatMale")
    assert fl.text() == "HatF"                       # a version never named by hand still follows the main name
    d.file_edit.setText(str(tmp_path / "Crown.swf"))
    assert ml.text() == "HatMale" and fl.text() == "CrownF"
