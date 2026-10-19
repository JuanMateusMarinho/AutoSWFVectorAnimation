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


EXPECTED = {"Face", "Ear L", "Mouth", "Brow L", "Brow R", "Eye L", "Eye R", "Hair", "Lock 1", "Lock 2", "Lock 3",
            "Lock 4", "Lock 5", "Lock 6", "Horn R", "Helm", "Accessory 1"}

def test_the_synthetic_helm_is_labeled_like_its_truth(parts_helm):
    from drawings import agreement, line_mask
    t = parts_helm
    passes, pm = detect(t)
    assert set(pm.parts) == EXPECTED
    under_lines = line_mask(passes)
    for name in EXPECTED:
        recall, precision = agreement(pm.part_mask(name), t.truth[name], ignore=under_lines)
        bars = (0.9, 0.9) if name.startswith("Ear") else (0.95, 0.95)
        if name.startswith(("Lock", "Hair")):       # a lock's root sits where the outline's notches end (~1 unit)
            bars = (0.8, 0.85)
        assert recall >= bars[0] and precision >= bars[1], (name, recall, precision)
    zs = [pm.parts[n].z for n in pm.parts]
    assert zs == sorted(zs)

def test_lock_roots_and_tips(parts_helm):
    t = parts_helm
    _, pm = detect(t)
    for k in range(1, 7):
        part = pm.parts["Lock %d" % k]
        rx, ry = t.roots["Lock %d" % k]
        tx, ty = t.tips["Lock %d" % k]
        assert np.hypot(part.pivot.x - rx, part.pivot.y - ry) <= 1.5, k
        assert np.hypot(part.tip.x - tx, part.tip.y - ty) <= 2.0, k

def test_one_click_fixes_a_wrong_part(parts_helm):
    from autoswf.parts.model import Assign, Corrections
    t = parts_helm
    _, pm = detect(t)
    gem = pm.graph.regions[pm.parts["Accessory 1"].regions[0]]
    cx, cy = (gem.box[0] + gem.box[2]) / 2, (gem.box[1] + gem.box[3]) / 2
    _, fixed = detect(t, corrections=Corrections([Assign((cx, cy), "Helm")]))
    assert "Accessory 1" not in fixed.parts and fixed.region_at(cx, cy).id in fixed.parts["Helm"].regions

def test_a_cut_and_a_click_make_a_new_lock_and_colors_set_slots(parts_helm):
    from autoswf.parts.model import Assign, Corrections
    t = parts_helm
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    px = lambda x, y: (ox + x * s, oy + y * s)
    cut = [px(-38, -15), px(-38, -7)]                  # across the hair band, left of Lock 1's base (x -36)
    c = Corrections([Assign(px(-40, -11), "Lock 7")], [cut], {"Helm": "Base", "Brow L": "none"})
    _, pm = detect(t, corrections=c)
    assert "Lock 7" in pm.parts and -39.5 < pm.parts["Lock 7"].pivot.x < -36.5
    assert {pm.location_of[r] for r in pm.parts["Helm"].regions} == {"Base"}
    assert {pm.location_of[r] for r in pm.parts["Brow L"].regions} == {None}

def test_stale_corrections_are_notes_not_errors(parts_helm):
    from autoswf.parts.model import Assign, Corrections
    _, pm = detect(parts_helm, corrections=Corrections([Assign((1, 1), "Helm")], [], {"Accessory 4": "Trim"}))
    assert any("is not on any region; skipped" in n for n in pm.notes)
    assert any("Color for 'Accessory 4' skipped" in n for n in pm.notes)

def test_part_folders_win_over_the_heuristics():
    from drawings import TestDrawing, disc, rect
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.writers import LayerSpec
    W = H = 200
    layers = [LayerSpec("Rosto", children=[LayerSpec("Flats", disc(W, H, (80, 200, 90, 255), 100, 120, 60))]),
              LayerSpec("Olhos", children=[LayerSpec("Flats", disc(W, H, (255, 255, 255, 255), 80, 120, 10)),
                                           LayerSpec("Flats 2", disc(W, H, (200, 30, 30, 255), 82, 121, 5))]),
              LayerSpec("Acessórios", children=[LayerSpec("Flats", rect(W, H, (240, 240, 240, 255), 150, 20, 170, 40))])]
    _, pm = detect(TestDrawing(W, H, layers, Alignment(2, (100, 100))))
    assert set(pm.parts) == {"Face", "Eye L", "Accessory 1"}       # without the folder the white box would be Helm
    assert {pm.location_of[r] for r in pm.parts["Face"].regions} == {"Skin"}         # green skin

