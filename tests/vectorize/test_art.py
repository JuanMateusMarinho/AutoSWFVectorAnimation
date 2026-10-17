# tests/vectorize/test_art.py
import numpy as np
import pytest
from drawings import disc, drawing_from_specs, rect, ring
from autoswf.aqw.helm import export_helm
from autoswf.aqw.template import Alignment
from autoswf.aqw.validate import validate_helm_swf
from autoswf.drawing.composite import blend
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import LayerSpec
from autoswf.vectorize.art import VectorizeSettings, helm_from_art, split_tones, vectorize

W = H = 120
RED, BLUE, INK, GOLD = (200, 40, 40, 255), (120, 110, 210, 255), (25, 15, 35, 255), (250, 220, 90, 255)

def art_of(specs, **kw):
    d = drawing_from_specs(W, H, specs)
    return vectorize(extract_passes(d, assign_roles(d)), Alignment(4, (60, 60)), VectorizeSettings(**kw))

SPECS = [LayerSpec("Flats", disc(W, H, RED, 60, 60, 45)),
         LayerSpec("Shadow", rect(W, H, BLUE, 70, 0, 120, 120), blend="multiply", clipping=True),
         LayerSpec("Light", disc(W, H, (255, 255, 255, 255), 40, 40, 20, soft=True), blend="screen", clipping=True),
         LayerSpec("Details", disc(W, H, GOLD, 80, 80, 6)),
         LayerSpec("Line", ring(W, H, INK, 60, 60, 47, 43))]

def test_layers_styles_and_baked_tones():
    art = art_of(SPECS)
    assert [(l.name, l.role) for l in art.layers] == [("Fills", "fills"), ("Details", "details"), ("Line", "line")]
    fills = art.layers[0]
    flat = [s for s in fills.styles if s.tones == () and s.flat is not None]
    shadow = [s for s in fills.styles if s.tones == (("shadow", 1),)]
    lights = sorted({t[1] for s in fills.styles for t in s.tones if t[0] == "light"})
    assert [s.color[:3] for s in flat] == [RED[:3]]
    expected = blend("multiply", np.array(RED[:3]) / 255, np.array(BLUE[:3]) / 255) * 255
    assert np.abs(np.array(shadow[0].color[:3]) - expected).max() <= 3
    assert lights == [1, 2, 3] and art.soft.any()
    assert art.layers[2].styles[0].color[:3] == INK[:3]

def test_split_tones_keeps_geometry_and_drops_inner_edges():
    fills = art_of(SPECS).layers[0]
    base, *tones = split_tones(fills)
    assert [t.name for t in tones] == ["Fills shadow", "Fills light"]
    assert all(s.tones == () for s in base.styles)
    assert all(p.fill_left != p.fill_right for p in base.shape.paths)
    assert tones[0].styles and all("shadow" in dict(s.tones) for s in tones[0].styles)

def test_helm_from_art_is_a_valid_helm():
    art = art_of(SPECS)
    for separate, count in ((False, 3), (True, 5)):
        item = helm_from_art(art, "TestHelm", separate_tones=separate)
        assert len(item.root.frames[0].placements) == count
        assert validate_helm_swf(export_helm(item), "TestHelm") == []

def test_parts_are_traced_separately():
    specs = [LayerSpec("Face", children=[LayerSpec("Flats", rect(W, H, RED, 0, 60, 120, 120))]),
             LayerSpec("Hair", children=[LayerSpec("Flats", rect(W, H, BLUE, 0, 0, 120, 70))])]
    assert [l.name for l in art_of(specs).layers] == ["Face: Fills", "Hair: Fills"]
