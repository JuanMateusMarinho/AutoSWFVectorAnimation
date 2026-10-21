import json
import zipfile

import pytest

from editor_fixtures import LINE_RGBA, part_by_key, rect_area, shape_of, strip_face_armor
from autoswf.items.item_edits import ItemEdits
from autoswf.items.layers import NewLayer
from autoswf.items.structure import read_structure
from autoswf.project.aswf import load_item_project, load_project, project_kind, save_item_project
from autoswf.swf.decode import MovieData


def edits_for(armor: bytes) -> ItemEdits:
    structure = read_structure(MovieData(armor))
    head = part_by_key(structure, "MHead")
    line_id = structure.piece("MHead/1/3").char_id
    return ItemEdits(removed=[structure.piece("MHead/2").ref],
                     shapes={line_id: shape_of({0: rect_area(0, 0, 50, 3)}, [LINE_RGBA])},
                     layers=[NewLayer(head.char_id, "Scar", [(shape_of({0: rect_area(10, 10, 20, 12)}, [(9, 9, 9, 255)]),
                                                              ("Skin", "Dark"))])],
                     rebinds={"StripHero_fla.Shadow_2": ("Hair", "Dark")})


def test_item_project_round_trip(tmp_path):
    armor = strip_face_armor()
    edits = edits_for(armor)
    save_item_project(tmp_path / "x.aswf", armor, "StripHero.swf", edits)
    assert project_kind(tmp_path / "x.aswf") == "item"
    loaded = load_item_project(tmp_path / "x.aswf")
    assert loaded.original == armor and loaded.name == "StripHero.swf"
    assert loaded.edits.apply(armor) == edits.apply(armor)


def test_helm_projects_of_version_1_still_open(tmp_path, helm_psd):
    doc = {"format": "autoswf-project", "version": 1, "source": {"name": helm_psd.path.name, "path": str(helm_psd.path)},
           "settings": {"source": str(helm_psd.path)}, "parts": []}
    with zipfile.ZipFile(tmp_path / "old.aswf", "w") as z:
        z.writestr("project.json", json.dumps(doc))
    assert project_kind(tmp_path / "old.aswf") == "helm"
    assert load_project(tmp_path / "old.aswf", tmp_path / "cache").settings.source == str(helm_psd.path)


def test_a_newer_item_project_is_refused(tmp_path):
    with zipfile.ZipFile(tmp_path / "new.aswf", "w") as z:
        z.writestr("project.json", json.dumps({"format": "autoswf-project", "version": 3, "kind": "item"}))
    with pytest.raises(ValueError, match="was made by a newer AutoSWF"):
        load_item_project(tmp_path / "new.aswf")
