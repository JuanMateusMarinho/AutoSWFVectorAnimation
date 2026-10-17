# tests/parts/test_detect.py
import numpy as np
import pytest
from drawings import drawing_from_specs, hat_only, smooth_helmet
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.parts.detect import detect_parts

def detect(t, **kw):
    d = drawing_from_specs(t.width, t.height, t.layers)
    passes = extract_passes(d, assign_roles(d))
    return passes, detect_parts(passes, t.alignment, **kw)

def location_map(pm, width, height):
    out = np.full((height, width), "", "<U4")
    for group in pm.graph.groups:
        x0, y0 = group.origin
        h, w = group.labels.shape
        view = out[y0:y0 + h, x0:x0 + w]
        for rid, loc in pm.location_of.items():
            if pm.graph.regions[rid].group == group.index:
                view[group.labels == rid] = loc or "-"
    return out

def inner(mask, px):
    from scipy import ndimage
    return ndimage.binary_erosion(mask, iterations=px)

def test_skin_hair_and_iris_get_their_locations(parts_helm):
    t = parts_helm
    _, pm = detect(t)
    loc = location_map(pm, t.width, t.height)
    for name, mask in t.truth.items():
        if not name.startswith("Eye"):
            assert (loc[inner(mask, 2)] == (t.locations[name] or "-")).mean() >= 0.99, name
    for side in "LR":
        assert (loc[inner(t.pieces["Eye %s iris" % side], 1)] == "Eye").mean() >= 0.95
        for piece in ("white", "pupil", "highlight"):
            assert (loc[inner(t.pieces["Eye %s %s" % (side, piece)], 1)] == "-").mean() >= 0.95

def test_eye_pieces_are_found(parts_helm):
    from drawings import agreement
    t = parts_helm
    _, pm = detect(t)
    for side in "LR":
        for piece in ("white", "iris", "pupil", "highlight"):
            found = np.zeros((t.height, t.width), bool)
            for rid, p in pm.piece_of.items():
                if p == piece and pm.part_of[rid] == "Eye " + side:
                    found |= pm.graph.canvas_mask(rid)
            recall, precision = agreement(found, t.pieces["Eye %s %s" % (side, piece)], slack=1)
            assert recall >= 0.9 and precision >= 0.9, (side, piece, recall, precision)

def test_a_smooth_helmet_around_the_face_is_not_hair():
    t = smooth_helmet()
    _, pm = detect(t)
    assert pm.hair == [] and "Hair" not in set(pm.location_of.values()) and pm.skin is not None

def test_a_hat_alone_has_nothing_colorable():
    t = hat_only()
    _, pm = detect(t)
    assert set(pm.location_of.values()) == {None} and pm.skin is None and pm.hair == []
    assert any("No skin found" in n for n in pm.notes)

@pytest.mark.aqw
@pytest.mark.parametrize("rel, class_name", [(None, "mcHeadM"), (None, "mcHeadF"),
                                              ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"),
                                              ("morph", "CrystallisOnsenMMorph4")])
def test_official_color_locations(qapp, aqw_cache, request, rel, class_name):
    from official_drawings import official_drawing, official_locations
    from autoswf.swf.decode import MovieData
    path = request.getfixturevalue("reference_morph") if rel == "morph" else (
        aqw_cache.file_path(rel) if rel else aqw_cache.client_path())
    movie = MovieData(path)
    t = official_drawing(movie, class_name)
    truth = official_locations(movie, class_name)
    passes, pm = detect(t)
    loc = location_map(pm, t.width, t.height)
    covered = (loc != "") & (passes.full[..., 3] > 0)
    for p in passes.parts:                                       # line and detail pixels are never colorable
        x0, y0 = p.origin
        h, w = p.lines.shape[:2]
        covered[y0:y0 + h, x0:x0 + w] &= (p.lines[..., 3] < 0.5) & (p.details[..., 3] < 0.5)
    colorable = covered & np.isin(truth, ["Skin", "Hair", "Eye"])
    plain = covered & (truth == "-")
    assert (loc[colorable] == truth[colorable]).mean() >= 0.95
    assert (loc[plain] == "-").mean() >= 0.95
