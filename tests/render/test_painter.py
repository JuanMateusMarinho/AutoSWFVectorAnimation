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


def test_raster_cache_reuses_shapes_and_matches_direct_drawing(qapp):
    tags = [shape_tag(1, 3, fills=[("solid", RED)], lines=[(0.05, (0, 0, 0, 255))], paths=[dict(sq(0, 0, 10, 10), line=1)]),
            sprite_tag(2, [[place2(1, cid=1, matrix=Matrix(1.5, 0.3, -0.3, 1.5, 4, 3)), place2(2, cid=1, matrix=Matrix.translate(20, 20))]])]
    obj = instantiate(MovieData(swf(tags)), 2)
    cached, direct = Renderer(), Renderer(cache_bytes=0)
    cached.render_image(obj, 40, 40, Matrix(), None)
    again = cached.render_image(obj, 40, 40, Matrix(), None)
    plain = direct.render_image(obj, 40, 40, Matrix(), None)
    assert cached.cache_hits >= 2 and direct.cache_hits == 0
    assert all(abs(a - b) <= 2 for y in range(40) for x in range(40) for a, b in zip(rgba(again, x, y), rgba(plain, x, y)))

# one shape: fill 1 is the upper-right triangle and fill 2 the lower-left one; they share the diagonal (0,0)-(20,20)
TRIANGLES = [{"fill1": 1, "start": (0, 0), "edges": [(20, 0), (20, 20)]},
             {"fill1": 2, "start": (20, 20), "edges": [(0, 20), (0, 0)]},
             {"fill0": 1, "fill1": 2, "start": (0, 0), "edges": [(20, 20)]}]

def test_fills_sharing_an_edge_leave_no_seam(qapp):
    tags = [shape_tag(1, 3, fills=[("solid", RED), ("solid", BLUE)], lines=[], paths=TRIANGLES)]
    for renderer in (Renderer(), Renderer(cache_bytes=0)):
        obj = instantiate(MovieData(swf(tags)), 1)
        img = renderer.render_image(obj, 30, 30, Matrix.scale(1.0, 1.0), None)
        assert min(rgba(img, x, y)[3] for x in range(1, 19) for y in range(1, 19)) >= 254
        assert rgba(img, 15, 3) == RED and rgba(img, 3, 15) == BLUE

def test_seam_free_fills_add_each_fill_once(qapp):
    # the triangles' boxes overlap, so the second fill's box holds the first one's pixels, and the renderer keeps the
    # layers' memory from shape to shape; colors that do not saturate would show pixels added twice
    dark_red, dark_blue = (120, 0, 0, 255), (0, 0, 120, 255)
    tags = [shape_tag(1, 3, fills=[("solid", dark_red), ("solid", dark_blue)], lines=[], paths=TRIANGLES)]
    renderer = Renderer(cache_bytes=0)
    for _ in range(2):
        img = renderer.render_image(instantiate(MovieData(swf(tags)), 1), 30, 30, Matrix(), None)
        assert rgba(img, 15, 3) == dark_red and rgba(img, 3, 15) == dark_blue

def test_seam_free_fills_cost_little_more_than_drawing_them_one_by_one(qapp, monkeypatch):
    import time
    colors = [((37 * i) % 256, (91 * i) % 256, (151 * i) % 256, 255) for i in range(36)]
    paths = [sq(10 * c, 10 * r, 10 * c + 10, 10 * r + 10, fill=6 * r + c + 1) for r in range(6) for c in range(6)]
    obj = instantiate(MovieData(swf([shape_tag(1, 3, fills=[("solid", c) for c in colors], lines=[], paths=paths)])), 1)
    renderer, view = Renderer(cache_bytes=0), Matrix(4.1, 0.3, -0.3, 4.1, 20.3, 5.7)

    def one_by_one(self, p, transform, fills):    # source-over, fill after fill: the way that leaves seams
        p.setTransform(transform)
        for path, brush in fills:
            p.setBrush(brush)
            p.drawPath(path)

    def run_seconds(paint_fills):                 # 10 frames with no raster cache
        monkeypatch.setattr(Renderer, "_paint_fills_seamless", paint_fills)
        start = time.perf_counter()
        for _ in range(10):
            renderer.render_image(obj, 280, 280, view, None)
        return time.perf_counter() - start

    seamless = Renderer._paint_fills_seamless
    run_seconds(seamless), run_seconds(one_by_one)                    # warm-up
    runs = [(run_seconds(seamless), run_seconds(one_by_one)) for _ in range(7)]  # interleaved: load changes hit both
    seam_free, plain = min(s for s, _ in runs), min(p for _, p in runs)
    assert seam_free < 3 * plain, (seam_free, plain)


def test_an_overridden_shape_is_drawn_fresh(qapp):
    from autoswf.edit.swf_source import shape_def_of
    from editor_fixtures import rect_area, shape_of
    movie = MovieData(swf([shape_tag(1, 1, [("solid", RED)], [], [sq(0, 0, 20, 20)])]))
    obj = instantiate(movie, 1)
    renderer = Renderer()
    before = renderer.render_image(obj, 40, 40, Matrix(), None)
    movie.override(1, shape_def_of(shape_of({0: rect_area(0, 0, 20, 20)}, [BLUE]), 1))
    after = renderer.render_image(obj, 40, 40, Matrix(), None)
    assert rgba(before, 10, 10)[:3] == (255, 0, 0) and rgba(after, 10, 10)[:3] == (0, 0, 255)
    assert movie.overrides == {1: 1}
