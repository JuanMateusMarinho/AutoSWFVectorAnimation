# tests/render/test_painter.py
from swf_builders import morph_tag, place2, shape_tag, sprite_tag, swf
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import MovieData

RED, BLUE, WHITE = (255, 0, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)

def sq(x0, y0, x1, y1, fill=1):
    return {"fill1": fill, "start": (x0, y0), "edges": [(x1, y0), (x1, y1), (x0, y1), (x0, y0)]}

def draw(tags, cid, size=40, scale=1.0, colors=None):
    obj = instantiate(MovieData(swf(tags)), cid)
    run_pending_actions(obj, ScriptContext(colors))
    return Renderer().render_image(obj, size, size, Matrix.scale(scale, scale), colors)

def rgba(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue(), c.alpha())

def test_solid_square_scaled(qapp):
    img = draw([shape_tag(1, 3, fills=[("solid", RED)], lines=[], paths=[sq(0, 0, 10, 10)])], 1, scale=2)
    assert rgba(img, 10, 10) == RED and rgba(img, 30, 30)[3] == 0

def test_even_odd_hole_and_nonzero_fill(qapp):
    paths = [sq(0, 0, 30, 30), sq(10, 10, 20, 20)]
    eo = draw([shape_tag(1, 3, fills=[("solid", RED)], lines=[], paths=paths)], 1)
    nz = draw([shape_tag(1, 4, fills=[("solid", RED)], lines=[], paths=paths, nonzero=True)], 1)
    assert rgba(eo, 15, 15)[3] == 0 and rgba(eo, 5, 5) == RED and rgba(nz, 15, 15) == RED

def test_linear_gradient(qapp):
    g = ("linear", Matrix(a=20 / 1638.4, d=20 / 1638.4, tx=10, ty=10), [(0, (0, 0, 0, 255)), (255, WHITE)])
    img = draw([shape_tag(1, 3, fills=[g], lines=[], paths=[sq(0, 0, 20, 20)])], 1)
    r, g_, b, a = rgba(img, 10, 10)
    assert a == 255 and r == g_ == b and abs(r - 134) <= 3          # pixel center x = 10.5 -> 52.5 % of the ramp
    assert rgba(img, 0, 10)[0] < 20 and rgba(img, 19, 10)[0] > 235

def test_clip_color_transform(qapp):
    tags = [shape_tag(1, 3, fills=[("solid", (100, 100, 100, 255))], lines=[], paths=[sq(0, 0, 20, 20)]),
            sprite_tag(2, [[place2(1, cid=1, cx=ColorTransform((0.5, 1.0, 1.0, 1.0), (10, -100, 0, 0)))]])]
    assert rgba(draw(tags, 2), 10, 10) == (60, 0, 100, 255)

def test_line_only_shape_keeps_a_one_pixel_hairline_when_scaled_down(qapp):
    line = {"line": 1, "start": (0, 100), "edges": [(400, 100)]}
    img = draw([shape_tag(1, 3, fills=[], lines=[(0.05, (0, 0, 0, 255))], paths=[line])], 1, scale=0.1)
    assert max(rgba(img, 20, y)[3] for y in (9, 10)) >= 100

def test_clip_depth_mask(qapp):
    tags = [shape_tag(1, 3, fills=[("solid", BLUE)], lines=[], paths=[sq(0, 0, 10, 10)]),
            shape_tag(2, 3, fills=[("solid", RED)], lines=[], paths=[sq(0, 0, 20, 20)]),
            sprite_tag(3, [[place2(1, cid=1, clip_depth=2), place2(2, cid=2), place2(3, cid=2, matrix=Matrix.translate(20, 20))]])]
    img = draw(tags, 3)
    assert rgba(img, 5, 5) == RED and rgba(img, 15, 15)[3] == 0 and rgba(img, 25, 25) == RED

def test_morph_shape_at_half_ratio(qapp):
    tags = [morph_tag(1, RED, BLUE, start=[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], end=[(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)]),
            sprite_tag(2, [[place2(1, cid=1, ratio=32768)]])]
    img = draw(tags, 2)
    r, g, b, a = rgba(img, 15, 15)
    assert a == 255 and abs(r - 128) <= 2 and abs(b - 128) <= 2 and rgba(img, 25, 25)[3] == 0

def test_bounds_and_invisible_objects(qapp):
    md = MovieData(swf([shape_tag(1, 3, fills=[("solid", RED)], lines=[], paths=[sq(5, 5, 15, 25)]), sprite_tag(2, [[place2(1, cid=1)]])]))
    obj = instantiate(md, 2)
    assert object_bounds(obj, Matrix.translate(1, 0)) == (6.0, 16.0, 5.0, 25.0)
    obj.visible = False
    assert Renderer().render_image(obj, 30, 30, Matrix(), None).pixelColor(10, 10).alpha() == 0

def test_render_command_paints_player_skin(tmp_path, qapp):
    from PySide6.QtGui import QImage
    from autoswf.cli import main
    demo, png = tmp_path / "demo.swf", tmp_path / "demo.png"
    main(["demo-helm", str(demo)])
    assert main(["render", str(demo), "--class", "AutoSwfDemoMorph", "--out", str(png), "--scale", "3"]) == 0
    img, skin = QImage(str(png)), PlayerColors().skin
    target = ((skin >> 16) & 255, (skin >> 8) & 255, skin & 255, 255)
    assert sum(rgba(img, x, y) == target for y in range(img.height()) for x in range(img.width())) > 100
    assert main(["render", str(demo), "--class", "Nope", "--out", str(png)]) == 1
