# tests/parts/test_assemble.py
import dataclasses
import numpy as np
import pytest
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import Symbol
from autoswf.model.geometry import Matrix
from autoswf.parts.assemble import assemble_helm, face_shade, head_to_backhair, instance_name
from autoswf.render.colors import PlayerColors
from autoswf.vectorize.art import FaceStyle

def render(swf, t, colors, hide=()):
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    movie = MovieData(swf)
    obj = instantiate(movie, movie.classes["PartsHelm"])
    run_pending_actions(obj, ScriptContext(colors))
    def walk(clip):
        for child in getattr(clip, "children", []):
            if child.name in hide:
                child.visible = False
            walk(child)
    walk(obj)
    view = Matrix.translate(*t.alignment.origin) @ Matrix.scale(t.alignment.scale, t.alignment.scale)
    img = qimage_to_array(Renderer(cache_bytes=0).render_image(obj, t.width, t.height, view, colors))
    a = img[..., 3:4]
    return np.dstack([np.where(a > 0, img[..., :3] / np.maximum(a, 1e-9), 0) * 255, a[..., 0] * 255])

def at(img, t, x, y):
    s, (ox, oy) = t.alignment.scale, t.alignment.origin
    return tuple(int(round(v)) for v in img[int(oy + y * s), int(ox + x * s)])

def test_shades_names_and_the_back_hair_matrix():
    style = lambda *tones: FaceStyle((0, 0, 0, 255), (1, 1, 1, 255), tones)
    assert face_shade(style(), frozenset()) == "None"
    assert face_shade(style(("shadow", 1)), frozenset()) == "Dark"
    assert face_shade(style(("shadow", 1), ("occlusion", 1)), frozenset()) == "Darker"
    assert face_shade(style(("shadow", 1), ("light", 1)), frozenset()) == "Light"
    assert face_shade(style(("light", 1)), frozenset({"light"})) == "None"
    assert face_shade(style(("light", 2)), frozenset({"light"})) == "Light"
    assert [instance_name(n) for n in ("Lock 3", "Eye L ball", "Back hair", "Helm")] == ["lock3", "eyeLBall", "backHair", "helm"]
    m = head_to_backhair()
    assert abs(m.a - 0.2633) < 1e-3 and abs(m.b + 0.0033) < 1e-3 and abs(m.tx - 5.86) < 0.02 and abs(m.ty - 14.87) < 0.02

def test_structure_and_validity(converted_parts_helm):
    c = converted_parts_helm
    assert validate_helm_swf(c.swf, "PartsHelm") == []
    top = c.helm.item.root.frames[0].placements
    assert [p.name for p in top] == ["face", "mouth", "earL", "browL", "browR", "eyeL", "eyeR", "hair", "lock1",
                                     "lock2", "lock3", "lock4", "lock5", "lock6", "hornR", "helm", "accessory1"]
    assert [p.name for p in top[5].item.frames[0].placements] in (["eyeLBall", "eyeLLash", "eyeLLid"],
                                                                  ["eyeLBall", "eyeLLid"])
    assert set(c.helm.colorable) == {
        ("Face", "Skin", "None"), ("Face", "Skin", "Dark"), ("Ear L", "Skin", "None"), ("Brow L", "Hair", "None"),
        ("Brow R", "Hair", "None"), ("Eye L ball", "Eye", "None"), ("Eye R ball", "Eye", "None"),
        ("Hair", "Hair", "None"), ("Hair", "Hair", "Darker"), ("Hair", "Hair", "Light")} | {
        ("Lock %d" % k, "Hair", "None") for k in range(1, 7)}
    for wrapper in c.helm.wrappers.values():
        for p in wrapper.frames[0].placements:
            if isinstance(p.item, Symbol) and p.item.color_custom is not None:
                assert p.matrix == Matrix() and p.color is None
                assert all(not isinstance(q.item, Symbol) for q in p.item.frames[0].placements)
    assert all(p.item.color_custom is None for p in top)

@pytest.mark.parametrize("colors", [PlayerColors(hair=0xC02030, skin=0x80C0FF, eye=0x20FF40),
                                    PlayerColors(hair=0x30A0F0, skin=0x6B4423, eye=0xFFD000)])
def test_hair_skin_and_irises_follow_the_player(converted_parts_helm, colors):
    c = converted_parts_helm
    t, img = c.t, render(c.swf, c.t, colors)
    rgb = lambda v: ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    near = lambda got, want: max(abs(g - w) for g, w in zip(got[:3], want)) <= 3
    assert near(at(img, t, -11, -2), rgb(colors.hair))                     # inside Lock 3
    assert near(at(img, t, -30, -10.5), rgb(colors.hair))                  # hair band, between its tones
    assert near(at(img, t, -30, -12.3), tuple(max(0, v - 125) for v in rgb(colors.hair)))   # occlusion: Darker
    assert near(at(img, t, -25, 28), rgb(colors.skin))                     # cheek
    r, g, b = rgb(colors.skin)
    assert near(at(img, t, 12, 22), (max(0, r - 25), max(0, g - 50), max(0, b - 50)))       # cheek shadow: Dark
    assert near(at(img, t, -18.7, 14.5), rgb(colors.eye))                  # iris, beside the pupil
    assert near(at(img, t, -26, 14), (255, 255, 255))                      # eye white keeps its color
    assert near(at(img, t, -21, 14.5), (20, 20, 30))                       # pupil keeps its color

