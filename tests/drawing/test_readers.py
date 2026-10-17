# tests/drawing/test_readers.py
import numpy as np
import pytest
from autoswf.drawing.layers import DrawingError
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.writers import LayerSpec, write_clip, write_psd

W, H = 40, 30
RED, BLUE, BLACK, WHITE = (200, 30, 30, 255), (40, 60, 200, 255), (10, 10, 10, 255), (255, 255, 255, 255)

def canvas(color, x0, y0, x1, y1):
    a = np.zeros((H, W, 4), np.uint8); a[y0:y1, x0:x1] = color; return a

LAYERS = [LayerSpec("Hair", children=[LayerSpec("Flats", canvas(RED, 5, 5, 30, 25)),
                                      LayerSpec("Sombra", canvas(BLUE, 20, 0, 40, 30), blend="multiply", opacity=0.5, clipping=True)]),
          LayerSpec("Sketch", canvas(BLACK, 0, 0, 10, 10), visible=False),
          LayerSpec("Line", canvas(BLACK, 5, 5, 30, 7))]

def check_tree(d, names):
    assert (d.width, d.height) == (W, H) and [n.name for n in d.layers] == names
    hair = d.layers[names.index("Hair")]
    assert hair.kind == "group" and [c.name for c in hair.children] == ["Flats", "Sombra"]
    flats, sombra = hair.children
    assert (flats.left, flats.top, flats.pixels.shape) == (5, 5, (20, 25, 4)) and tuple(flats.pixels[0, 0]) == RED
    assert (sombra.blend, sombra.clipping, round(sombra.opacity, 2)) == ("multiply", True, 0.5)
    assert (sombra.left, sombra.top, sombra.pixels.shape) == (20, 0, (30, 20, 4))
    assert not d.layers[names.index("Sketch")].visible
    assert [(n.name, len(a)) for n, a in d.walk()][:3] == [(names[0], 0), ("Hair", 0), ("Flats", 1)]

def test_psd_round_trip(tmp_path):
    write_psd(tmp_path / "a.psd", W, H, [LayerSpec("Paper", canvas(WHITE, 0, 0, W, H))] + LAYERS)
    check_tree(read_drawing(tmp_path / "a.psd"), ["Paper", "Hair", "Sketch", "Line"])

def test_clip_round_trip(tmp_path):
    write_clip(tmp_path / "a.clip", W, H, LAYERS)
    check_tree(read_drawing(tmp_path / "a.clip"), ["Paper", "Hair", "Sketch", "Line"])

def test_psd_layer_mask_is_applied(tmp_path):
    from PIL import Image
    from psd_tools import PSDImage
    write_psd(tmp_path / "m.psd", W, H, [LayerSpec("Flats", canvas(RED, 0, 0, W, H))])
    psd = PSDImage.open(tmp_path / "m.psd")
    m = np.zeros((H, W), np.uint8); m[:, :20] = 255
    psd[0].create_mask(Image.fromarray(m, "L")); psd.save(tmp_path / "m.psd")
    flats = read_drawing(tmp_path / "m.psd").layers[0]
    assert (flats.left, flats.pixels.shape[1]) == (0, 20)

def test_png_is_one_flattened_layer(tmp_path):
    from PIL import Image
    Image.fromarray(canvas(RED, 5, 5, 30, 25), "RGBA").save(tmp_path / "helm.png")
    d = read_drawing(tmp_path / "helm.png")
    assert d.flattened and [(n.name, n.kind) for n in d.layers] == [("helm", "pixel")]

def test_unsupported_and_broken_files(tmp_path):
    (tmp_path / "a.txt").write_text("x"); (tmp_path / "b.psd").write_bytes(b"not a psd")
    with pytest.raises(DrawingError, match=r"Unsupported file type '\.txt'; AutoSWF opens \.clip, \.psd and \.png files"):
        read_drawing(tmp_path / "a.txt")
    with pytest.raises(DrawingError, match="Could not read b.psd"):
        read_drawing(tmp_path / "b.psd")

@pytest.mark.real
def test_real_clip_studio_file(real_drawing):
    d = read_drawing(real_drawing)
    assert (d.width, d.height) == (1600, 1200) and [n.name for n in d.layers] == ["Paper", "Layer 1"]
    sketch = d.layers[1]
    assert sketch.kind == "pixel" and sketch.pixels.shape[0] < 1200 and sketch.pixels[..., 3].max() == 255
