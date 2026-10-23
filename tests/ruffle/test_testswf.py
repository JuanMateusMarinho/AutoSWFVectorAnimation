# tests/ruffle/test_testswf.py
from autoswf.swf.decode import MovieData


def test_a_test_swf_carries_the_stage_the_armor_and_the_settings():
    from aqw_fakes import release_armor_swf
    from autoswf.ruffle.testswf import STAGE_CLASS, build_test_swf, read_test_swf
    armor = release_armor_swf()
    data = build_test_swf(armor, {"link": "TestRelease", "genders": ["M"]}, abc=b"\x10\x00\x2e\x00" + b"\0" * 8)
    assert data[:3] == b"CWS" and MovieData(data).classes.get(STAGE_CLASS) == 0
    settings, embedded = read_test_swf(data)
    assert settings == {"link": "TestRelease", "genders": ["M"]} and embedded == armor


def test_a_test_swf_can_carry_aqws_training_dummy():
    from aqw_fakes import release_armor_swf
    from autoswf.ruffle.testswf import DUMMY_CLASS, build_test_swf, embedded_dummy
    from autoswf.swf.decode import MovieData
    abc = b"\x10\x00\x2e\x00" + b"\0" * 8
    dummy = b"FWS fake dummy"
    data = build_test_swf(release_armor_swf(), {"dummy": "TrainingDummy"}, abc=abc, dummy=dummy)
    assert embedded_dummy(data) == dummy and MovieData(data).classes.get(DUMMY_CLASS) == 3
    assert embedded_dummy(build_test_swf(release_armor_swf(), {}, abc=abc)) is None
