# tests/items/test_structure.py
import pytest

from aqw_fakes import hair_swf, helm, labeled_item_swf, mini_armor_with_pieces, root_weapon_swf
from autoswf.items.structure import PieceRef, read_structure
from autoswf.swf.decode import MovieData
from swf_builders import swf


def walk(st):
    def visit(pieces):
        for p in pieces:
            yield p
            yield from visit(p.children)
    for part in st.parts:
        yield from visit(part.pieces)


def test_armor_parts_and_pieces():
    st = read_structure(MovieData(mini_armor_with_pieces("M")))
    assert (st.kind, st.link, st.genders) == ("armor", "TestArmor", ("M",))
    assert [p.key for p in st.parts][:3] == ["MChest", "MHip", "MShoulder"]
    chest = st.parts[0]
    assert chest.label == "Chest (male)" and [c.label for c in chest.pieces] == ["Skin (None)", "Vest", "Strap"]
    strap_stud = st.piece("MChest/5/1")                               # the Stud placed on the Strap's own timeline
    assert strap_stud.ref.depth == 1 and st.instances(strap_stud.ref) == ["MChest/5/1"]
    gem = st.piece("MChest/5/1/1")                                    # the Gem inside the Stud definition: shown 3 times
    assert sorted(st.instances(gem.ref)) == ["MChest/3/2/1", "MChest/5/1/1", "MShoulder/3/1"]
    assert st.piece("MHead/1").instance_name == "Face"
    blinker = st.piece("MHead/3")
    assert blinker.kind == "clip" and [c.ref.depth for c in blinker.children] == [1, 2]
    with pytest.raises(KeyError, match="MChest/9"):
        st.piece("MChest/9")
    assert "TestArmorMChest" in st.public_classes() and "TestArmor_fla.Skin_1" not in st.public_classes()


def test_structure_of_every_item_kind():
    helm_st = read_structure(MovieData(helm("Kit")))
    assert helm_st.kind == "helm" and [p.key for p in helm_st.parts] == ["Helm", "Backhair"]
    assert read_structure(MovieData(helm("Kit", backhair=False))).kind == "item"
    assert read_structure(MovieData(labeled_item_swf("TestCape", ("Idle", "Move")))).kind == "cape"
    assert read_structure(MovieData(labeled_item_swf("TestPet", ("Ready", "Idle", "Walk")))).kind == "pet"
    hair = read_structure(MovieData(hair_swf()))
    assert hair.kind == "hair" and [p.key for p in hair.parts] == ["MHair", "MHairBack"]
    weapon = read_structure(MovieData(root_weapon_swf()))
    assert weapon.kind == "weapon" and weapon.parts[0].key == "Root" and weapon.parts[0].pieces
    with pytest.raises(ValueError, match="No AQW item classes were found in empty.swf"):
        read_structure(MovieData(swf([])), "empty.swf")


@pytest.mark.real
def test_kind_of_brave(kind_of_brave):
    st = read_structure(MovieData(kind_of_brave))
    assert (st.kind, st.link, st.genders, len(st.parts)) == ("armor", "KindOfBrave", ("M",), 11)
    chest = next(p for p in st.parts if p.key == "MChest")
    assert [c.ref.depth for c in chest.pieces] == [1, 7, 39]
    assert len(st.piece("MRobeBack/1").children) == 7
    assert {p.color for p in walk(st) if p.color} == {("Skin", "None"), ("Skin", "Dark"), ("Skin", "Darker"),
                                                      ("Eye", "None"), ("Eye", "Light"), ("Hair", "None")}
    assert st.instances(PieceRef(110, 39)) == ["MChest/39"] and st.instances(PieceRef(31, 1)) == ["MRobeBack/1"]


def test_a_part_that_shows_other_characters_later_lists_each_with_its_label():
    from aqw_fakes import listener_armor_swf
    st = read_structure(MovieData(listener_armor_swf()))
    head = next(p for p in st.parts if p.key == "MHead")
    assert [p.label for p in head.pieces] == ["Portrait: headOnly", "Idle: body", "Walk: body", "Slash: body"]
    assert [p.frame for p in head.pieces] == [0, 1, 2, 3] and [len(p.children) for p in head.pieces] == [0, 1, 2, 4]
    assert [c.label for c in head.pieces[2].children] == ["Frame 1: Shape %d" % head.pieces[2].children[0].char_id,
                                                          "Frame 2: Shape %d" % head.pieces[2].children[1].char_id]
    assert len({p.ref for p in head.pieces}) == 1
    assert st.instances(head.pieces[0].ref) == [p.path for p in head.pieces]
    assert st.piece(head.pieces[2].path) is head.pieces[2]
