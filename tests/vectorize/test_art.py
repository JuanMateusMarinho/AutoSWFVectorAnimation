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

def test_fills_extend_under_the_line_art_they_only_touch(qapp):
    # flats stop exactly where an outline starts (official AQW art, or a bucket fill up to the line): the fill shape
    # must reach under the line's opaque core, or the two abutting shapes leave a seam
    from autoswf.aqw.helm import HelmItem
    from autoswf.model.document import Frame, Placement, Symbol
    from autoswf.model.geometry import Matrix
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    art = art_of([LayerSpec("Flats", disc(W, H, RED, 60, 60, 40)), LayerSpec("Line", ring(W, H, INK, 60, 60, 47, 40))])
    fills = art.layers[0]
    md = MovieData(export_helm(HelmItem("F", Symbol("F", [Frame([Placement(fills.shape, 1)])]))))
    obj = instantiate(md, md.classes["F"]); run_pending_actions(obj, ScriptContext(None))
    img = qimage_to_array(Renderer().render_image(obj, W, H, Matrix.scale(4, 4) @ Matrix.translate(15, 15), None))
    assert img[60, 103, 3] == 1 and img[60, 108, 3] == 0         # under the line core (r 43), not past it (r 48)
    assert all(s.color[:3] == RED[:3] for s in fills.styles)

def test_one_tone_layer_with_two_tints_keeps_both():
    # artists often paint one multiply layer with a different tint per area: same flat + same tone level, two colors
    specs = [LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H)),
             LayerSpec("Shadow", rect(W, H, BLUE, 0, 0, 60, H) + rect(W, H, (230, 200, 120, 255), 60, 0, W, H),
                       blend="multiply", clipping=True)]
    fills = art_of(specs).layers[0]
    tinted = sorted(s.color[:3] for s in fills.styles if s.tones == (("shadow", 1),))
    expected = sorted(tuple(int(round(v)) for v in blend("multiply", np.array(RED[:3]) / 255, np.array(c) / 255) * 255)
                      for c in (BLUE[:3], (230, 200, 120)))
    assert len(tinted) == 2 and np.abs(np.array(tinted) - np.array(expected)).max() <= 2

def test_low_opacity_details_and_lines_keep_their_opacity():
    specs = [LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H)),
             LayerSpec("Details", rect(W, H, (255, 255, 255, 255), 10, 70, 50, 110), opacity=0.3),
             LayerSpec("Line", ring(W, H, INK, 30, 30, 18, 13)),
             LayerSpec("Line 2", ring(W, H, INK, 90, 30, 18, 13), opacity=0.4)]
    art = art_of(specs)
    assert [l.name for l in art.layers] == ["Fills", "Details", "Line"]
    (detail,) = art.layers[1].styles
    assert detail.color[:3] == (255, 255, 255) and abs(detail.color[3] - 77) <= 6
    alphas = sorted(s.color[3] for s in art.layers[2].styles)
    assert len(alphas) == 2 and abs(alphas[0] - 102) <= 8 and alphas[1] == 255

def test_thin_lines_stay_opaque_and_whole(qapp):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPen
    from drawings import _qt_layer
    from autoswf.vectorize.metrics import _inverse, _render
    strokes = [(3, (10, 15, 110, 15)), (2, (10, 30, 90, 110)), (1.5, (30, 30, 110, 110)), (1, (10, 50, 100, 83)),
               (1, (40, 10, 110, 80))]
    def paint(p):
        for width, (x0, y0, x1, y1) in strokes:
            pen = QPen(QColor(*INK[:3])); pen.setWidthF(width); pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen); p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    light = (240, 230, 200, 255)
    specs = [LayerSpec("Flats", rect(W, H, light, 0, 0, W, H)), LayerSpec("Line", _qt_layer(W, 1.0, (0, 0), paint))]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, Alignment(4, (60, 60)))
    assert all(s.color[3] >= 250 for s in art.layers[-1].styles)
    image = _render(export_helm(helm_from_art(art, "T")), "T", W, H, _inverse(art.alignment.matrix()))
    luma = image[..., :3] @ np.array([0.3, 0.59, 0.11]) * 255
    for width, (x0, y0, x1, y1) in strokes:
        t = np.linspace(0.1, 0.9, 20)
        xs, ys = (x0 + (x1 - x0) * t).astype(int), (y0 + (y1 - y0) * t).astype(int)
        dark = [min(luma[y - 1:y + 2, x - 1:x + 2].min(), 255) < 150 for x, y in zip(xs, ys)]
        assert sum(dark) >= 17, (width, (x0, y0, x1, y1), sum(dark))

def test_fills_never_cover_lines_below_them_or_hide_under_lone_lines():
    under = art_of([LayerSpec("Line", ring(W, H, INK, 60, 60, 47, 40)), LayerSpec("Flats", disc(W, H, RED, 60, 60, 40))])
    assert [l.name for l in under.layers] == ["Line", "Fills"]
    lone = art_of([LayerSpec("Flats", disc(W, H, RED, 40, 60, 25)), LayerSpec("Line", ring(W, H, INK, 95, 60, 15, 11))])
    (face,) = lone.layers[0].styles
    for art, x in ((under, 104), (lone, 108)):          # inside the ring's stroke, away from the flats: no fill there
        from autoswf.aqw.helm import HelmItem
        from autoswf.model.document import Frame, Placement, Symbol
        from autoswf.model.geometry import Matrix
        from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
        from autoswf.render.effects import qimage_to_array
        from autoswf.render.painter import Renderer
        from autoswf.swf.decode import MovieData
        fills = next(l for l in art.layers if l.role == "fills")
        md = MovieData(export_helm(HelmItem("F", Symbol("F", [Frame([Placement(fills.shape, 1)])]))))
        obj = instantiate(md, md.classes["F"]); run_pending_actions(obj, ScriptContext(None))
        img = qimage_to_array(Renderer().render_image(obj, W, H, Matrix.scale(4, 4) @ Matrix.translate(15, 15), None))
        assert img[60, x, 3] == 0

def test_translucent_flats_keep_their_opacity_and_empty_results_are_errors():
    from autoswf.drawing.layers import DrawingError
    (face,) = art_of([LayerSpec("Flats", disc(W, H, RED, 60, 60, 40), opacity=0.4)]).layers[0].styles
    assert face.color[:3] == RED[:3] and abs(face.color[3] - 102) <= 6
    with pytest.raises(DrawingError, match="Nothing was traced"):
        art_of([LayerSpec("Line", rect(W, H, INK, 10, 10, 12, 12))])
