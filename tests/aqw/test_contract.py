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


@pytest.mark.parametrize("text, link, error, warning", [
    ("MyHelm", "MyHelm", None, None),
    ("Chapéu 2", "Chapeu2", None, "the link will be 'Chapeu2'"),
    ("4ever", "_4ever", None, "the link will be '_4ever'"),
    ("", "", "The link name is empty", None),
    ("class", "class", "reserved word", None),
    ("Game", "Game", "class of the AQW game client", None),
    ("MovieClip", "MovieClip", "Flash class name", None),
])
def test_check_link(text, link, error, warning):
    from autoswf.aqw.contract import check_link
    c = check_link(text)
    assert c.link == link
    assert (error is None and c.error is None) or (error is not None and error in c.error)
    assert (warning is None and c.warning is None) or (warning is not None and warning in c.warning)


def test_names_from_the_cached_client_are_refused():
    from autoswf.aqw.contract import check_link
    assert "AQW game client" in check_link("LoaderPanel", {"LoaderPanel"}).error
