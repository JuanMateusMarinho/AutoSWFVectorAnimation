import pytest

from autoswf.aqw.contract import internal_class_name, sanitize_link


def test_sanitize_link():
    assert sanitize_link("Crystallis Onsen Morph 4") == "CrystallisOnsenMorph4"
    assert sanitize_link("Chapéu 2") == "Chapeu2"
    assert sanitize_link("4ever Hat") == "_4everHat"
    with pytest.raises(ValueError):
        sanitize_link("!!!")


def test_internal_class_name():
    assert internal_class_name("KitsuneMorph", "Hair shade", 3) == "KitsuneMorph_fla.Hairshade_3"
    assert internal_class_name("KitsuneMorph", "???", 1) == "KitsuneMorph_fla.Symbol_1"
