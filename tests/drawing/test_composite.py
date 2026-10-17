# tests/drawing/test_composite.py
import clipparse
import numpy as np
import pytest
from psd_tools import PSDImage
from autoswf.drawing.composite import blend, composite
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.writers import LayerSpec, write_clip, write_psd

W, H = 40, 30
def canvas(color, x0, y0, x1, y1):
    a = np.zeros((H, W, 4), np.uint8); a[y0:y1, x0:x1] = color; return a

def straight(p):
    a = p[..., 3:4]; return np.where(a > 0, p[..., :3] / np.maximum(a, 1e-6), 0)

@pytest.mark.parametrize("mode, cb, cs, out", [
    ("multiply", .5, .5, .25), ("screen", .5, .5, .75), ("overlay", .25, .8, .4), ("soft_light", .25, .8, .4),
    ("hard_light", .8, .25, .4), ("add", .7, .6, 1.0), ("color_dodge", .25, .5, .5), ("color_burn", .75, .5, .5),
    ("difference", .2, .7, .5), ("darken", .2, .7, .2), ("lighten", .2, .7, .7), ("subtract", .7, .2, .5)])
def test_blend_formulas(mode, cb, cs, out):
    assert blend(mode, np.array([cb]), np.array([cs]))[0] == pytest.approx(out, abs=1e-6)

SPEC = [LayerSpec("Hair", children=[LayerSpec("Flats", canvas((200, 120, 60, 255), 5, 5, 30, 25)),
                                    LayerSpec("Sombra", canvas((90, 70, 170, 255), 18, 0, 40, 30), blend="multiply", opacity=0.6, clipping=True),
                                    LayerSpec("Luz", canvas((255, 230, 150, 255), 8, 8, 14, 14), blend="screen", clipping=True)]),
        LayerSpec("Line", canvas((20, 10, 30, 255), 5, 5, 30, 7))]
WHITE = LayerSpec("Paper", canvas((255, 255, 255, 255), 0, 0, W, H))

def test_matches_psd_tools(tmp_path):
    write_psd(tmp_path / "a.psd", W, H, [WHITE] + SPEC)
    ours = straight(composite(read_drawing(tmp_path / "a.psd")))
    ref = np.asarray(PSDImage.open(tmp_path / "a.psd").composite().convert("RGB")) / 255
    assert np.abs(ours - ref).max() <= 2 / 255

def test_matches_clip_studio_merge(tmp_path):
    write_clip(tmp_path / "a.clip", W, H, SPEC)
    ours = straight(composite(read_drawing(tmp_path / "a.clip")))
    c = clipparse.ClipFile(); c.load(str(tmp_path / "a.clip"))
    ref = np.frombuffer(c.merged_image(), np.uint8).reshape(H, W, 4)[..., [2, 1, 0]] / 255
    assert np.abs(ours - ref).max() <= 2 / 255

def test_excluded_clipping_base_still_masks(tmp_path):
    write_psd(tmp_path / "a.psd", W, H, SPEC)
    d = read_drawing(tmp_path / "a.psd")
    only = composite(d, include=lambda n: n.name == "Sombra")
    assert only[10, 35, 3] == 0 and only[10, 25, 3] == pytest.approx(0.6, abs=0.01)
    assert straight(only)[10, 25] == pytest.approx(np.array([90, 70, 170]) / 255, abs=0.01)
    cov = composite(d, include=lambda n: n.name == "Sombra", force_normal=True)
    assert cov[10, 25, 3] == pytest.approx(0.6, abs=0.01)

def test_folder_isolation_opacity_and_unsupported_modes(tmp_path):
    gray, light = canvas((128, 128, 128, 255), 0, 0, W, H), canvas((200, 200, 200, 255), 0, 0, 20, H)
    for mode, expected in (("pass_through", 227), ("normal", 200)):     # screen sees the paper only through a pass-through folder
        write_psd(tmp_path / "f.psd", W, H, [LayerSpec("Paper", gray), LayerSpec("G", children=[LayerSpec("S", light, blend="screen")], blend=mode)])
        assert composite(read_drawing(tmp_path / "f.psd"))[5, 5, 0] * 255 == pytest.approx(expected, abs=1.5)
    a, b = canvas((255, 0, 0, 255), 0, 0, 20, 30), canvas((0, 0, 255, 255), 10, 0, 30, 30)
    write_psd(tmp_path / "o.psd", W, H, [LayerSpec("G", children=[LayerSpec("A", a), LayerSpec("B", b)], opacity=0.5)])
    assert composite(read_drawing(tmp_path / "o.psd"))[5, 15, 3] == pytest.approx(0.5, abs=0.01)   # folder opacity once, not per child
    write_psd(tmp_path / "h.psd", W, H, [LayerSpec("A", a), LayerSpec("B", b, blend="hue")])
    notes = set()
    composite(read_drawing(tmp_path / "h.psd"), notes=notes)
    assert notes == {"Blend mode 'hue' of layer 'B' is drawn as normal"}
