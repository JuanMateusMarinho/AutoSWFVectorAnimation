# tests/parts/test_hidden.py
import numpy as np
import pytest
from drawings import drawing_from_specs
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.parts.detect import detect_parts
from autoswf.parts.hidden import layered_passes, split_passes

@pytest.fixture(scope="module")
def split(parts_helm):
    t = parts_helm
    d = drawing_from_specs(t.width, t.height, t.layers)
    passes = extract_passes(d, assign_roles(d))
    pm = detect_parts(passes, t.alignment)
    return t, passes, pm, {layer.name: layer for layer in split_passes(passes, pm)}

def canvas(origin, array, t):
    """A part's (or a pass's) local array placed on the drawing's canvas."""
    out = np.zeros((t.height, t.width) + array.shape[2:], array.dtype)
    x0, y0 = origin
    h, w = array.shape[:2]
    out[y0:y0 + h, x0:x0 + w] = array
    return out

def of(layer, name, t):
    return canvas(layer.passes.origin, getattr(layer.passes, name), t)

def head_grid(t):
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    ys, xs = np.mgrid[0:t.height, 0:t.width]
    return (xs + 0.5 - ox) / s, (ys + 0.5 - oy) / s

def test_layers_and_eye_sub_layers(split):
    t, passes, pm, layers = split
    assert {"Eye L ball", "Eye L lid", "Eye R ball", "Face", "Lock 3", "Helm"} <= set(layers)
    assert layers["Eye L ball"].parent == "Eye L" and layers["Face"].parent is None
    iris = of(layers["Eye L ball"], "flats", t)[..., 3] > 0.99
    assert iris[t.pieces["Eye L iris"]].mean() >= 0.95
    lid = of(layers["Eye L lid"], "lines", t)[..., 3] > 0.5
    ys = np.nonzero(lid)[0]
    assert len(ys) and ys.max() < t.alignment.origin[1] + 14.5 * t.alignment.scale

def test_skin_and_hair_continue_under_moving_parts(split):
    t, passes, pm, layers = split
    face, hair = of(layers["Face"], "fills", t), of(layers["Hair"], "fills", t)
    eye = t.truth["Eye L"]
    assert (face[eye][:, 3] >= 0.99).mean() >= 0.98
    lock = t.truth["Lock 3"]
    assert (np.maximum(face[..., 3], hair[..., 3])[lock] >= 0.99).mean() >= 0.98
    hx, hy = head_grid(t)
    tip = lock & (hy > -2)                                         # the half of the tooth over the face
    straight = face[tip][:, :3] / np.maximum(face[tip][:, 3:4], 1e-6) * 255
    assert (np.abs(straight - (242, 201, 160)).max(axis=1) <= 30).mean() >= 0.95

def test_hidden_fills_do_not_paint_the_background(split):
    t, passes, pm, layers = split
    hx, hy = head_grid(t)
    over_background = t.truth["Lock 6"] & (hx > 24) & (hy > 16)    # the side lock hanging right of the face
    assert over_background.sum() > 50
    for name, layer in layers.items():
        if name != "Lock 6":
            assert of(layer, "fills", t)[..., 3][over_background].max() < 0.05, name

def test_the_rest_pose_keeps_every_pixel(split):
    from scipy import ndimage
    t, passes, pm, layers = split
    union = np.zeros((t.height, t.width), np.float32)
    for layer in layers.values():
        for name in ("fills", "lines", "details"):
            union = np.maximum(union, of(layer, name, t)[..., 3])
    assert (union[passes.full[..., 3] > 0.02] > 0).all()
    own = of(layers["Lock 3"], "fills", t)
    source = canvas(passes.parts[0].origin, passes.parts[0].fills, t)
    inside = ndimage.binary_erosion(pm.part_mask("Lock 3"), iterations=1)          # the lock's own pixels
    assert np.abs(own[inside] - source[inside]).max() < 1e-6

def test_lock_outlines_belong_to_the_lock(split):
    from scipy import ndimage
    t, passes, pm, layers = split
    lock = of(layers["Lock 3"], "lines", t)[..., 3] > 0.5
    face = of(layers["Face"], "lines", t)[..., 3] > 0.5
    source = canvas(passes.parts[0].origin, passes.parts[0].lines, t)[..., 3] > 0.5
    beside = ndimage.binary_dilation(t.truth["Lock 3"], iterations=3) & ~t.truth["Lock 3"] & ~t.truth["Hair"]
    assert lock[beside & source].mean() >= 0.8
    lock_any = of(layers["Lock 3"], "lines", t)[..., 3] > 0.02
    face_any = of(layers["Face"], "lines", t)[..., 3] > 0.02
    shared = face_any & lock_any                                                   # only a 2 px underlap
    assert (shared & ~ndimage.binary_dilation(face_any & ~lock_any, iterations=2)).sum() == 0

def test_layered_passes_feed_the_vectorizer(split):
    from autoswf.vectorize.art import vectorize
    t, passes, pm, layers = split
    lp = layered_passes(passes, list(layers.values()))
    assert lp.full is passes.full and [p.part for p in lp.parts] == list(layers)
    art = vectorize(lp, t.alignment)
    assert {"Lock 3: Fills", "Eye L ball: Fills", "Face: Line"} <= {l.name for l in art.layers}

def test_a_face_folder_painted_under_the_hair_keeps_its_own_painting():
    from drawings import disc, rect
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.writers import LayerSpec
    W = H = 240
    painted = disc(W, H, (240, 200, 160, 255), 120, 140, 80)
    painted[100:140, 60:180, :3] = (250, 150, 150)                 # a blush, mostly hidden by the hair folder
    specs = [LayerSpec("Face", children=[LayerSpec("Flats", painted)]),
             LayerSpec("Hair", children=[LayerSpec("Flats", rect(W, H, (120, 70, 40, 255), 40, 40, 200, 130))])]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    pm = detect_parts(passes, Alignment(2.4, (120, 130)))
    layers = {l.name: l for l in split_passes(passes, pm)}
    t = type("Canvas", (), {"width": W, "height": H})
    face = of(layers["Face"], "flats", t)
    folder = canvas(passes.parts[0].origin, passes.parts[0].flats, t)
    assert np.allclose(face[100:130, 60:180], folder[100:130, 60:180])
