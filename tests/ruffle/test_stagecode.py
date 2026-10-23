# tests/ruffle/test_stagecode.py


def test_the_shipped_stage_was_built_from_these_sources():
    from autoswf.ruffle.stagecode import built_digest, sources_digest, stage_abc
    assert built_digest() == sources_digest(), "run: python tools/build_ruffle_stage.py"
    abc = stage_abc()
    assert abc[:4] == bytes([0x10, 0x00, 0x2E, 0x00])                    # ABC 46.16
