# tests/items/test_animated.py
import pytest

from aqw_fakes import animated_armor_swf, mini_armor_with_pieces
from autoswf.items.animated import read_animated_armor
from autoswf.swf.decode import MovieData


def test_an_animated_armor_is_recognized():
    armor = read_animated_armor(MovieData(animated_armor_swf()))
    assert armor.class_name == "TestAnimMHead" and armor.labels == {"Idleing": 2, "Walking": 9, "Attack1": 19}
    assert armor.table() == [("Idle", "Idleing", False), ("Walk", "Walking", True), ("Attack1", "Attack1", False),
                             ("Fight", "Attack1", False)]
    assert armor.notes == []
    assert read_animated_armor(MovieData(mini_armor_with_pieces("M"))) is None


@pytest.mark.real
def test_azrael_guardian_armor(azrael):
    armor = read_animated_armor(MovieData(azrael))
    assert armor.labels == {"Idleing": 2, "Walking": 9, "Attack1": 22, "Attack2": 72, "Attack3": 166}
    assert len(armor.listeners) == 44 and [b for g, _, b in armor.table() if b] == [True]
    assert ("Walk", "Walking", True) in armor.table() and ("Attack1", "Attack1", False) in armor.table()
    assert armor.notes == []


def test_an_armor_that_registers_its_listeners_from_methods_is_recognized():
    from aqw_fakes import listener_armor_swf
    armor = read_animated_armor(MovieData(listener_armor_swf()))
    assert armor.class_name == "TestBindMHead" and armor.labels == {"Portrait": 0, "Idle": 1, "Walk": 2, "Slash": 3}
    assert armor.table() == [("Idle", "Idle", False), ("Fight", "Idle", True), ("Walk", "Walk", True),
                             ("Attack1", "Slash", True), ("Attack2", "Slash", True)]
    assert armor.motions() == ["Portrait", "Idle", "Walk", "Slash"] and armor.notes == []


def test_a_mapping_that_cannot_be_read_still_gives_the_motions():
    from aqw_fakes import listener_armor_swf
    armor = read_animated_armor(MovieData(listener_armor_swf(readable=False)))
    assert armor.table() == [] and armor.motions() == ["Portrait", "Idle", "Walk", "Slash"]
    assert any("cannot be read" in note for note in armor.notes)


@pytest.mark.real
def test_the_sword_hero(the_sword_hero):
    armor = read_animated_armor(MovieData(the_sword_hero))
    assert armor.class_name == "TheSwordHeroMHead" and len(armor.listeners) == 54 and armor.notes == []
    assert armor.motions() == ["Portrait", "Idle", "Walk", "SolarSlash", "CrossFlare", "DawnBurst", "Hit", "Dead"]
    table = armor.table()
    for row in (("Idle", "Idle", False), ("Walk", "Walk", True), ("Attack1", "SolarSlash", True),
                ("Attack2", "CrossFlare", True), ("Cast1", "DawnBurst", True), ("Hit", "Hit", True),
                ("Dead", "Dead", True), ("Getup", "Idle", True)):
        assert row in table
