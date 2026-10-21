# tests/project/test_aswf.py
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawings import add_lock_on_the_left
from autoswf.anim.settings import ManualKey
from autoswf.drawing.writers import write_psd
from autoswf.project.aswf import PartSignature, load_project, match_parts, part_signatures, reimport, save_project
from autoswf.project.build import HelmBuilder
from autoswf.project.settings import HelmSettings


def project_with_work(psd):
    s = HelmSettings(source=str(psd.path), align=psd.align)
    s.animation.parts.update({"Lock 2": ("Sway", {"amplitude": 20}), "Eye L": ("Blink", {})})
    s.animation.keys.append(ManualKey("Lock 2", "Lock 2", 5, {"rotation": 4.0}))
    s.pivots["Lock 2"] = (1.0, 2.0)
    s.corrections.colors["Lock 2"] = "Trim"
    return s, HelmBuilder().build(s)


def test_save_and_open_keep_everything(helm_psd, tmp_path):
    s, b = project_with_work(helm_psd)
    save_project(tmp_path / "p.aswf", s, b)
    loaded = load_project(tmp_path / "p.aswf", tmp_path / "cache")
    assert loaded.settings.to_dict() == s.to_dict() and loaded.swf == b.swf and not loaded.source_changed
    assert {sig.name for sig in loaded.signatures} == set(b.parts.parts)
    with zipfile.ZipFile(tmp_path / "p.aswf") as z:
        assert z.read("source/Synthetic Helm.psd") == helm_psd.path.read_bytes()


def test_reopen_with_a_renamed_layer_and_a_missing_drawing(helm_psd, tmp_path):
    copy = tmp_path / "art" / "Synthetic Helm.psd"
    copy.parent.mkdir()
    copy.write_bytes(helm_psd.path.read_bytes())
    s, b = project_with_work(SimpleNamespace(path=copy, align=helm_psd.align))
    s.roles["Old layer name"] = "line"
    save_project(tmp_path / "p.aswf", s, b)
    copy.unlink()
    loaded = load_project(tmp_path / "p.aswf", tmp_path / "cache")
    assert "using the copy saved in the project" in loaded.notes[0]
    assert Path(loaded.settings.source).read_bytes() == helm_psd.path.read_bytes()
    built = HelmBuilder().build(loaded.settings)
    assert built.error and "Old layer name" in built.error


def test_bad_project_files_are_clear_errors(tmp_path):
    (tmp_path / "x.aswf").write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="x.aswf is not an AutoSWF project"):
        load_project(tmp_path / "x.aswf", tmp_path)
    with zipfile.ZipFile(tmp_path / "y.aswf", "w") as z:
        z.writestr("project.json", json.dumps({"format": "autoswf-project", "version": 2}))
    with pytest.raises(ValueError, match=r"made by a newer AutoSWF \(project version 2\)"):
        load_project(tmp_path / "y.aswf", tmp_path)


def test_parts_match_by_position_and_color():
    old = [PartSignature("Lock 1", "lock", (-20, -30), 40, (90, 60, 40)),
           PartSignature("Lock 2", "lock", (0, -32), 40, (90, 60, 40)),
           PartSignature("Ear L", "ear", (-45, 0), 30, (240, 200, 160))]
    new = [PartSignature("Lock 1", "lock", (-40, -30), 40, (90, 60, 40)),
           PartSignature("Lock 2", "lock", (-19, -31), 42, (90, 60, 40)),
           PartSignature("Lock 3", "lock", (1, -32), 40, (92, 60, 40))]
    assert match_parts(old, new) == {"Lock 1": "Lock 2", "Lock 2": "Lock 3"}


def test_reimport_keeps_matched_parts_and_lists_the_rest(helm_psd, tmp_path):
    s, b = project_with_work(helm_psd)
    old = part_signatures(b)
    t = helm_psd.t
    new_path = tmp_path / "v2.psd"
    write_psd(new_path, t.width, t.height, add_lock_on_the_left(t))
    s2 = s.copy()
    s2.source = str(new_path)
    b2 = HelmBuilder().build(s2)
    s3, report = reimport(s2, old, b2)
    assert report.renamed["Lock 2"] == "Lock 3" and "Lock 1" in report.new
    assert s3.animation.parts["Lock 3"] == ("Sway", {"amplitude": 20}) and "Lock 2" not in s3.animation.parts
    assert [(k.part, k.target) for k in s3.animation.keys] == [("Lock 3", "Lock 3")]
    assert s3.pivots == {"Lock 3": (1.0, 2.0)} and s3.corrections.colors == {"Lock 3": "Trim"}
    assert "Renamed: Lock 2 → Lock 3" in report.text()


@pytest.mark.parametrize("name", ["../../escaped.txt", r"..\..\escaped.txt", "C:/escaped.txt", "sub/../../x.psd"])
def test_a_crafted_project_never_writes_outside_its_cache_folder(tmp_path, name):
    import json
    import zipfile
    from autoswf.project.aswf import FORMAT, VERSION, load_project
    path = tmp_path / "evil.aswf"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"format": FORMAT, "version": VERSION, "settings": {"source": "x.psd"},
                                               "source": {"name": name, "path": r"\\attacker\share\x.psd"}}))
        z.writestr("source/" + name, b"payload")
    cache = tmp_path / "deep" / "cache"
    loaded = load_project(path, cache)
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p.read_bytes() == b"payload"]
    assert all(cache / "projects" in p.parents for p in written)
    assert loaded.saved_copy is None or (cache / "projects") in loaded.saved_copy.parents
    assert not loaded.settings.source.startswith(("\\\\", "//"))                 # never a network path (NTLM)
