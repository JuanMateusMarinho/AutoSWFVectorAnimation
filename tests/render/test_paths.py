# tests/render/test_paths.py
from autoswf.swf.decode import Edge, LineStyle, MorphShapeDef, ShapeDef, SolidStyle
from autoswf.render.paths import fill_paths, interpolate_morph, stroke_paths

def E(a, b, fill0=None, fill1=None, line=None, control=None, layer=0):
    return Edge(a, control, b, fill0, fill1, line, layer)

def shape(edges, fills=2, lines=()):
    return ShapeDef(1, (0, 0, 0, 0), tuple(SolidStyle((0, 0, 0, 255)) for _ in range(fills)), tuple(lines), tuple(edges), False)

def points(segments):
    return [segments[0][0]] + [end for _, _, end in segments]

def test_two_squares_sharing_an_edge():
    edges = [E((0, 0), (20, 0), fill1=0), E((20, 0), (20, 20), fill0=1, fill1=0), E((20, 20), (0, 20), fill1=0),
             E((0, 20), (0, 0), fill1=0), E((20, 0), (40, 0), fill1=1), E((40, 0), (40, 20), fill1=1), E((40, 20), (20, 20), fill1=1)]
    fp = fill_paths(shape(edges))
    assert [(p.layer, p.fill) for p in fp] == [(0, 0), (0, 1)]
    assert [points(c) for c in fp[0].contours] == [[(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]]
    assert [points(c) for c in fp[1].contours] == [[(20, 20), (20, 0), (40, 0), (40, 20), (20, 20)]]

def test_open_contour_is_kept_and_same_fill_on_both_sides_is_skipped():
    edges = [E((0, 0), (20, 0), fill1=0), E((20, 0), (20, 20), fill1=0), E((5, 5), (6, 6), fill0=0, fill1=0)]
    assert [points(c) for c in fill_paths(shape(edges, fills=1))[0].contours] == [[(0, 0), (20, 0), (20, 20)]]

def test_stroke_runs_split_where_edges_do_not_connect():
    pen = LineStyle(1.0, SolidStyle((0, 0, 0, 255)))
    edges = [E((0, 0), (20, 0), line=0), E((20, 0), (20, 20), line=0), E((40, 0), (60, 0), line=0)]
    sp = stroke_paths(shape(edges, fills=0, lines=[pen]))
    assert [(p.layer, p.line) for p in sp] == [(0, 0)]
    assert [points(r) for r in sp[0].runs] == [[(0, 0), (20, 0), (20, 20)], [(40, 0), (60, 0)]]

def test_morph_halfway_pairs_straight_with_curved_edges():
    start = shape([E((0, 0), (200, 0), fill1=0), E((200, 0), (0, 0), fill1=0, control=(100, 0))], fills=1)
    end = ShapeDef(1, (0, 0, 0, 0), (SolidStyle((0, 0, 255, 255)),), (),
                   (E((0, 0), (400, 0), fill1=0, control=(200, 200)), E((400, 0), (0, 0), fill1=0)), False)
    mid = interpolate_morph(MorphShapeDef(1, start, end), 0.5)
    assert mid.fills == (SolidStyle((0, 0, 128, 255)),)
    assert [(e.start, e.control, e.end) for e in mid.edges] == [((0, 0), (150, 100), (300, 0)), ((300, 0), (150, 0), (0, 0))]