def test_black_outlines_in_the_flats_join_their_part(parts_helm):
    import dataclasses
    from autoswf.drawing.writers import LayerSpec
    from drawings import ring
    t = parts_helm
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    outline = ring(t.width, t.height, (10, 10, 10, 255), ox - 9 * s, oy - 17.5 * s, 3.6 * s, 3.0 * s)
    flats = np.where(outline[..., 3:4] > 0, outline, t.layers[0].pixels)
    _, pm = detect(dataclasses.replace(t, layers=[LayerSpec("Flats", flats)] + t.layers[1:]))
    assert set(pm.parts) == EXPECTED

@pytest.mark.aqw
def test_official_parts(qapp, aqw_cache, reference_morph):
    from official_drawings import official_drawing
    from autoswf.swf.decode import MovieData
    _, morph = detect(official_drawing(MovieData(reference_morph), "CrystallisOnsenMMorph4"))
    assert sum(n.startswith("Lock") for n in morph.parts) >= 6
    assert {"Face", "Eye L", "Eye R", "Hair"} <= set(morph.parts)
    artix = MovieData(aqw_cache.file_path("items/helms/ArtixHead.swf"))
    _, pm = detect(official_drawing(artix, "ArtixHead"))
    assert {"Face", "Eye L", "Eye R", "Hair"} <= set(pm.parts)
    leppy = MovieData(aqw_cache.file_path("items/helms/GoldLeppy2018HatM.swf"))
    _, pm = detect(official_drawing(leppy, "GoldLeppy2018HatM"))
    assert {"Hair", "Ear L"} <= set(pm.parts)



# ---------------------------------------------------------------- review fixes

def test_a_hat_over_hair_without_a_face_has_no_skin():
    from drawings import hat_over_hair
    _, pm = detect(hat_over_hair())
    assert pm.skin is None and "Skin" not in set(pm.location_of.values())
    assert pm.hair and any(n.startswith("Lock") for n in pm.parts)

def test_one_click_makes_a_region_hair_with_its_color():
    from autoswf.parts.model import Assign, Corrections
    t = smooth_helmet()
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    _, pm = detect(t, corrections=Corrections([Assign((ox - 9 * s, oy - 40 * s), "Hair")]))
    hair = [r for n, p in pm.parts.items() if n == "Hair" or n.startswith("Lock") for r in p.regions]
    assert hair and {pm.location_of[r] for r in hair} == {"Hair"}

@pytest.mark.parametrize("names", [("Hair", "Face", "Bangs"), ("Back", "Head", "Front")])
def test_hair_folders_over_and_under_a_face_folder(names):
    from drawings import folder_helm
    from autoswf.drawing.writers import LayerSpec
    _, pm = detect(folder_helm(names))
    assert pm.skin[:3] == (242, 201, 160) and pm.hair and pm.hair[0][:3] == (120, 70, 40)
    face = pm.parts["Face"]
    assert {pm.location_of[r] for r in face.regions} == {"Skin"}
    assert {pm.graph.regions[r].group for r in face.regions} == {1}

def test_white_hair_keeps_its_eyes():
    from drawings import synthetic_parts_helm
    t = synthetic_parts_helm(480, hair=(235, 235, 240), skin=(240, 200, 170))
    _, pm = detect(t)
    assert {"Eye L", "Eye R"} <= set(pm.parts)
    loc = location_map(pm, t.width, t.height)
    for side in "LR":
        for piece in ("white", "pupil", "highlight"):
            assert (loc[inner(t.pieces["Eye %s %s" % (side, piece)], 1)] == "-").mean() >= 0.95, (side, piece)

@pytest.mark.parametrize("color", [(90, 110, 140), (150, 150, 150), (180, 140, 40)])
def test_a_plated_helmet_is_not_hair(color):
    from drawings import plated_helmet
    _, pm = detect(plated_helmet(color))
    assert pm.hair == [] and "Hair" not in set(pm.location_of.values())