def test_drawn_colors_render_like_the_drawing(converted_parts_helm):
    from autoswf.vectorize.metrics import quality_report
    c = converted_parts_helm
    report = quality_report(c.passes, c.art, c.swf, "PartsHelm")
    assert report.problems() == [], report.format()

def test_hidden_parts_leave_no_holes(converted_parts_helm):
    from scipy import ndimage
    c = converted_parts_helm
    for name, region in (("lock3", "Lock 3"), ("eyeLBall", "Eye L")):
        img = render(c.swf, c.t, PlayerColors(), hide={name})
        inside = ndimage.binary_erosion(c.t.truth[region], iterations=3)
        assert (img[inside][:, 3] >= 250).all(), name

def test_wrappers_sit_at_their_pivots(converted_parts_helm):
    c = converted_parts_helm
    m = c.helm.placements["Lock 3"].matrix
    rx, ry = c.t.roots["Lock 3"]
    assert (m.a, m.b, m.c, m.d) == (1, 0, 0, 1) and np.hypot(m.tx - rx, m.ty - ry) <= 1.5

def test_parts_that_trace_to_nothing_are_left_out(converted_parts_helm):
    c = converted_parts_helm
    art = dataclasses.replace(c.art, layers=[l for l in c.art.layers if l.part != "Accessory 1"])
    helm = assemble_helm(art, c.layers, "PartsHelm")
    assert "Accessory 1" not in helm.wrappers
    assert "accessory1" not in [p.name for p in helm.item.root.frames[0].placements]
    assert all(w.frames[0].placements for w in helm.wrappers.values())
    assert validate_helm_swf(export_helm(helm.item), "PartsHelm") == []

def test_back_hair_gets_its_own_class(qapp):
    from drawings import disc, drawing_from_specs, rect
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.drawing.writers import LayerSpec
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.swf.reader import SWF
    from autoswf.vectorize.art import vectorize
    W = H = 240
    specs = [LayerSpec("Back hair", children=[LayerSpec("Flats", rect(W, H, (120, 70, 40, 255), 60, 120, 180, 230))]),
             LayerSpec("Flats", disc(W, H, (240, 200, 160, 255), 120, 110, 70))]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    alignment = Alignment(2.4, (120, 120))
    layers = split_passes(passes, detect_parts(passes, alignment))
    helm = assemble_helm(vectorize(layered_passes(passes, layers), alignment), layers, "BH")
    swf = export_helm(helm.item)
    assert "BH_backhair" in SWF(swf).symbols.values() and validate_helm_swf(swf, "BH") == []
    assert helm.item.backhair.frames[0].placements[0].matrix.a == pytest.approx(head_to_backhair().a)
    assert ("Back hair", "Hair", "None") in helm.colorable
    assert "backHair" not in [p.name for p in helm.item.root.frames[0].placements]


@pytest.mark.aqw
def test_back_hair_shows_in_idle_where_it_was_drawn(qapp, aqw_cache):
    from drawings import disc, drawing_from_specs, rect
    from autoswf.aqw.helm import HelmItem
    from autoswf.aqw.rig import AvatarRig
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.drawing.writers import LayerSpec
    from autoswf.model.document import Frame, Placement
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.render.painter import object_bounds
    from autoswf.swf.decode import MovieData
    from autoswf.vectorize.art import vectorize
    W = H = 240
    specs = [LayerSpec("Back hair", children=[LayerSpec("Flats", rect(W, H, (120, 70, 40, 255), 60, 120, 180, 230))]),
             LayerSpec("Flats", disc(W, H, (240, 200, 160, 255), 120, 110, 70))]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    alignment = Alignment(2.4, (120, 120))
    layers = split_passes(passes, detect_parts(passes, alignment))
    helm = assemble_helm(vectorize(layered_passes(passes, layers), alignment), layers, "BH")
    art = helm.item.backhair.frames[0].placements[0].item          # the back hair in head-local space
    in_helm = export_helm(HelmItem("BHB", Symbol("BHB", [Frame([Placement(art, 1)])])))
    client = MovieData(aqw_cache.client_path())
    for gender in "MF":
        rig = AvatarRig(client, gender, helm=MovieData(export_helm(helm.item)), helm_link="BH")
        drawn = object_bounds(rig._slot("backhair"), Matrix())
        reference = AvatarRig(client, gender, helm=MovieData(in_helm), helm_link="BHB")
        head = reference.head()
        expected = object_bounds(head.child_by_name("helm"), head.matrix)
        assert max(abs(a - b) for a, b in zip(drawn, expected)) <= 1.0, (gender, drawn, expected)
