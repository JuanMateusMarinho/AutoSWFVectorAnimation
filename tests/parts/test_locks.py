# tests/parts/test_locks.py
import numpy as np
from PIL import Image, ImageDraw
from autoswf.parts.locks import split_locks

def comb(scale, teeth=5, width=10.0, height=12.0):
    """A hair band (6 units tall) with triangular teeth hanging from it; returns the mask and the tooth masks."""
    w, h = int((teeth * width + 20) * scale), int(30 * scale)
    def poly(points):
        im = Image.new("L", (w, h), 0)
        ImageDraw.Draw(im).polygon([(x * scale, y * scale) for x, y in points], fill=1)
        return np.array(im, bool)
    band = poly([(4, 4), (teeth * width + 16, 4), (teeth * width + 16, 10), (4, 10)])
    tips = [poly([(10 + k * width, 10), (10 + (k + 1) * width, 10), (10 + (k + 0.5) * width, 10 + height)])
            for k in range(teeth)]
    return band | np.logical_or.reduce(tips), tips

def iou(a, b):
    return (a & b).sum() / (a | b).sum()

def test_each_tooth_becomes_a_lock():
    mask, tips = comb(6)
    pieces, cuts = split_locks(mask, 6)
    assert pieces.max() == 5 and len(cuts) == 5
    for tip in tips:
        best = max(iou(pieces == k, tip) for k in range(1, 6))
        assert best >= 0.85

def test_the_same_shape_at_other_scales():
    for scale in (3, 9):
        mask, _ = comb(scale)
        assert split_locks(mask, scale)[0].max() == 5

def test_smooth_shapes_and_short_bumps_have_no_locks():
    yy, xx = np.mgrid[0:300, 0:400]
    ellipse = ((xx - 200) / 180) ** 2 + ((yy - 150) / 120) ** 2 <= 1
    assert split_locks(ellipse, 6)[0].max() == 0
    mask, _ = comb(6, height=3.0)                       # bumps 10 wide and 3 tall are not locks
    assert split_locks(mask, 6)[0].max() == 0

def test_a_side_lock_joined_smoothly_on_one_side_is_cut_at_its_root():
    scale = 6
    im = Image.new("L", (92 * scale, 60 * scale), 0)
    pts = [(4, 4), (80, 4), (80, 14), (84, 34), (81, 52), (75, 34), (70, 14), (4, 14)]   # side lock under x 70..80
    ImageDraw.Draw(im).polygon([(x * scale, y * scale) for x, y in pts], fill=1)       # (271 of 1031 units²: 26 %)
    pieces, (cut,) = split_locks(np.array(im, bool), scale)
    ends = sorted([cut.a, cut.b])
    assert pieces.max() == 1
    assert np.hypot(ends[0][0] / scale - 70, ends[0][1] / scale - 14) <= 1.5      # the notch
    assert abs(ends[1][0] / scale - 80) <= 1.5 and 10 <= ends[1][1] / scale <= 18   # straight across to the outer edge
