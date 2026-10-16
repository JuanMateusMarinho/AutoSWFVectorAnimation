# tests/render/test_effects.py
from swf_builders import place3, shape_tag, sprite_tag, swf
from autoswf.model.geometry import Matrix
from autoswf.render.display import instantiate
from autoswf.render.painter import Renderer
from autoswf.swf.decode import BlurFilter, ColorMatrixFilter, GlowFilter, MovieData

RED, WHITE = (255, 0, 0, 255), (255, 255, 255, 255)
GRAY = (0.3086, 0.6094, 0.082, 0, 0) * 3 + (0, 0, 0, 1, 0)

def scene(color, x0, x1, **place):
    sq = {"fill1": 1, "start": (x0, x0), "edges": [(x1, x0), (x1, x1), (x0, x1), (x0, x0)]}
    return MovieData(swf([shape_tag(1, 3, fills=[("solid", color)], lines=[], paths=[sq]), sprite_tag(2, [[place3(1, cid=1, **place)]])]))

def render(md, renderer=None, background=None):
    return (renderer or Renderer()).render_image(instantiate(md, 2), 40, 40, Matrix(), None, background=background)

def rgba(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())

def test_overlay_blend_keeps_the_backdrop_under_mid_gray(qapp):
    # W3C/Flash overlay of 50 % gray leaves the backdrop almost unchanged; a normal draw would give gray
    r, g, b, _ = rgba(render(scene((128, 128, 128, 255), 0, 40, blend=13), background=(200, 100, 50, 255)), 10, 10)
    assert abs(r - 200) <= 3 and abs(g - 100) <= 3 and abs(b - 50) <= 3

def test_color_matrix_grayscale(qapp):
    r, g, b, a = rgba(render(scene(RED, 10, 30, filters=[ColorMatrixFilter(GRAY)])), 20, 20)
    assert a == 255 and r == g == b and abs(r - 79) <= 2

def test_blur_softens_edges(qapp):
    img = render(scene(WHITE, 10, 30, filters=[BlurFilter(8.0, 8.0, 1)]))
    assert rgba(img, 20, 20)[3] == 255 and 0 < rgba(img, 10, 20)[3] < 255 and rgba(img, 7, 20)[3] > 0

def test_outer_glow_only_outside(qapp):
    img = render(scene(WHITE, 10, 30, filters=[GlowFilter(RED, 8.0, 8.0, 1.0, False, False, 1)]))
    r, g, b, a = rgba(img, 8, 20)
    assert rgba(img, 20, 20) == WHITE and a > 0 and r > 200 and g < 30

def test_unsupported_effects_are_noted(qapp):
    renderer = Renderer()
    render(scene(WHITE, 10, 30, filters=[b"\x03" + bytes(27)], blend=9), renderer)
    assert {"Bevel filter is not rendered", "Blend mode 'subtract' is approximated"} <= renderer.notes
