# tests/aqw/test_template.py
import clipparse
import pytest
from aqw_fakes import mini_client
from psd_tools import PSDImage
from psd_tools.constants import Tag
from autoswf.aqw.template import (HEAD_BOX, TEMPLATE_LAYERS, Alignment, fit_alignment, is_template, template_alignment,
                                  write_template)
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.roles import assign_roles
from autoswf.model.geometry import Point
from autoswf.swf.decode import MovieData

def test_alignment_matrix_parse_and_print():
    m = template_alignment().matrix()
    assert m.apply(Point(1110, 1115)) == Point(0, 0) and m.apply(Point(1120, 1115)) == Point(1, 0)
    p = Alignment(10, (0, 0), 90).matrix().apply(Point(10, 0))
    assert p.x == pytest.approx(0, abs=1e-9) and p.y == pytest.approx(1)
    assert Alignment.parse("10,1110,1115") == Alignment(10.0, (1110.0, 1115.0), 0.0)
    assert str(Alignment.parse("7.5,12,-3,15")) == "7.5,12,-3,15"
    with pytest.raises(ValueError, match="Alignment must look like SCALE,X,Y or SCALE,X,Y,DEGREES"):
        Alignment.parse("big")

@pytest.mark.parametrize("text", ["nan,0,0", "10,inf,0", "10,0,-inf", "10,0,0,nan", "inf,0,0"])
def test_alignment_rejects_values_that_are_not_finite(text):
    with pytest.raises(ValueError, match="Alignment must look like SCALE,X,Y or SCALE,X,Y,DEGREES"):
        Alignment.parse(text)

def test_a_drawing_turned_clockwise_needs_a_negative_rotation():
    # The head's "up" (0, -1) in a drawing turned 90° clockwise points right, to (1, 0).
    up = Alignment(1, (0, 0), -90).matrix().apply(Point(1, 0))
    assert up.x == pytest.approx(0, abs=1e-9) and up.y == pytest.approx(-1)

def test_fit_alignment_puts_the_art_on_the_head():
    m = fit_alignment((100, 300, 50, 350)).matrix()
    hx, hy = (HEAD_BOX[0] + HEAD_BOX[1]) / 2, (HEAD_BOX[2] + HEAD_BOX[3]) / 2
    c, top, bottom = m.apply(Point(200, 200)), m.apply(Point(200, 50)), m.apply(Point(200, 350))
    assert (c.x, c.y) == (pytest.approx(hx), pytest.approx(hy)) and bottom.y - top.y == pytest.approx(HEAD_BOX[3] - HEAD_BOX[2])

def test_template_files(tmp_path, qapp):
    write_template(MovieData(mini_client()), tmp_path / "t.psd", clip=tmp_path / "t.clip")
    psd = PSDImage.open(tmp_path / "t.psd")
    assert psd.size == (2000, 2000)
    assert [l.name for l in psd] == ["AQW Guide Head F", "AQW Guide Head M", *TEMPLATE_LAYERS]
    f, m = psd[0], psd[1]
    assert not f.visible and m.visible
    assert all(l.tagged_blocks.get_data(Tag.PROTECTED_SETTING) for l in (f, m))
    assert psd[3].blend_mode.name == "MULTIPLY" and psd[3].clipping
    d = read_drawing(tmp_path / "t.psd")
    guide = d.layers[1]
    assert is_template(d) and guide.pixels[1115 - guide.top, 1110 - guide.left, 3] == 255
    roles = {n.name: r.role for n, r in assign_roles(d).items()}
    assert roles == {"AQW Guide Head F": "ignore", "AQW Guide Head M": "ignore", "Flats": "flat", "Shadow": "shadow",
                     "Occlusion": "occlusion", "Light": "light", "Details": "details", "Line": "line"}
    assert clipparse.validate(str(tmp_path / "t.clip")) == []
    assert [n.name for n in read_drawing(tmp_path / "t.clip").layers] == ["Paper", "AQW Guide Head F", "AQW Guide Head M", *TEMPLATE_LAYERS]


def test_alignment_survives_a_trip_through_its_matrix():
    from autoswf.aqw.template import alignment_from_matrix, alignment_text
    a = Alignment(7.5, (900.0, 1040.0), -12.0)
    b = alignment_from_matrix(a.matrix())
    assert b.scale == pytest.approx(7.5) and b.rotation == pytest.approx(-12.0)
    assert b.origin == pytest.approx((900.0, 1040.0))
    precise = Alignment(10.123456789, (1110.987654321, 1115.5), 0.25)
    assert Alignment.parse(alignment_text(precise)) == precise
