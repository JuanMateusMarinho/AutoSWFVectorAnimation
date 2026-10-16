import math

from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.swf.bits import BitWriter, bits_for_signed, write_cxform_alpha, write_matrix, write_rect
from autoswf.swf.reader import R


def test_bits_for_signed():
    assert bits_for_signed(0) == 0 and bits_for_signed(1) == 2 and bits_for_signed(-1) == 1
    assert bits_for_signed(11000) == 15 and bits_for_signed(-180000) == 19


def test_rect_roundtrip():
    w = BitWriter(); write_rect(w, 0, 11000, -40, 8000)
    assert R(w.getvalue()).rect() == (0, 11000, -40, 8000)


def test_matrix_roundtrip_identity_scale_rotate():
    for m in (Matrix.identity(), Matrix(-0.28, -0.03, -0.05, 0.48, 34.6, 28.6),
              Matrix.rotate(math.pi / 6) @ Matrix.scale(1.96, 1.96)):
        w = BitWriter(); write_matrix(w, m)
        a, b, c, d, tx, ty = R(w.getvalue()).matrix()
        assert all(abs(x - y) < 1e-4 for x, y in zip((a, b, c, d), (m.a, m.b, m.c, m.d)))
        assert (tx, ty) == (round(m.tx * 20) / 20, round(m.ty * 20) / 20)


def test_cxform_alpha_roundtrip():
    w = BitWriter(); write_cxform_alpha(w, ColorTransform((1.0, 1.0, 1.0, 0.0), (0, 0, 0, 0)))
    assert R(w.getvalue()).cxform(True) == {"mult": (1.0, 1.0, 1.0, 0.0), "add": None}
