# tests/app/test_app_acceptance.py
"""Plan 6 done means: (1) a helm from drawing to validated male/female files through a saved project, every element
in its own layer (spec §9.4); (2) KindOfBrave.swf opened, its quiver and chest strap removed, previewed and exported
valid. Both run through the objects the window drives."""
from pathlib import Path

import pytest

from aqw_fakes import mini_client
from autoswf.app.controller import ProjectController
from autoswf.app.swf_editor import SwfEditor
from autoswf.aqw.validate import validate_helm_swf, validate_item_swf
from autoswf.preview.scene import PreviewScene
from autoswf.project.player import HelmPlayer
from autoswf.project.settings import Adjust, Variant
from autoswf.project.suggest import suggestions
from autoswf.render.effects import qimage_to_array
from autoswf.swf.decode import MovieData


def test_a_helm_from_drawing_to_versions_through_a_saved_project(qapp, helm_psd, app_cache, tmp_path):
    c = ProjectController(app_cache, threaded=False)
    c.import_drawing(helm_psd.path, align=helm_psd.align)
    x, y = c.build.parts.label_point("Accessory 1")
    c.assign_region((x, y), "Helm")                                           # a fix: click + pick
    for s in suggestions(c.build, c.settings):
        (c.accept if s.preset else c.skip)(s)
    c.set_preset_value("Lock 1", "amplitude", 18)
    c.add_key("Eye L", "Eye L lid", 11)
    c.set_color_slot("Helm", "Base")
    c.save(tmp_path / "helm.aswf")
    c2 = ProjectController(app_cache, threaded=False)
    loaded = c2.open_project(tmp_path / "helm.aswf")
    assert not loaded.source_changed and Path(c2.settings.source).samefile(c.settings.source)
    assert {**c2.settings.to_dict(), "source": ""} == {**c.settings.to_dict(), "source": ""}

    def versions(s):
        s.export.variants = True
        s.export.genders.update({"M": Variant(str(tmp_path / "HM.swf"), "HM"),
                                 "F": Variant(str(tmp_path / "HF.swf"), "HF", Adjust(scale=0.95))})
    c2.change("Versions", versions)
    results = []
    c2.export(results.extend)
    assert [r.ok for r in results] == [True, True]
    for r in results:
        data = r.path.read_bytes()
        assert validate_helm_swf(data, r.link) == [] and len(data) < 60 * 1024
        assert HelmPlayer(data, r.link).length == 87
        movie = MovieData(data)                         # spec §9.4: one layer per element, never merged
        names = [cmd.name for cmd in movie.character(movie.classes[r.link]).frames[0]]
        assert len(names) == len(set(names))
        assert {"face", "eyeL", "eyeR", "hair", "lock1", "lock6", "earL", "helm"} <= set(names)


@pytest.mark.real
def test_kind_of_brave_in_the_app(qapp, kind_of_brave, app_cache, tmp_path):
    e = SwfEditor(app_cache)
    assert e.open(kind_of_brave) is None
    e.set_removed(e.structure.piece("MRobeBack/1").ref, True)
    e.set_removed(e.structure.piece("MChest/39").ref, True)
    d = e.export_dialog()
    d.file_edit.setText(str(tmp_path / "KOB.swf"))
    d.export_button.click()
    out = (tmp_path / "KOB.swf").read_bytes()
    assert validate_item_swf(out, e.structure.public_classes(), e.original).ok
    assert "valid" in d.report.toPlainText()
    sc = PreviewScene(MovieData(mini_client()), {"M": MovieData(out)}, "KindOfBrave", genders=("M",))
    assert qimage_to_array(sc.snapshot(400, 300))[..., 3].max() > 0
