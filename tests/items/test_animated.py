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
