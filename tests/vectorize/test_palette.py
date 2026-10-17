# tests/vectorize/test_palette.py
import numpy as np
import pytest
from autoswf.vectorize.palette import merge_small, palette_labels, relative_threshold

def premult(rgb, alpha=1.0):
    a = np.zeros(rgb.shape[:2] + (4,), np.float32); a[..., :3] = rgb / 255 * alpha; a[..., 3] = alpha; return a

def test_anti_aliased_edges_snap_to_their_neighbors_not_to_a_similar_color():
    img = np.zeros((20, 60, 3)); img[:, :20] = (220, 30, 30); img[:, 21:40] = (30, 200, 30)
    img[:, 20] = (125, 115, 30)                      # 50/50 anti-aliasing between red and green
    img[:, 40:] = (128, 110, 30)                     # an unrelated brown region close to that mix
    li = palette_labels(premult(img))
    assert len(li.colors) == 3 and not li.posterized
    names = {tuple(c[:3]): i for i, c in enumerate(li.colors)}
    assert set(li.labels[:, 20]) <= {names[(220, 30, 30)], names[(30, 200, 30)]}

def test_alpha_below_half_is_empty():
    a = premult(np.full((4, 4, 3), 100.0)); a[:, :2] *= 0.3
    li = palette_labels(a)
    assert (li.labels[:, :2] == -1).all() and (li.labels[:, 2:] == 0).all()

def test_soft_gradient_is_posterized_into_steps():
    img = np.zeros((20, 120, 3)); img[:] = np.linspace(40, 240, 120)[None, :, None]
    li = palette_labels(premult(img))
    assert 3 <= len(li.colors) <= 10 and li.posterized == frozenset(range(len(li.colors)))
    row = li.labels[10]
    greys = [li.colors[l][0] for l in row]
    assert greys == sorted(greys) and max(abs(g - v) for g, v in zip(greys, img[10, :, 0])) <= 24

def test_merge_small_specks():
    lab = np.zeros((30, 30), np.int32); lab[5:7, 5:7] = 1; lab[15:25, 15:25] = 2
    out = merge_small(lab, 12)
    assert (out[5:7, 5:7] == 0).all() and (out[15:25, 15:25] == 2).all()

def test_relative_threshold():
    a = np.zeros((10, 10)); a[:5] = 0.6
    assert relative_threshold(a) == pytest.approx(0.3)

def test_memory_stays_bounded_on_big_drawings():
    import tracemalloc
    h = w = 1500
    colors = np.array([(r, g, b) for r in (20, 80, 140, 200) for g in (30, 110, 190) for b in (40, 160, 240)], float)
    stripes = np.repeat(colors, w // len(colors) + 1, axis=0)[:w]       # 36 flat colors side by side
    image = premult(np.broadcast_to(stripes[None], (h, w, 3)).copy())
    tracemalloc.start()
    li = palette_labels(image)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(li.colors) == 36 and peak < 800 * 2 ** 20, peak / 2 ** 20