def test_blond_hair_does_not_take_a_gold_band():
    from drawings import synthetic_parts_helm
    t = synthetic_parts_helm(480, hair=(240, 200, 120), skin=(110, 70, 50))
    _, pm = detect(t)
    assert [c[:3] for c in pm.hair] == [(240, 200, 120)]
    assert {pm.location_of[r] for r in pm.parts["Helm"].regions} == {None}

def test_color_slots_never_reach_eye_whites_pupils_highlights_or_outlines(parts_helm):
    from autoswf.parts.model import Corrections
    t = parts_helm
    _, pm = detect(t, corrections=Corrections(colors={"Eye L": "Eye", "Helm": "Base"}))
    for rid in pm.parts["Eye L"].regions:
        want = "Eye" if pm.piece_of[rid] == "iris" else None
        assert pm.location_of[rid] == want, pm.piece_of[rid]
    assert any("keep their colors" in n for n in pm.notes)

def test_an_eyes_folder_keeps_white_pieces_of_other_folders_out_of_its_eyes():
    from drawings import TestDrawing, disc
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.writers import LayerSpec
    W = H = 200
    white, iris, ink = (255, 255, 255, 255), (40, 120, 200, 255), (20, 20, 30, 255)
    eyes = [LayerSpec("Flats", disc(W, H, white, 80, 120, 10)), LayerSpec("Flats 2", disc(W, H, iris, 82, 121, 5)),
            LayerSpec("Flats 3", disc(W, H, white, 130, 120, 10)), LayerSpec("Flats 4", disc(W, H, iris, 132, 121, 5))]
    mark = np.where(disc(W, H, ink, 105, 138, 2.5)[..., 3:4] > 0, disc(W, H, ink, 105, 138, 2.5),
                    disc(W, H, white, 105, 138, 5))         # a white mark in the eye band, a dark dot in its middle
    layers = [LayerSpec("Rosto", children=[LayerSpec("Flats", disc(W, H, (240, 200, 160, 255), 100, 120, 60))]),
              LayerSpec("Olhos", children=eyes), LayerSpec("Flats", mark)]
    _, pm = detect(TestDrawing(W, H, layers, Alignment(2, (100, 100))))
    assert {"Eye L", "Eye R"} <= set(pm.parts)
    for name in ("Eye L", "Eye R"):
        assert {pm.graph.regions[r].group for r in pm.parts[name].regions} == {1}, name
    assert not pm.part_of[pm.region_at(105, 134).id].startswith("Eye")

def test_a_slot_for_the_hair_reaches_its_locks(parts_helm):
    from autoswf.parts.model import Corrections
    _, pm = detect(parts_helm, corrections=Corrections(colors={"Hair": "none"}))
    locks = [r for n, p in pm.parts.items() if n.startswith("Lock") for r in p.regions]
    assert locks and {pm.location_of[r] for r in locks} == {None}


def test_color_slots_match_a_fresh_detection(converted_parts_helm):
    from autoswf.parts.detect import apply_color_slots
    from autoswf.parts.model import Corrections
    c = converted_parts_helm
    colors = {"Helm": "Base", "Brow L": "none", "Hair": "Trim", "Eye L": "Accessory"}
    fresh = detect_parts(c.passes, c.t.alignment, Corrections(colors=colors))
    fast = apply_color_slots(c.parts, colors)
    assert fast.location_of == fresh.location_of and fast.notes == fresh.notes
    assert apply_color_slots(fast, {}).location_of == c.parts.location_of


def test_a_lock_marked_as_another_part_leaves_the_other_locks(parts_helm):
    from autoswf.parts.model import Assign, Corrections
    _, pm = detect(parts_helm)
    x, y = pm.label_point("Lock 2")
    locks = sorted(n for n in pm.parts if n.startswith("Lock"))
    _, fixed = detect(parts_helm, corrections=Corrections([Assign((x, y), "Accessory 3")]))
    assert fixed.part_of[fixed.region_at(x, y).id] == "Accessory 3"
    assert "Hair" in fixed.parts and len([n for n in fixed.parts if n.startswith("Lock")]) == len(locks) - 1
    assert fixed.parts["Accessory 3"].regions == [fixed.region_at(x, y).id]
