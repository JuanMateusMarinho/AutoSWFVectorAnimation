# tests/project/test_export.py
import pytest

from autoswf.aqw.assets import AqwCache
from autoswf.aqw.validate import validate_helm_swf
from autoswf.project.build import HelmBuilder
from autoswf.project.export import export_files, export_problems
from autoswf.project.settings import Adjust, HelmSettings, Variant
from autoswf.swf.decode import MovieData
from autoswf.swf.reader import SWF


def built(psd, **kw):
    s = HelmSettings(source=str(psd.path), align=psd.align, **kw)
    builder = HelmBuilder()
    return builder, builder.build(s), s


def test_export_writes_a_valid_helm_and_reports(helm_psd, tmp_path, app_cache):
    builder, b, s = built(helm_psd)
    s.export.file = str(tmp_path / "Out.swf")
    [r] = export_files(builder, b, s, app_cache)
    assert r.ok and r.link == "Out" and r.path.read_bytes()[:3] == b"CWS"
    assert validate_helm_swf(r.path.read_bytes(), "Out") == [] and "Out.swf" in r.summary() and "valid" in r.summary()
    assert any("Not animated yet" in n for n in r.notes)


def test_back_hair_can_be_left_out(backhair_psd, tmp_path, app_cache):
    builder, b, s = built(backhair_psd)
    s.export.file, s.export.back_hair = str(tmp_path / "NoBack.swf"), False
    [r] = export_files(builder, b, s, app_cache)
    assert r.ok and "NoBack_backhair" not in SWF(r.path.read_bytes()).symbols.values()
    s.export.file, s.export.back_hair = str(tmp_path / "Back.swf"), True
    [r] = export_files(builder, b, s, app_cache)
    assert "Back_backhair" in SWF(r.path.read_bytes()).symbols.values()


def face_tx(data, link):
    movie = MovieData(data)
    root = movie.character(movie.classes[link])
    return next(c.matrix.tx for c in root.frames[0] if c.name == "face")


def test_gender_versions_write_two_files_with_their_adjustments(helm_psd, tmp_path, app_cache):
    builder, b, s = built(helm_psd)
    plain = export_files(builder, b, HelmSettings.from_dict({**s.to_dict(), "export": {"file": str(tmp_path / "H.swf")}}),
                         app_cache)[0]
    s.export.variants = True
    s.export.genders = {"M": Variant(str(tmp_path / "HM.swf"), "HM", Adjust(x=2.0)),
                        "F": Variant(str(tmp_path / "HF.swf"), "HF", Adjust(scale=0.9), {"Lock 1": Adjust(y=1.5)})}
    rm, rf = export_files(builder, b, s, app_cache)
    assert (rm.gender, rf.gender) == ("M", "F") and rm.ok and rf.ok
    base = face_tx(plain.path.read_bytes(), "H")
    assert face_tx(rm.path.read_bytes(), "HM") == pytest.approx(base + 2.0, abs=0.05)
    assert face_tx(rf.path.read_bytes(), "HF") == pytest.approx(base * 0.9, abs=0.05)


def test_bad_names_and_paths_are_refused(helm_psd, tmp_path):
    s = HelmSettings(source=str(helm_psd.path))
    s.export.variants = True
    s.export.genders = {"M": Variant(str(tmp_path / "Same.swf"), "Same"), "F": Variant(str(tmp_path / "Same.swf"), "Same")}
    problems = export_problems(s)
    assert any("different files" in p for p in problems) and any("different links" in p for p in problems)
    s.export.variants, s.export.link, s.export.file = False, "class", str(helm_psd.path)
    problems = export_problems(s)
    assert any("reserved word" in p for p in problems) and any("would overwrite the drawing" in p for p in problems)


def test_unwritable_folder_reports_and_leaves_nothing(helm_psd, tmp_path, app_cache):
    builder, b, s = built(helm_psd)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    s.export.file = str(blocker / "Out.swf")
    [r] = export_files(builder, b, s, app_cache)
    assert not r.ok and r.problems[0].startswith("Could not write") and not list(tmp_path.glob("**/*.part"))


def test_morph_check_reports_per_gender(helm_psd, tmp_path, app_cache):
    builder, b, s = built(helm_psd)
    s.export.file, s.export.morph = str(tmp_path / "M.swf"), True
    [r] = export_files(builder, b, s, app_cache)
    assert any(n.startswith("Morph check:") for n in r.notes)


def test_morph_check_without_aqw_files_is_a_note(helm_psd, tmp_path):
    builder, b, s = built(helm_psd)
    s.export.file, s.export.morph = str(tmp_path / "M.swf"), True
    [r] = export_files(builder, b, s, AqwCache(tmp_path / "none"))
    assert r.ok and any("Morph check skipped" in n for n in r.notes)


def test_size_warning(helm_psd, tmp_path, app_cache, monkeypatch):
    from autoswf.project import export as ex
    monkeypatch.setattr(ex, "SIZE_WARNING_BYTES", 100)
    builder, b, s = built(helm_psd)
    s.export.file = str(tmp_path / "Big.swf")
    [r] = export_files(builder, b, s, app_cache)
    assert any("larger than 200 KB" in n for n in r.notes)
