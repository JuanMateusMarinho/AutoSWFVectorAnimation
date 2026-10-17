# tests/vectorize/test_trace.py
import numpy as np
from autoswf.vectorize.trace import boundary_chains

def cracks_of(labels):
    """Every unit pixel edge between different labels (outside = -1), as frozensets of two lattice points."""
    p = np.pad(labels, 1, constant_values=-1)
    out = set()
    h, w = labels.shape
    for y in range(h + 1):
        for x in range(w):
            if p[y, x + 1] != p[y + 1, x + 1]:
                out.add(frozenset({(x, y), (x + 1, y)}))
    for y in range(h):
        for x in range(w + 1):
            if p[y + 1, x] != p[y + 1, x + 1]:
                out.add(frozenset({(x, y), (x, y + 1)}))
    return out

def label_at(labels, x, y):
    h, w = labels.shape
    return labels[y, x] if 0 <= x < w and 0 <= y < h else -1

def check(labels):
    chains = boundary_chains(labels)
    seen = []
    for c in chains:
        pts = [tuple(int(v) for v in p) for p in c.points]
        assert c.left != c.right and (not c.closed or pts[0] == pts[-1])     # a chain may also leave and re-enter one junction
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            seen.append(frozenset({(x0, y0), (x1, y1)}))
            dx, dy = x1 - x0, y1 - y0
            # pixel on the right of a step (y down): right of +x is below, right of +y is to the left
            rx, ry = (min(x0, x1), y0) if dy == 0 and dx > 0 else (min(x0, x1), y0 - 1) if dy == 0 else (x0 - 1, min(y0, y1)) if dy > 0 else (x0, min(y0, y1))
            assert label_at(labels, rx, ry) == c.right
    assert len(seen) == len(set(seen)) and set(seen) == cracks_of(labels)
    return chains

def test_two_squares_share_one_chain():
    chains = check(np.array([[0, 0, 1, 1], [0, 0, 1, 1]]))
    shared = [c for c in chains if {c.left, c.right} == {0, 1}]
    assert len(shared) == 1 and not shared[0].closed and len(shared[0].points) == 3

def test_island_is_one_closed_chain():
    lab = np.full((5, 5), 0); lab[2, 2] = 1
    chains = check(lab)
    island = [c for c in chains if 1 in (c.left, c.right)]
    assert len(island) == 1 and island[0].closed and len(island[0].points) == 5

def test_checkerboard_and_random_label_images():
    check(np.array([[0, 1], [1, 0]]))
    rng = np.random.default_rng(3)
    for _ in range(20):
        check(rng.integers(-1, 4, size=(17, 23)))
