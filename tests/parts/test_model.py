import json

import pytest
from autoswf.parts.model import Assign, Corrections, PartName, default_location, folder_kind


def test_part_names_round_trip_and_z_order():
    for text in ("Face", "Ear L", "Eye R", "Brow L", "Mouth", "Nose", "Hair", "Lock 3", "Back hair", "Horn R",
                 "Helm", "Accessory 2"):
        assert PartName.parse(text).name == text
    assert PartName.parse(" lock  3 ") == PartName("lock", index=3) and PartName.parse("eye l") == PartName("eye", "L")
    names = sorted((PartName.parse(n) for n in ("Helm", "Face", "Lock 2", "Lock 1", "Eye R", "Eye L", "Hair")),
                   key=lambda p: p.z)
    assert [p.name for p in names] == ["Face", "Eye L", "Eye R", "Hair", "Lock 1", "Lock 2", "Helm"]
    for bad in ("Lok 2", "Eye", "Lock", "Lock 0", "Face L", "Hair 2"):
        with pytest.raises(ValueError, match="Unknown part '%s'; parts are named Face, Ear L/R" % bad):
            PartName.parse(bad)


def test_default_locations_and_folder_words():
    assert [default_location(k, p) for k, p in (("face", None), ("lock", None), ("eye", "iris"), ("eye", "white"),
                                                ("shell", None), ("brow", None))] == ["Skin", "Hair", "Eye", None, None, "Hair"]
    assert [folder_kind(n) for n in ("Cabelo", "Back Hair", "Cabelo de trás", "Olhos", "Chapéu", "Acessórios",
                                     "後ろ髪", "Sketch", "Hair 2")] == \
        ["hair", "back_hair", "back_hair", "eye", "shell", "accessory", "back_hair", None, "hair"]


def test_corrections_file_round_trip(tmp_path):
    c = Corrections([Assign((512.0, 300.0), "Lock 2"), Assign((400.0, 310.0), "Eye L", "iris")],
                    [[(100.0, 200.0), (140.0, 260.0)]], {"Helm": "Base", "Brow L": "none"})
    c.save(tmp_path / "h.parts.json")
    assert Corrections.load(tmp_path / "h.parts.json") == c
    (tmp_path / "empty.parts.json").write_text("{}")
    assert Corrections.load(tmp_path / "empty.parts.json") == Corrections()


@pytest.mark.parametrize("data, message", [
    ({"assign": [{"at": [1, 2], "part": "Lok 2"}]}, "entry 1 of \"assign\": Unknown part 'Lok 2'"),
    ({"assign": [{"at": [1, 2], "part": "Face", "piece": "iris"}]}, "only eyes have pieces"),
    ({"assign": [{"at": [1, 2], "part": "Eye L", "piece": "lens"}]}, "Unknown eye piece 'lens'"),
    ({"assign": [{"at": "here", "part": "Face"}]}, "\"at\" must be two numbers"),
    ({"cuts": [[[0, 0]]]}, "a cut needs at least two points"),
    ({"colors": {"Helm": "Gold"}}, "Unknown color 'Gold'; use Skin, Hair, Eye, Base, Trim, Accessory or none"),
    ({"colors": {"Lok": "Base"}}, "Unknown part 'Lok'"),
    ({"shapes": []}, "Unknown key 'shapes'"),
])
def test_bad_corrections_are_clear_errors(tmp_path, data, message):
    path = tmp_path / "x.parts.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="x.parts.json: .*" + message.replace("(", r"\(").replace(")", r"\)")):
        Corrections.load(path)


def test_invalid_json_names_the_file(tmp_path):
    (tmp_path / "x.parts.json").write_text("{nope")
    with pytest.raises(ValueError, match=r"x.parts.json is not valid JSON \(line 1"):
        Corrections.load(tmp_path / "x.parts.json")
