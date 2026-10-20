# tests/aqw/test_validate_item.py
import struct

import pytest

from aqw_fakes import mini_armor_with_pieces
from autoswf.abc.movieclip_classes import SETCOLOR_FORMS
from autoswf.aqw.validate import validate_item_swf
from swf_builders import place2, shape_tag, sprite_tag, swf, symbol_class


def test_official_forms_validate_as_items():
    for form in SETCOLOR_FORMS:
        report = validate_item_swf(mini_armor_with_pieces("M", setcolor_form=form), {"TestArmorMChest"})
        assert report.ok, (form, report.problems)


def square(cid):
    return shape_tag(cid, 1, [("solid", (200, 0, 0, 255))], [],
                     [{"start": (0, 0), "edges": [(5, 0), (5, 5), (0, 5), (0, 0)], "fill1": 1}])


def test_item_problems_and_notes():
    broken = swf([square(1), sprite_tag(2, [[place2(1, 1), place2(2, 77)]]), symbol_class({2: "AMChest", 99: "AMHip"})])
    report = validate_item_swf(broken, {"AMChest", "AMShin"})
    assert any("points to character 99" in p for p in report.problems)
    assert any("places character 77" in p for p in report.problems)
    assert any("'AMShin' is missing" in p for p in report.problems)
    slow = bytearray(mini_armor_with_pieces("M"))
    slow = bytearray(swf_with_fps(bytes(slow), 12))
    assert any("says 12 fps" in n for n in validate_item_swf(bytes(slow)).notes)
    again = validate_item_swf(broken, {"AMChest", "AMShin"}, original=broken)
    assert again.ok and any(n.startswith("Already in the original: ") for n in again.notes)
    assert validate_item_swf(b"junk").problems[0].startswith("The file is not a valid SWF")


def swf_with_fps(data: bytes, fps: int) -> bytes:
    import zlib
    from autoswf.swf.reader import R, decompress
    _, version, _, body = decompress(data)
    r = R(body, 0)
    r.rect()
    r.align()
    body = body[:r.p] + struct.pack("<H", fps * 256) + body[r.p + 2:]
    return b"CWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + zlib.compress(body)


@pytest.mark.real
def test_the_users_armor_and_morph_validate(reference_morph, kind_of_brave):
    assert validate_item_swf(kind_of_brave.read_bytes(), {"KindOfBraveMChest"}).ok
    report = validate_item_swf(reference_morph.read_bytes(), {"CrystallisOnsenMMorph4"})
    assert report.ok and any("12 fps" in n for n in report.notes)
